"""
Repository Pattern Implementation
Provides abstraction layer for data access
"""
from typing import Optional, List, Dict, Any, TypeVar, Generic
from datetime import datetime
from sqlalchemy.orm import Session, Query
from sqlalchemy import and_, or_, func
import uuid

from models.insurance_models import (
    InsuranceEnvelope, PolicyRoot, ActivityClass, SpaceRiskProfile,
    InsurancePricing, IncidentReport, Claim, AccessGrant, AuditLog, User
)
from utils.exceptions import NotFoundError, RepositoryError

T = TypeVar('T')


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations"""
    
    def __init__(self, model: type, db: Session):
        self.model = model
        self.db = db
    
    def get(self, id: str) -> Optional[T]:
        """Get entity by ID"""
        try:
            return self.db.query(self.model).filter(self.model.id == id).first()
        except Exception as e:
            raise RepositoryError(f"Error retrieving {self.model.__name__}: {e}")
    
    def get_or_raise(self, id: str) -> T:
        """Get entity by ID or raise NotFoundError"""
        entity = self.get(id)
        if entity is None:
            raise NotFoundError(f"{self.model.__name__} with id {id} not found")
        return entity
    
    def list(
        self,
        filters: Optional[Dict[str, Any]] = None,
        offset: int = 0,
        limit: int = 100
    ) -> List[T]:
        """List entities with optional filters and pagination"""
        query = self.db.query(self.model)
        
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.filter(getattr(self.model, key) == value)
        
        return query.offset(offset).limit(limit).all()
    
    def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        """Count entities with optional filters"""
        query = self.db.query(func.count(self.model.id))
        
        if filters:
            for key, value in filters.items():
                if hasattr(self.model, key):
                    query = query.filter(getattr(self.model, key) == value)
        
        return query.scalar() or 0
    
    def create(self, data: Dict[str, Any]) -> T:
        """Create new entity"""
        try:
            entity = self.model(**data)
            self.db.add(entity)
            self.db.commit()
            self.db.refresh(entity)
            return entity
        except Exception as e:
            self.db.rollback()
            raise RepositoryError(f"Error creating {self.model.__name__}: {e}")
    
    def update(self, id: str, data: Dict[str, Any]) -> Optional[T]:
        """Update entity"""
        try:
            entity = self.get_or_raise(id)
            for key, value in data.items():
                if hasattr(entity, key):
                    setattr(entity, key, value)
            self.db.commit()
            self.db.refresh(entity)
            return entity
        except Exception as e:
            self.db.rollback()
            raise RepositoryError(f"Error updating {self.model.__name__}: {e}")
    
    def delete(self, id: str) -> bool:
        """Delete entity"""
        try:
            entity = self.get_or_raise(id)
            self.db.delete(entity)
            self.db.commit()
            return True
        except Exception as e:
            self.db.rollback()
            raise RepositoryError(f"Error deleting {self.model.__name__}: {e}")


class PolicyRootRepository(BaseRepository[PolicyRoot]):
    """Repository for PolicyRoot"""
    
    def __init__(self, db: Session):
        super().__init__(PolicyRoot, db)
    
    def get_active_policy(self, policy_number: str) -> Optional[PolicyRoot]:
        """Get active policy by number"""
        return self.db.query(PolicyRoot).filter(
            PolicyRoot.policy_number == policy_number,
            PolicyRoot.status == 'active'
        ).first()
    
    def get_active_policies(self) -> List[PolicyRoot]:
        """Get all active policies"""
        return self.db.query(PolicyRoot).filter(
            PolicyRoot.status == 'active'
        ).all()
    
    def get_policy_for_jurisdiction(
        self,
        jurisdiction: str,
        effective_date: Optional[datetime] = None
    ) -> Optional[PolicyRoot]:
        """Get active policy for jurisdiction at given date"""
        if effective_date is None:
            effective_date = datetime.utcnow()
        
        return self.db.query(PolicyRoot).filter(
            PolicyRoot.jurisdiction == jurisdiction,
            PolicyRoot.status == 'active',
            PolicyRoot.effective_from <= effective_date,
            PolicyRoot.effective_until >= effective_date
        ).first()


class ActivityClassRepository(BaseRepository[ActivityClass]):
    """Repository for ActivityClass"""
    
    def __init__(self, db: Session):
        super().__init__(ActivityClass, db)
    
    def get_by_slug(self, slug: str) -> Optional[ActivityClass]:
        """Get activity class by slug"""
        return self.db.query(ActivityClass).filter(
            ActivityClass.slug == slug
        ).first()
    
    def get_all_slugs(self) -> List[str]:
        """Get all activity class slugs"""
        results = self.db.query(ActivityClass.slug).all()
        return [r[0] for r in results]
    
    def get_classes_allowing_alcohol(self) -> List[ActivityClass]:
        """Get activity classes that allow alcohol"""
        return self.db.query(ActivityClass).filter(
            ActivityClass.allows_alcohol == True
        ).all()
    
    def get_classes_allowing_minors(self) -> List[ActivityClass]:
        """Get activity classes that allow minors"""
        return self.db.query(ActivityClass).filter(
            ActivityClass.allows_minors == True
        ).all()


class SpaceRiskProfileRepository(BaseRepository[SpaceRiskProfile]):
    """Repository for SpaceRiskProfile"""
    
    def __init__(self, db: Session):
        super().__init__(SpaceRiskProfile, db)
    
    def get_by_owner(self, owner_id: str) -> List[SpaceRiskProfile]:
        """Get spaces by owner"""
        return self.db.query(SpaceRiskProfile).filter(
            SpaceRiskProfile.owner_id == owner_id
        ).all()


class InsuranceEnvelopeRepository(BaseRepository[InsuranceEnvelope]):
    """Repository for InsuranceEnvelope"""
    
    def __init__(self, db: Session):
        super().__init__(InsuranceEnvelope, db)
    
    def get_active_envelope(self, envelope_id: str) -> Optional[InsuranceEnvelope]:
        """Get active envelope that is currently valid"""
        now = datetime.utcnow()
        return self.db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.id == envelope_id,
            InsuranceEnvelope.status == 'active',
            InsuranceEnvelope.valid_from <= now,
            InsuranceEnvelope.valid_until >= now
        ).first()
    
    def get_envelopes_for_space(
        self,
        space_id: str,
        status: Optional[str] = None
    ) -> List[InsuranceEnvelope]:
        """Get envelopes for a space"""
        query = self.db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.space_id == space_id
        )
        if status:
            query = query.filter(InsuranceEnvelope.status == status)
        return query.all()
    
    def get_envelopes_for_steward(
        self,
        steward_id: str,
        status: Optional[str] = None
    ) -> List[InsuranceEnvelope]:
        """Get envelopes for a steward"""
        query = self.db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.steward_id == steward_id
        )
        if status:
            query = query.filter(InsuranceEnvelope.status == status)
        return query.all()
    
    def check_overlapping_envelopes(
        self,
        space_id: str,
        valid_from: datetime,
        valid_until: datetime,
        exclude_id: Optional[str] = None
    ) -> List[InsuranceEnvelope]:
        """Check for overlapping envelopes in time for a space"""
        query = self.db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.space_id == space_id,
            InsuranceEnvelope.status.in_(['pending', 'active']),
            InsuranceEnvelope.valid_from < valid_until,
            InsuranceEnvelope.valid_until > valid_from
        )
        
        if exclude_id:
            query = query.filter(InsuranceEnvelope.id != exclude_id)
        
        return query.all()
    
    def get_expiring_envelopes(self, hours: int = 24) -> List[InsuranceEnvelope]:
        """Get envelopes expiring within specified hours"""
        from datetime import timedelta
        now = datetime.utcnow()
        cutoff = now + timedelta(hours=hours)
        
        return self.db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.status == 'active',
            InsuranceEnvelope.valid_until <= cutoff,
            InsuranceEnvelope.valid_until > now
        ).all()
    
    def expire_overdue_envelopes(self) -> int:
        """Mark overdue envelopes as expired"""
        now = datetime.utcnow()
        result = self.db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.status == 'active',
            InsuranceEnvelope.valid_until < now
        ).update(
            {InsuranceEnvelope.status: 'expired'},
            synchronize_session=False
        )
        self.db.commit()
        return result


class AccessGrantRepository(BaseRepository[AccessGrant]):
    """Repository for AccessGrant"""
    
    def __init__(self, db: Session):
        super().__init__(AccessGrant, db)
    
    def get_active_grant(self, grant_id: str) -> Optional[AccessGrant]:
        """Get active access grant"""
        now = datetime.utcnow()
        return self.db.query(AccessGrant).filter(
            AccessGrant.id == grant_id,
            AccessGrant.status == 'active',
            AccessGrant.valid_from <= now,
            AccessGrant.valid_until >= now
        ).first()
    
    def get_grants_for_envelope(
        self,
        envelope_id: str,
        status: Optional[str] = None
    ) -> List[AccessGrant]:
        """Get grants for envelope"""
        query = self.db.query(AccessGrant).filter(
            AccessGrant.envelope_id == envelope_id
        )
        if status:
            query = query.filter(AccessGrant.status == status)
        return query.all()
    
    def get_active_grants_for_envelope(self, envelope_id: str) -> List[AccessGrant]:
        """Get active grants for envelope"""
        return self.db.query(AccessGrant).filter(
            AccessGrant.envelope_id == envelope_id,
            AccessGrant.status == 'active'
        ).all()
    
    def revoke_grants_for_envelope(
        self,
        envelope_id: str,
        reason: str,
        actor_id: Optional[str] = None
    ) -> int:
        """Revoke all active grants for an envelope"""
        from datetime import datetime
        result = self.db.query(AccessGrant).filter(
            AccessGrant.envelope_id == envelope_id,
            AccessGrant.status == 'active'
        ).update(
            {
                AccessGrant.status: 'revoked',
                AccessGrant.revoked_at: datetime.utcnow(),
                AccessGrant.revoke_reason: reason
            },
            synchronize_session=False
        )
        self.db.commit()
        return result
    
    def get_grant_for_update(self, grant_id: str) -> Optional[AccessGrant]:
        """Get grant with row lock for update"""
        return self.db.query(AccessGrant).filter(
            AccessGrant.id == grant_id
        ).with_for_update().first()


class IncidentReportRepository(BaseRepository[IncidentReport]):
    """Repository for IncidentReport"""
    
    def __init__(self, db: Session):
        super().__init__(IncidentReport, db)
    
    def get_incidents_for_envelope(self, envelope_id: str) -> List[IncidentReport]:
        """Get all incidents for an envelope"""
        return self.db.query(IncidentReport).filter(
            IncidentReport.envelope_id == envelope_id
        ).order_by(IncidentReport.occurred_at.desc()).all()
    
    def get_high_severity_incidents(self, days: int = 30) -> List[IncidentReport]:
        """Get high severity incidents in recent days"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        return self.db.query(IncidentReport).filter(
            IncidentReport.severity.in_(['high', 'critical']),
            IncidentReport.occurred_at >= cutoff
        ).order_by(IncidentReport.occurred_at.desc()).all()


class ClaimRepository(BaseRepository[Claim]):
    """Repository for Claim"""
    
    def __init__(self, db: Session):
        super().__init__(Claim, db)
    
    def get_claims_for_envelope(self, envelope_id: str) -> List[Claim]:
        """Get all claims for an envelope"""
        return self.db.query(Claim).filter(
            Claim.envelope_id == envelope_id
        ).order_by(Claim.opened_at.desc()).all()
    
    def get_open_claims_for_envelope(self, envelope_id: str) -> List[Claim]:
        """Get open claims for an envelope"""
        return self.db.query(Claim).filter(
            Claim.envelope_id == envelope_id,
            Claim.status.in_(['opened', 'under_review'])
        ).all()
    
    def get_open_claims(self) -> List[Claim]:
        """Get all open claims"""
        return self.db.query(Claim).filter(
            Claim.status.in_(['opened', 'under_review'])
        ).all()


class AuditLogRepository(BaseRepository[AuditLog]):
    """Repository for AuditLog"""
    
    def __init__(self, db: Session):
        super().__init__(AuditLog, db)
    
    def get_logs_for_entity(
        self,
        entity_type: str,
        entity_id: str,
        limit: int = 100
    ) -> List[AuditLog]:
        """Get audit logs for an entity"""
        return self.db.query(AuditLog).filter(
            AuditLog.entity_type == entity_type,
            AuditLog.entity_id == entity_id
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()
    
    def get_recent_logs(self, hours: int = 24, limit: int = 1000) -> List[AuditLog]:
        """Get recent audit logs"""
        from datetime import timedelta
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        return self.db.query(AuditLog).filter(
            AuditLog.created_at >= cutoff
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()
    
    def get_logs_by_actor(self, actor_id: str, limit: int = 100) -> List[AuditLog]:
        """Get audit logs for an actor"""
        return self.db.query(AuditLog).filter(
            AuditLog.actor_id == actor_id
        ).order_by(AuditLog.created_at.desc()).limit(limit).all()


class UserRepository(BaseRepository[User]):
    """Repository for User"""
    
    def __init__(self, db: Session):
        super().__init__(User, db)
    
    def get_by_username(self, username: str) -> Optional[User]:
        """Get user by username"""
        return self.db.query(User).filter(
            User.username == username,
            User.disabled == False
        ).first()
    
    def get_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        return self.db.query(User).filter(
            User.email == email,
            User.disabled == False
        ).first()
    
    def get_users_by_role(self, role: str) -> List[User]:
        """Get users by role"""
        return self.db.query(User).filter(
            User.role == role
        ).all()


class RepositoryFactory:
    """Factory for creating repositories"""
    
    def __init__(self, db: Session):
        self.db = db
        self._cache: Dict[str, Any] = {}
    
    @property
    def policies(self) -> PolicyRootRepository:
        if 'policies' not in self._cache:
            self._cache['policies'] = PolicyRootRepository(self.db)
        return self._cache['policies']
    
    @property
    def activity_classes(self) -> ActivityClassRepository:
        if 'activity_classes' not in self._cache:
            self._cache['activity_classes'] = ActivityClassRepository(self.db)
        return self._cache['activity_classes']
    
    @property
    def spaces(self) -> SpaceRiskProfileRepository:
        if 'spaces' not in self._cache:
            self._cache['spaces'] = SpaceRiskProfileRepository(self.db)
        return self._cache['spaces']
    
    @property
    def envelopes(self) -> InsuranceEnvelopeRepository:
        if 'envelopes' not in self._cache:
            self._cache['envelopes'] = InsuranceEnvelopeRepository(self.db)
        return self._cache['envelopes']
    
    @property
    def access_grants(self) -> AccessGrantRepository:
        if 'access_grants' not in self._cache:
            self._cache['access_grants'] = AccessGrantRepository(self.db)
        return self._cache['access_grants']
    
    @property
    def incidents(self) -> IncidentReportRepository:
        if 'incidents' not in self._cache:
            self._cache['incidents'] = IncidentReportRepository(self.db)
        return self._cache['incidents']
    
    @property
    def claims(self) -> ClaimRepository:
        if 'claims' not in self._cache:
            self._cache['claims'] = ClaimRepository(self.db)
        return self._cache['claims']
    
    @property
    def audit_logs(self) -> AuditLogRepository:
        if 'audit_logs' not in self._cache:
            self._cache['audit_logs'] = AuditLogRepository(self.db)
        return self._cache['audit_logs']
    
    @property
    def users(self) -> UserRepository:
        if 'users' not in self._cache:
            self._cache['users'] = UserRepository(self.db)
        return self._cache['users']
