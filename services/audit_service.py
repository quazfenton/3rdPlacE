from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from config.database import Base


class AuditLog(Base):
    """
    Audit log model for tracking important system events
    """
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=lambda: datetime.utcnow().isoformat())
    event_type = Column(String, nullable=False)  # envelope_voided, access_revoked, claim_processed, etc.
    entity_type = Column(String, nullable=False)  # envelope, access_grant, claim, incident
    entity_id = Column(String, nullable=False)
    actor_id = Column(String)  # Who performed the action
    action = Column(String, nullable=False)
    reason = Column(Text)
    metadata = Column(String)  # JSON string for additional context
    created_at = Column(DateTime(timezone=True), server_default=datetime.utcnow())


class AuditService:
    """
    Service for logging and retrieving audit events
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLog:
        """
        Log an audit event
        """
        import json

        audit_log = AuditLog(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_id=actor_id,
            action=action,
            reason=reason,
            metadata=json.dumps(metadata) if metadata else None
        )

        db.add(audit_log)
        db.commit()
        db.refresh(audit_log)

        return audit_log

    @staticmethod
    def log_envelope_voided(
        db: Session,
        envelope_id: str,
        reason: str,
        actor_id: Optional[str] = None
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
            reason=reason
        )

    @staticmethod
    def log_access_revoked(
        db: Session,
        grant_id: str,
        reason: str,
        actor_id: Optional[str] = None
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
            reason=reason
        )

    @staticmethod
    def log_claim_processed(
        db: Session,
        claim_id: str,
        decision: str,
        payout_amount: Optional[float] = None,
        actor_id: Optional[str] = None
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
            metadata={"payout_amount": payout_amount}
        )

    @staticmethod
    def log_incident_reported(
        db: Session,
        incident_id: str,
        incident_type: str,
        severity: str,
        actor_id: Optional[str] = None
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
            metadata={"incident_type": incident_type, "severity": severity}
        )

    @staticmethod
    def log_access_grant_created(
        db: Session,
        grant_id: str,
        envelope_id: str,
        lock_id: str,
        actor_id: Optional[str] = None
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
            metadata={"envelope_id": envelope_id, "lock_id": lock_id}
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

        cutoff = datetime.utcnow() - timedelta(hours=hours)

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
