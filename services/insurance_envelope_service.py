from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from models.insurance_models import InsuranceEnvelope, PolicyRoot, ActivityClass, SpaceRiskProfile
from utils.exceptions import InsuranceValidationError, CoverageError


class InsuranceEnvelopeService:
    """Service class for managing Insurance Envelope lifecycle"""
    
    @staticmethod
    def create_envelope(
        db: Session,
        policy_root_id: str,
        activity_class_id: str,
        space_id: str,
        steward_id: str,
        platform_entity_id: str,
        attendance_cap: int,
        duration_minutes: int,
        valid_from: datetime,
        valid_until: datetime,
        event_metadata: Optional[Dict[str, Any]] = None,
        alcohol: bool = False,
        minors_present: bool = False,
        jurisdiction: Optional[str] = None
    ) -> InsuranceEnvelope:
        """
        Create a new insurance envelope with validation
        """
        # Validate the inputs
        InsuranceEnvelopeService._validate_envelope_inputs(
            policy_root_id, activity_class_id, space_id, 
            attendance_cap, duration_minutes, valid_from, valid_until
        )
        
        # Check if policy root exists and is active
        policy_root = db.query(PolicyRoot).filter(
            PolicyRoot.id == policy_root_id,
            PolicyRoot.status == 'active'
        ).first()
        if not policy_root:
            raise InsuranceValidationError(f"Policy root {policy_root_id} not found or inactive")
        
        # Check if activity class exists
        activity_class = db.query(ActivityClass).filter(
            ActivityClass.id == activity_class_id
        ).first()
        if not activity_class:
            raise InsuranceValidationError(f"Activity class {activity_class_id} not found")
        
        # Check if space risk profile exists
        space_profile = db.query(SpaceRiskProfile).filter(
            SpaceRiskProfile.space_id == space_id
        ).first()
        if not space_profile:
            raise InsuranceValidationError(f"Space risk profile {space_id} not found")
        
        # Validate activity compliance with class restrictions
        InsuranceEnvelopeService._validate_activity_compliance(
            activity_class, alcohol, minors_present
        )
        
        # Create the envelope
        envelope = InsuranceEnvelope(
            policy_root_id=policy_root_id,
            activity_class_id=activity_class_id,
            space_id=space_id,
            steward_id=steward_id,
            platform_entity_id=platform_entity_id,
            event_metadata=event_metadata or {},
            attendance_cap=attendance_cap,
            duration_minutes=duration_minutes,
            alcohol=alcohol,
            minors_present=minors_present,
            jurisdiction=jurisdiction or policy_root.jurisdiction,
            valid_from=valid_from,
            valid_until=valid_until,
            status='pending'  # Will be activated after additional checks
        )
        
        try:
            db.add(envelope)
            db.commit()
            db.refresh(envelope)
            
            # Now activate the envelope after creation
            envelope = InsuranceEnvelopeService.activate_envelope(db, envelope.id)
            
            return envelope
        except IntegrityError:
            db.rollback()
            raise InsuranceValidationError("Failed to create insurance envelope due to constraint violation")
    
    @staticmethod
    def activate_envelope(db: Session, envelope_id: str) -> InsuranceEnvelope:
        """
        Activate an insurance envelope after validation
        """
        envelope = db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.id == envelope_id
        ).first()
        
        if not envelope:
            raise CoverageError(f"Insurance envelope {envelope_id} not found")
        
        if envelope.status != 'pending':
            raise CoverageError(f"Cannot activate envelope with status: {envelope.status}")
        
        # Perform additional validations before activation
        if not InsuranceEnvelopeService._is_valid_for_activation(envelope):
            raise CoverageError("Envelope failed activation validation")
        
        # Generate certificate URL
        envelope.certificate_url = f"https://certs.thirdplace.com/{envelope.id}.pdf"
        envelope.status = 'active'
        
        db.commit()
        db.refresh(envelope)
        
        return envelope
    
    @staticmethod
    def deactivate_envelope(db: Session, envelope_id: str, reason: str) -> InsuranceEnvelope:
        """
        Deactivate/void an insurance envelope
        """
        envelope = db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.id == envelope_id
        ).first()
        
        if not envelope:
            raise CoverageError(f"Insurance envelope {envelope_id} not found")
        
        if envelope.status in ['expired', 'voided']:
            return envelope  # Already deactivated
        
        envelope.status = 'voided'
        
        db.commit()
        db.refresh(envelope)
        
        # Log the deactivation reason
        from services.audit_service import AuditService
        AuditService.log_envelope_voided(db, envelope_id, reason)
        
        return envelope
    
    @staticmethod
    def get_active_envelope(db: Session, envelope_id: str) -> Optional[InsuranceEnvelope]:
        """
        Retrieve an active insurance envelope
        """
        return db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.id == envelope_id,
            InsuranceEnvelope.status == 'active',
            InsuranceEnvelope.valid_from <= datetime.utcnow(),
            InsuranceEnvelope.valid_until >= datetime.utcnow()
        ).first()
    
    @staticmethod
    def is_envelope_valid(envelope: InsuranceEnvelope) -> bool:
        """
        Check if an envelope is currently valid
        """
        now = datetime.utcnow()
        return (
            envelope.status == 'active' and
            envelope.valid_from <= now <= envelope.valid_until
        )
    
    @staticmethod
    def _validate_envelope_inputs(
        policy_root_id: str,
        activity_class_id: str,
        space_id: str,
        attendance_cap: int,
        duration_minutes: int,
        valid_from: datetime,
        valid_until: datetime
    ) -> None:
        """
        Validate envelope creation inputs
        """
        if attendance_cap <= 0:
            raise InsuranceValidationError("Attendance cap must be greater than 0")
        
        if duration_minutes <= 0:
            raise InsuranceValidationError("Duration must be greater than 0 minutes")
        
        if valid_from >= valid_until:
            raise InsuranceValidationError("Valid from must be before valid until")
        
        if valid_from < datetime.utcnow():
            raise InsuranceValidationError("Valid from cannot be in the past")
        
        # Check max duration (e.g., 12 hours)
        max_duration = timedelta(hours=12)
        if valid_until - valid_from > max_duration:
            raise InsuranceValidationError(f"Maximum duration is {max_duration}")
    
    @staticmethod
    def _validate_activity_compliance(
        activity_class: ActivityClass,
        alcohol: bool,
        minors_present: bool
    ) -> None:
        """
        Validate that the activity complies with class restrictions
        """
        if alcohol and not activity_class.allows_alcohol:
            raise InsuranceValidationError(
                f"Activity class {activity_class.slug} does not allow alcohol"
            )
        
        if minors_present and not activity_class.allows_minors:
            raise InsuranceValidationError(
                f"Activity class {activity_class.slug} does not allow minors"
            )
    
    @staticmethod
    def _is_valid_for_activation(envelope: InsuranceEnvelope) -> bool:
        """
        Perform additional validation checks before activation
        """
        # Check if the associated policy is still active
        policy = envelope.policy_root
        if not policy or policy.status != 'active':
            return False

        # Check if the activity class is valid
        activity_class = envelope.activity_class
        if not activity_class:
            return False

        # Check if the space profile is valid
        space_profile = envelope.space_profile
        if not space_profile:
            return False

        # Check time validity - allow activation if valid_from is in future or currently valid
        # Convert naive datetimes to timezone-aware if needed
        from datetime import timezone
        now = datetime.now(timezone.utc)
        
        # Make sure envelope datetimes are timezone-aware
        valid_from = envelope.valid_from
        valid_until = envelope.valid_until
        
        if valid_from.tzinfo is None:
            # Assume UTC for naive datetimes
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
            
        if valid_from <= valid_until and now <= valid_until:
            return True

        return False
    
    @staticmethod
    def check_attendance_capacity(db: Session, envelope_id: str) -> Dict[str, Any]:
        """
        Check the attendance capacity status for an envelope
        """
        envelope = db.query(InsuranceEnvelope).filter(
            InsuranceEnvelope.id == envelope_id
        ).first()
        
        if not envelope:
            raise CoverageError(f"Insurance envelope {envelope_id} not found")
        
        # Get the associated access grant to check current attendance
        from models.insurance_models import AccessGrant
        active_grant = db.query(AccessGrant).filter(
            AccessGrant.envelope_id == envelope_id,
            AccessGrant.status == 'active'
        ).first()
        
        if not active_grant:
            return {
                "capacity_available": True,
                "current_attendance": 0,
                "max_capacity": envelope.attendance_cap,
                "remaining_capacity": envelope.attendance_cap
            }
        
        return {
            "capacity_available": active_grant.checkins_used < envelope.attendance_cap,
            "current_attendance": active_grant.checkins_used,
            "max_capacity": envelope.attendance_cap,
            "remaining_capacity": envelope.attendance_cap - active_grant.checkins_used
        }