from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from models.insurance_models import AccessGrant, InsuranceEnvelope
from services.lock_integration import AccessGrantService
from utils.exceptions import AccessDeniedError


class AccessControlService:
    """
    Service for enforcing access control based on insurance envelopes
    """
    
    def __init__(self, access_grant_service: AccessGrantService):
        self.access_grant_service = access_grant_service
    
    def enforce_access_control(self, db: Session, grant_id: str) -> Dict[str, Any]:
        """
        Main access control enforcement function
        """
        # Get the access grant
        grant = db.query(AccessGrant).filter(
            AccessGrant.id == grant_id
        ).first()
        
        if not grant:
            return {
                "allowed": False,
                "reason": "Invalid grant ID",
                "enforcement_action": "deny_access"
            }
        
        # Check if the grant is active
        if grant.status != 'active':
            return {
                "allowed": False,
                "reason": f"Grant status is {grant.status}",
                "enforcement_action": "deny_access"
            }
        
        # Check time validity
        from datetime import timezone
        now = datetime.now(timezone.utc)
        if not (grant.valid_from <= now <= grant.valid_until):
            return {
                "allowed": False,
                "reason": "Grant is not valid at this time",
                "enforcement_action": "deny_access"
            }
        
        # Check if the associated envelope is still active
        envelope = db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.id == grant.envelope_id,
            InsuranceEnvelope.status == 'active'
        ).first()
        
        if not envelope:
            # The envelope has been voided, so revoke this grant too
            self._handle_voided_envelope(db, grant)
            return {
                "allowed": False,
                "reason": "Associated insurance envelope is no longer valid",
                "enforcement_action": "revoke_and_deny_access"
            }
        
        # Check attendance capacity atomically using SELECT FOR UPDATE
        from sqlalchemy import text
        # Lock the grant row to prevent concurrent updates
        locked_grant = db.query(AccessGrant).filter(
            AccessGrant.id == grant.id
        ).with_for_update().first()

        if locked_grant.checkins_used >= locked_grant.attendance_cap:
            # Capacity exceeded - void the envelope and revoke access
            self._handle_capacity_exceeded(db, locked_grant, envelope)
            return {
                "allowed": False,
                "reason": "Attendance capacity exceeded",
                "enforcement_action": "void_envelope_revoke_and_deny_access"
            }
        
        # All checks passed
        return {
            "allowed": True,
            "reason": "Access granted",
            "enforcement_action": "allow_access",
            "remaining_capacity": grant.attendance_cap - grant.checkins_used
        }
    
    def _handle_voided_envelope(self, db: Session, grant: AccessGrant) -> None:
        """
        Handle the case where the associated envelope has been voided
        """
        grant.status = 'revoked'
        db.commit()
        
        # Revoke access through the lock system
        lock_vendor = self._extract_vendor_from_lock_id(grant.lock_id)
        adapter = self.access_grant_service.adapters.get(lock_vendor)
        if adapter:
            # In async context, this would be awaited
            # await adapter.revoke_access(str(grant.id))
            pass
    
    def _handle_capacity_exceeded(
        self, 
        db: Session, 
        grant: AccessGrant, 
        envelope: InsuranceEnvelope
    ) -> None:
        """
        Handle the case where attendance capacity is exceeded
        """
        # Void the envelope
        from services.insurance_envelope_service import InsuranceEnvelopeService
        InsuranceEnvelopeService.deactivate_envelope(
            db, 
            str(envelope.id), 
            "attendance_cap_exceeded"
        )
        
        # Revoke the access grant
        grant.status = 'revoked'
        db.commit()
        
        # Revoke access through the lock system
        lock_vendor = self._extract_vendor_from_lock_id(grant.lock_id)
        adapter = self.access_grant_service.adapters.get(lock_vendor)
        if adapter:
            # In async context, this would be awaited
            # await adapter.revoke_access(str(grant.id))
            pass
    
    def _extract_vendor_from_lock_id(self, lock_id: str) -> str:
        """
        Extract vendor from lock ID (assuming format: vendor:lock_id)
        """
        if ':' in lock_id:
            return lock_id.split(':')[0]
        return 'generic'


class EnforcementHooks:
    """
    Hooks for real-time enforcement based on envelope state changes
    """
    
    @staticmethod
    def on_envelope_status_change(
        db: Session,
        envelope_id: str,
        old_status: str,
        new_status: str,
        access_grant_service: AccessGrantService
    ) -> None:
        """
        Handle actions when an envelope status changes
        """
        if new_status in ['voided', 'expired', 'claim_open']:
            # Find all access grants associated with this envelope
            from models.insurance_models import AccessGrant
            grants = db.query(AccessGrant).filter(
                AccessGrant.envelope_id == envelope_id,
                AccessGrant.status == 'active'
            ).all()
            
            for grant in grants:
                # Revoke the access grant
                grant.status = 'revoked'
                
                # Revoke access through the lock system
                lock_vendor = EnforcementHooks._extract_vendor_from_lock_id(grant.lock_id)
                adapter = access_grant_service.adapters.get(lock_vendor)
                if adapter:
                    # In async context, this would be awaited
                    # await adapter.revoke_access(str(grant.id))
                    pass
            
            db.commit()
    
    @staticmethod
    def _extract_vendor_from_lock_id(lock_id: str) -> str:
        """
        Extract vendor from lock ID (assuming format: vendor:lock_id)
        """
        if ':' in lock_id:
            return lock_id.split(':')[0]
        return 'generic'


class CapacityEnforcementService:
    """
    Service for enforcing attendance capacity limits
    """
    
    @staticmethod
    def increment_attendance(db: Session, grant_id: str) -> Dict[str, Any]:
        """
        Increment the attendance counter for a grant
        """
        from models.insurance_models import AccessGrant
        # Use SELECT FOR UPDATE to prevent race conditions
        grant = db.query(AccessGrant).filter(
            AccessGrant.id == grant_id
        ).with_for_update().first()

        if not grant:
            raise AccessDeniedError(f"Access grant {grant_id} not found")

        if grant.checkins_used >= grant.attendance_cap:
            raise AccessDeniedError("Attendance capacity already reached")

        # Increment the counter
        grant.checkins_used += 1
        db.commit()

        remaining_capacity = grant.attendance_cap - grant.checkins_used

        # Check if we're at capacity now
        if remaining_capacity == 0:
            # Trigger capacity exceeded handling
            from services.insurance_envelope_service import InsuranceEnvelopeService
            envelope = db.query(InsuranceEnvelope).filter(
                InsuranceEnvelope.id == grant.envelope_id
            ).first()

            if envelope:
                InsuranceEnvelopeService.deactivate_envelope(
                    db,
                    grant.envelope_id,
                    "attendance_cap_reached"
                )

        return {
            "success": True,
            "remaining_capacity": remaining_capacity,
            "current_attendance": grant.checkins_used
        }
    
    @staticmethod
    def get_attendance_status(db: Session, grant_id: str) -> Dict[str, Any]:
        """
        Get the current attendance status for a grant
        """
        from models.insurance_models import AccessGrant
        grant = db.query(AccessGrant).filter(
            AccessGrant.id == grant_id
        ).first()
        
        if not grant:
            raise ValueError(f"Access grant {grant_id} not found")
        
        return {
            "current_attendance": grant.checkins_used,
            "max_capacity": grant.attendance_cap,
            "remaining_capacity": grant.attendance_cap - grant.checkins_used,
            "at_capacity": grant.checkins_used >= grant.attendance_cap
        }


class EmergencyRevocationService:
    """
    Service for emergency revocation of all access grants
    """
    
    @staticmethod
    def revoke_all_active_grants(db: Session) -> int:
        """
        Revoke all active grants system-wide
        This is the safety kill switch mentioned in the requirements
        """
        from models.insurance_models import AccessGrant
        from models.insurance_models import InsuranceEnvelope
        
        # Get all active grants
        active_grants = db.query(AccessGrant).filter(
            AccessGrant.status == 'active'
        ).all()
        
        revoked_count = 0
        
        for grant in active_grants:
            # Update grant status
            grant.status = 'revoked'
            
            # Also void the associated envelope for safety
            envelope = db.query(InsuranceEnvelope).filter(
                InsuranceEnvelope.id == grant.envelope_id
            ).first()
            
            if envelope and envelope.status == 'active':
                envelope.status = 'voided'
        
        db.commit()
        
        # Revoke access through all lock systems
        # This would be done asynchronously in a real implementation
        # for grant in active_grants:
        #     lock_vendor = _extract_vendor_from_lock_id(grant.lock_id)
        #     adapter = access_grant_service.adapters.get(lock_vendor)
        #     if adapter:
        #         await adapter.revoke_access(str(grant.id))
        
        return len(active_grants)