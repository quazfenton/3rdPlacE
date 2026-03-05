from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
import json
import logging

from models.insurance_models import AuditLog
from utils.exceptions import ValidationError

logger = logging.getLogger(__name__)


class AuditService:
    """
    Service for logging and retrieving audit events
    
    Improvements:
    - UUID-based IDs
    - JSONB metadata storage
    - IP address and user agent tracking
    - Comprehensive query methods
    """

    @staticmethod
    def log_event(
        db: Session,
        event_type: str,
        entity_type: str,
        entity_id: str,
        action: str,
        actor_id: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """
        Log an audit event
        """
        if not event_type or not event_type.strip():
            raise ValidationError("event_type cannot be empty")
        if not entity_type or not entity_type.strip():
            raise ValidationError("entity_type cannot be empty")
        if not action or not action.strip():
            raise ValidationError("action cannot be empty")

        audit_log = AuditLog(
            event_type=event_type.strip(),
            entity_type=entity_type.strip(),
            entity_id=entity_id,
            actor_id=actor_id,
            action=action.strip(),
            reason=reason,
            metadata=metadata or {},
            ip_address=ip_address,
            user_agent=user_agent
        )

        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        logger.debug(f"Audit log created: {event_type} - {entity_type}:{entity_id}")

        return audit_log

    @staticmethod
    def log_envelope_voided(
        db: Session,
        envelope_id: str,
        reason: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Log when an insurance envelope is voided
        """
        return AuditService.log_event(
            db=db,
            event_type="envelope_voided",
            entity_type="envelope",
            entity_id=envelope_id,
            action="void",
            actor_id=actor_id,
            reason=reason,
            metadata={"reason": reason},
            ip_address=ip_address
        )

    @staticmethod
    def log_access_revoked(
        db: Session,
        grant_id: str,
        reason: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Log when access is revoked
        """
        return AuditService.log_event(
            db=db,
            event_type="access_revoked",
            entity_type="access_grant",
            entity_id=grant_id,
            action="revoke",
            actor_id=actor_id,
            reason=reason,
            metadata={"reason": reason},
            ip_address=ip_address
        )

    @staticmethod
    def log_claim_processed(
        db: Session,
        claim_id: str,
        decision: str,
        payout_amount: Optional[float] = None,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Log when a claim is processed
        """
        return AuditService.log_event(
            db=db,
            event_type="claim_processed",
            entity_type="claim",
            entity_id=claim_id,
            action=decision,
            actor_id=actor_id,
            metadata={"payout_amount": payout_amount, "decision": decision},
            ip_address=ip_address
        )

    @staticmethod
    def log_incident_reported(
        db: Session,
        incident_id: str,
        incident_type: str,
        severity: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Log when an incident is reported
        """
        return AuditService.log_event(
            db=db,
            event_type="incident_reported",
            entity_type="incident",
            entity_id=incident_id,
            action="report",
            actor_id=actor_id,
            metadata={"incident_type": incident_type, "severity": severity},
            ip_address=ip_address
        )

    @staticmethod
    def log_access_grant_created(
        db: Session,
        grant_id: str,
        envelope_id: str,
        lock_id: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Log when an access grant is created
        """
        return AuditService.log_event(
            db=db,
            event_type="access_grant_created",
            entity_type="access_grant",
            entity_id=grant_id,
            action="create",
            actor_id=actor_id,
            metadata={"envelope_id": envelope_id, "lock_id": lock_id},
            ip_address=ip_address
        )

    @staticmethod
    def log_envelope_created(
        db: Session,
        envelope_id: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Log when an insurance envelope is created
        """
        return AuditService.log_event(
            db=db,
            event_type="envelope_created",
            entity_type="envelope",
            entity_id=envelope_id,
            action="create",
            actor_id=actor_id,
            ip_address=ip_address
        )

    @staticmethod
    def log_envelope_activated(
        db: Session,
        envelope_id: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Log when an insurance envelope is activated
        """
        return AuditService.log_event(
            db=db,
            event_type="envelope_activated",
            entity_type="envelope",
            entity_id=envelope_id,
            action="activate",
            actor_id=actor_id,
            ip_address=ip_address
        )

    @staticmethod
    def log_user_login(
        db: Session,
        user_id: str,
        username: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> AuditLog:
        """
        Log when a user logs in
        """
        return AuditService.log_event(
            db=db,
            event_type="user_login",
            entity_type="user",
            entity_id=user_id,
            action="login",
            actor_id=actor_id or user_id,
            metadata={"username": username},
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def log_user_created(
        db: Session,
        user_id: str,
        username: str,
        role: str,
        actor_id: Optional[str] = None,
        ip_address: Optional[str] = None
    ) -> AuditLog:
        """
        Log when a user is created
        """
        return AuditService.log_event(
            db=db,
            event_type="user_created",
            entity_type="user",
            entity_id=user_id,
            action="create",
            actor_id=actor_id,
            metadata={"username": username, "role": role},
            ip_address=ip_address
        )

    @staticmethod
    def get_audit_logs_for_entity(
        db: Session,
        entity_type: str,
        entity_id: str,
        limit: int = 100
    ) -> List[AuditLog]:
        """
        Get audit logs for a specific entity
        """
        return db.query(AuditLog).filter(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_recent_audit_logs(
        db: Session,
        hours: int = 24,
        limit: int = 1000
    ) -> List[AuditLog]:
        """
        Get recent audit logs within a specified time period
        """
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        return db.query(AuditLog).filter(
            AuditLog.created_at >= cutoff
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_audit_logs_by_event_type(
        db: Session,
        event_type: str,
        limit: int = 100
    ) -> List[AuditLog]:
        """
        Get audit logs for a specific event type
        """
        return db.query(AuditLog).filter(
            AuditLog.event_type == event_type
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_audit_logs_by_actor(
        db: Session,
        actor_id: str,
        limit: int = 100
    ) -> List[AuditLog]:
        """
        Get audit logs for a specific actor
        """
        return db.query(AuditLog).filter(
            AuditLog.actor_id == actor_id
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()

    @staticmethod
    def get_audit_logs_summary(
        db: Session,
        hours: int = 24
    ) -> Dict[str, Any]:
        """
        Get summary statistics for audit logs
        """
        from datetime import timedelta
        from sqlalchemy import func

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        # Total events
        total = db.query(func.count(AuditLog.id)).filter(
            AuditLog.created_at >= cutoff
        ).scalar() or 0

        # Events by type
        by_type = db.query(
            AuditLog.event_type,
            func.count(AuditLog.id)
        ).filter(
            AuditLog.created_at >= cutoff
        ).group_by(AuditLog.event_type).all()

        # Events by actor
        by_actor = db.query(
            AuditLog.actor_id,
            func.count(AuditLog.id)
        ).filter(
            AuditLog.created_at >= cutoff,
            AuditLog.actor_id.isnot(None)
        ).group_by(AuditLog.actor_id).all()

        return {
            "total_events": total,
            "events_by_type": {event_type: count for event_type, count in by_type},
            "events_by_actor": {actor_id: count for actor_id, count in by_actor},
            "time_period_hours": hours
        }

    @staticmethod
    def search_audit_logs(
        db: Session,
        event_type: Optional[str] = None,
        entity_type: Optional[str] = None,
        actor_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[AuditLog]:
        """
        Search audit logs with multiple filters
        """
        query = db.query(AuditLog)

        if event_type:
            query = query.filter(AuditLog.event_type == event_type)
        if entity_type:
            query = query.filter(AuditLog.entity_type == entity_type)
        if actor_id:
            query = query.filter(AuditLog.actor_id == actor_id)
        if start_date:
            query = query.filter(AuditLog.created_at >= start_date)
        if end_date:
            query = query.filter(AuditLog.created_at <= end_date)

        return query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()
