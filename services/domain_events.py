"""
Domain Events System
Provides event-driven architecture for decoupled service communication
"""
from typing import Dict, Any, List, Callable, Awaitable, Optional
from datetime import datetime
from enum import Enum
import asyncio
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Domain event types"""
    # Envelope events
    ENVELOPE_CREATED = "envelope.created"
    ENVELOPE_ACTIVATED = "envelope.activated"
    ENVELOPE_VOIDED = "envelope.voided"
    ENVELOPE_EXPIRED = "envelope.expired"
    ENVELOPE_CLAIM_OPENED = "envelope.claim_opened"
    
    # Access grant events
    ACCESS_GRANT_CREATED = "access_grant.created"
    ACCESS_GRANT_REVOKED = "access_grant.revoked"
    ACCESS_GRANT_EXPIRED = "access_grant.expired"
    CAPACITY_EXCEEDED = "capacity.exceeded"
    
    # Incident/Claim events
    INCIDENT_REPORTED = "incident.reported"
    CLAIM_OPENED = "claim.opened"
    CLAIM_UPDATED = "claim.updated"
    CLAIM_APPROVED = "claim.approved"
    CLAIM_DENIED = "claim.denied"
    CLAIM_PAID = "claim.paid"
    
    # System events
    EMERGENCY_REVOCATION = "system.emergency_revocation"


@dataclass
class DomainEvent:
    """Base domain event"""
    event_type: EventType
    entity_type: str
    entity_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)
    data: Dict[str, Any] = field(default_factory=dict)
    actor_id: Optional[str] = None
    correlation_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "actor_id": self.actor_id,
            "correlation_id": self.correlation_id
        }


# Type for event handlers
EventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventDispatcher:
    """
    Central event dispatcher for domain events
    Supports both sync and async handlers
    """
    
    _instance: Optional['EventDispatcher'] = None
    
    def __new__(cls) -> 'EventDispatcher':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._event_store: List[DomainEvent] = []
        self._max_store_size = 10000
        self._initialized = True
        logger.info("EventDispatcher initialized")
    
    @classmethod
    def get_instance(cls) -> 'EventDispatcher':
        return cls()
    
    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to an event type"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        logger.debug(f"Handler subscribed to {event_type.value}")
    
    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe from an event type"""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass
    
    async def dispatch(self, event: DomainEvent) -> None:
        """Dispatch an event to all registered handlers"""
        # Store event
        self._event_store.append(event)
        if len(self._event_store) > self._max_store_size:
            self._event_store = self._event_store[-self._max_store_size:]
        
        # Get handlers
        handlers = self._handlers.get(event.event_type, [])
        
        if not handlers:
            logger.debug(f"No handlers for event {event.event_type.value}")
            return
        
        # Execute handlers concurrently
        tasks = []
        for handler in handlers:
            try:
                tasks.append(handler(event))
            except Exception as e:
                logger.error(f"Error calling handler for {event.event_type.value}: {e}")
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Handler {i} for {event.event_type.value} raised: {result}"
                    )
        
        logger.info(f"Dispatched event {event.event_type.value} to {len(handlers)} handlers")
    
    def dispatch_sync(self, event: DomainEvent) -> None:
        """Synchronously dispatch an event (for non-async contexts)"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule in running loop
                asyncio.create_task(self.dispatch(event))
            else:
                loop.run_until_complete(self.dispatch(event))
        except RuntimeError:
            # No event loop, create one
            asyncio.run(self.dispatch(event))
    
    def get_event_history(
        self,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        limit: int = 100
    ) -> List[DomainEvent]:
        """Get event history, optionally filtered by entity"""
        events = self._event_store
        
        if entity_type:
            events = [e for e in events if e.entity_type == entity_type]
        if entity_id:
            events = [e for e in events if str(e.entity_id) == str(entity_id)]
        
        return events[-limit:]


# Convenience functions for creating and dispatching events
def create_event(
    event_type: EventType,
    entity_type: str,
    entity_id: str,
    data: Optional[Dict[str, Any]] = None,
    actor_id: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> DomainEvent:
    """Create a domain event"""
    return DomainEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        data=data or {},
        actor_id=actor_id,
        correlation_id=correlation_id
    )


async def publish_event(event: DomainEvent) -> None:
    """Publish a domain event"""
    dispatcher = EventDispatcher.get_instance()
    await dispatcher.dispatch(event)


def publish_event_sync(event: DomainEvent) -> None:
    """Publish a domain event synchronously"""
    dispatcher = EventDispatcher.get_instance()
    dispatcher.dispatch_sync(event)


# Event handler decorator
def on_event(event_type: EventType):
    """Decorator to register an event handler"""
    def decorator(func: EventHandler) -> EventHandler:
        dispatcher = EventDispatcher.get_instance()
        dispatcher.subscribe(event_type, func)
        return func
    return decorator
