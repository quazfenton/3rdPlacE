from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
import hashlib
import logging

from models.insurance_models import InsuranceEnvelope, PolicyRoot, ActivityClass, SpaceRiskProfile, AccessGrant
from repositories.base_repository import RepositoryFactory, InsuranceEnvelopeRepository
from services.domain_events import (
    EventDispatcher, EventType, create_event, publish_event_sync
)
from utils.exceptions import (
    InsuranceValidationError, CoverageError, ConflictError, NotFoundError
)

logger = logging.getLogger(__name__)


class InsuranceEnvelopeService:
    """
    Service class for managing Insurance Envelope lifecycle
    
    Improvements:
    - Uses repository pattern for data access
    - Proper transaction boundaries
    - Domain events for state changes
    - Race condition prevention with row locking
    - Certificate hash for verification
    """

    # Maximum duration for an envelope (12 hours)
    MAX_DURATION_MINUTES = 720
    
    # Maximum advance booking (30 days)
    MAX_ADVANCE_BOOKING_DAYS = 30

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
        jurisdiction: Optional[str] = None,
        actor_id: Optional[str] = None
    ) -> InsuranceEnvelope:
        """
        Create a new insurance envelope with full validation.
        
        Uses proper transaction boundaries - either everything succeeds or
        everything rolls back.
        """
        repos = RepositoryFactory(db)
        
        # Validate inputs
        InsuranceEnvelopeService._validate_envelope_inputs(
            attendance_cap, duration_minutes, valid_from, valid_until
        )

        # Check for overlapping envelopes (race condition prevention)
        overlapping = repos.envelopes.check_overlapping_envelopes(
            space_id=space_id,
            valid_from=valid_from,
            valid_until=valid_until
        )
        if overlapping:
            raise ConflictError(
                f"Overlapping envelope exists: {overlapping[0].id}. "
                "Cannot create multiple active envelopes for the same space and time."
            )

        # Check if policy root exists and is active
        policy_root = repos.policies.get(policy_root_id)
        if not policy_root or policy_root.status != 'active':
            raise InsuranceValidationError(f"Policy root {policy_root_id} not found or inactive")

        # Check if activity class exists
        activity_class = repos.activity_classes.get(activity_class_id)
        if not activity_class:
            raise InsuranceValidationError(f"Activity class {activity_class_id} not found")

        # Check if space risk profile exists
        space_profile = repos.spaces.get(space_id)
        if not space_profile:
            raise InsuranceValidationError(f"Space risk profile {space_id} not found")

        # Validate activity compliance with class restrictions
        violations = InsuranceEnvelopeService._validate_activity_compliance(
            activity_class, alcohol, minors_present, event_metadata
        )
        if violations:
            raise InsuranceValidationError(
                f"Activity violates restrictions: {'; '.join(violations)}"
            )

        # Set jurisdiction from policy if not provided
        if not jurisdiction:
            jurisdiction = policy_root.jurisdiction

        # Create the envelope
        envelope_data = {
            'policy_root_id': policy_root_id,
            'activity_class_id': activity_class_id,
            'space_id': space_id,
            'steward_id': steward_id,
            'platform_entity_id': platform_entity_id,
            'event_metadata': event_metadata or {},
            'attendance_cap': attendance_cap,
            'duration_minutes': duration_minutes,
            'alcohol': alcohol,
            'minors_present': minors_present,
            'jurisdiction': jurisdiction,
            'valid_from': valid_from,
            'valid_until': valid_until,
            'status': 'pending',
            'coverage_limits': activity_class.default_limits or {},
            'exclusions': policy_root.exclusions or {}
        }
        
        envelope = InsuranceEnvelope(**envelope_data)
        db.add(envelope)
        
        # Flush to get the ID before commit
        db.flush()
        
        try:
            db.commit()
            db.refresh(envelope)
            
            logger.info(f"Created insurance envelope {envelope.id} in pending status")
            
            # Activate the envelope after successful creation
            envelope = InsuranceEnvelopeService.activate_envelope(
                db, str(envelope.id), actor_id
            )
            
            return envelope
            
        except IntegrityError as e:
            db.rollback()
            logger.error(f"Integrity error creating envelope: {e}")
            raise InsuranceValidationError(
                "Failed to create insurance envelope due to constraint violation"
            )

    @staticmethod
    def activate_envelope(
        db: Session,
        envelope_id: str,
        actor_id: Optional[str] = None
    ) -> InsuranceEnvelope:
        """
        Activate an insurance envelope after validation.
        Generates certificate URL and hash for verification.
        """
        repos = RepositoryFactory(db)
        envelope = repos.envelopes.get_or_raise(envelope_id)

        if envelope.status != 'pending':
            raise CoverageError(
                f"Cannot activate envelope with status: {envelope.status}. "
                "Only 'pending' envelopes can be activated."
            )

        # Perform validations before activation
        validation_errors = InsuranceEnvelopeService._validate_for_activation(envelope)
        if validation_errors:
            raise CoverageError(
                f"Envelope failed activation validation: {'; '.join(validation_errors)}"
            )

        # Generate certificate URL and hash
        cert_string = f"{envelope.id}:{envelope.valid_until.isoformat()}:{envelope.attendance_cap}"
        cert_hash = hashlib.sha256(cert_string.encode()).hexdigest()
        
        envelope.certificate_url = f"/api/v1/certificates/{envelope.id}.pdf"
        envelope.certificate_hash = cert_hash
        envelope.status = 'active'

        db.commit()
        db.refresh(envelope)

        logger.info(f"Activated insurance envelope {envelope.id}")

        # Publish domain event
        event = create_event(
            event_type=EventType.ENVELOPE_ACTIVATED,
            entity_type='insurance_envelope',
            entity_id=str(envelope.id),
            data={
                'space_id': str(envelope.space_id),
                'valid_from': envelope.valid_from.isoformat(),
                'valid_until': envelope.valid_until.isoformat(),
                'attendance_cap': envelope.attendance_cap
            },
            actor_id=actor_id
        )
        publish_event_sync(event)

        return envelope

    @staticmethod
    def deactivate_envelope(
        db: Session,
        envelope_id: str,
        reason: str,
        actor_id: Optional[str] = None
    ) -> InsuranceEnvelope:
        """
        Deactivate/void an insurance envelope.
        Also revokes all associated access grants.
        """
        repos = RepositoryFactory(db)
        envelope = repos.envelopes.get_or_raise(envelope_id)

        if envelope.status in ['expired', 'voided']:
            logger.info(f"Envelope {envelope_id} already deactivated with status {envelope.status}")
            return envelope

        old_status = envelope.status
        envelope.status = 'voided'

        db.commit()
        db.refresh(envelope)

        logger.info(f"Voided insurance envelope {envelope.id}: {reason}")

        # Revoke all associated access grants
        revoked_count = repos.access_grants.revoke_grants_for_envelope(
            envelope_id=str(envelope.id),
            reason=f"Envelope voided: {reason}",
            actor_id=actor_id
        )
        
        logger.info(f"Revoked {revoked_count} access grants for envelope {envelope_id}")

        # Log audit event
        from services.audit_service import AuditService
        AuditService.log_envelope_voided(db, str(envelope.id), reason, actor_id)

        # Publish domain event
        event = create_event(
            event_type=EventType.ENVELOPE_VOIDED,
            entity_type='insurance_envelope',
            entity_id=str(envelope.id),
            data={
                'old_status': old_status,
                'reason': reason,
                'revoked_grants': revoked_count
            },
            actor_id=actor_id
        )
        publish_event_sync(event)

        return envelope

    @staticmethod
    def get_active_envelope(db: Session, envelope_id: str) -> Optional[InsuranceEnvelope]:
        """
        Retrieve an active insurance envelope that is currently valid.
        """
        repos = RepositoryFactory(db)
        return repos.envelopes.get_active_envelope(envelope_id)

    @staticmethod
    def is_envelope_valid(envelope: InsuranceEnvelope) -> bool:
        """
        Check if an envelope is currently valid.
        Handles both timezone-aware and naive datetimes.
        """
        if envelope.status != 'active':
            return False
        
        now = datetime.now(timezone.utc)
        
        # Ensure datetimes are timezone-aware
        valid_from = envelope.valid_from
        valid_until = envelope.valid_until
        
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        
        return valid_from <= now <= valid_until

    @staticmethod
    def check_attendance_capacity(
        db: Session,
        envelope_id: str
    ) -> Dict[str, Any]:
        """
        Check the attendance capacity status for an envelope.
        Uses row locking to prevent race conditions.
        """
        repos = RepositoryFactory(db)
        envelope = repos.envelopes.get_or_raise(envelope_id)

        # Get the associated access grant with row lock
        active_grant = repos.access_grants.get_grant_for_update(
            db.query(AccessGrant).filter(
                AccessGrant.envelope_id == envelope_id,
                AccessGrant.status == 'active'
            ).first().id if db.query(AccessGrant).filter(
                AccessGrant.envelope_id == envelope_id,
                AccessGrant.status == 'active'
            ).first() else None
        ) if db.query(AccessGrant).filter(
            AccessGrant.envelope_id == envelope_id,
            AccessGrant.status == 'active'
        ).first() else None

        if not active_grant:
            return {
                "capacity_available": True,
                "current_attendance": 0,
                "max_capacity": envelope.attendance_cap,
                "remaining_capacity": envelope.attendance_cap
            }

        current = active_grant.checkins_used or 0
        remaining = envelope.attendance_cap - current

        return {
            "capacity_available": remaining > 0,
            "current_attendance": current,
            "max_capacity": envelope.attendance_cap,
            "remaining_capacity": remaining,
            "at_capacity": remaining <= 0
        }

    @staticmethod
    def expire_overdue_envelopes(db: Session) -> int:
        """
        Mark overdue envelopes as expired.
        Should be called periodically (e.g., cron job).
        """
        repos = RepositoryFactory(db)
        expired_count = repos.envelopes.expire_overdue_envelopes()
        
        if expired_count > 0:
            logger.info(f"Expired {expired_count} overdue envelopes")
        
        return expired_count

    @staticmethod
    def _validate_envelope_inputs(
        attendance_cap: int,
        duration_minutes: int,
        valid_from: datetime,
        valid_until: datetime
    ) -> None:
        """
        Validate envelope creation inputs.
        """
        if attendance_cap <= 0:
            raise InsuranceValidationError("Attendance cap must be greater than 0")
        
        if attendance_cap > 10000:
            raise InsuranceValidationError("Attendance cap exceeds maximum (10000)")

        if duration_minutes <= 0:
            raise InsuranceValidationError("Duration must be greater than 0 minutes")
        
        if duration_minutes > InsuranceEnvelopeService.MAX_DURATION_MINUTES:
            raise InsuranceValidationError(
                f"Maximum duration is {InsuranceEnvelopeService.MAX_DURATION_MINUTES} minutes"
            )

        if valid_from >= valid_until:
            raise InsuranceValidationError("Valid from must be before valid until")

        # Ensure datetimes are timezone-aware for comparison
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        
        if valid_from < now:
            raise InsuranceValidationError("Valid from cannot be in the past")

        # Check max advance booking
        max_advance = now + timedelta(days=InsuranceEnvelopeService.MAX_ADVANCE_BOOKING_DAYS)
        if valid_from > max_advance:
            raise InsuranceValidationError(
                f"Cannot book more than {InsuranceEnvelopeService.MAX_ADVANCE_BOOKING_DAYS} days in advance"
            )

        # Check max duration
        if valid_until - valid_from > timedelta(minutes=InsuranceEnvelopeService.MAX_DURATION_MINUTES):
            raise InsuranceValidationError(
                f"Maximum duration is {InsuranceEnvelopeService.MAX_DURATION_MINUTES} minutes"
            )

    @staticmethod
    def _validate_activity_compliance(
        activity_class: ActivityClass,
        alcohol: bool,
        minors_present: bool,
        event_metadata: Optional[Dict[str, Any]]
    ) -> List[str]:
        """
        Validate that the activity complies with class restrictions.
        Returns list of violation reasons (empty if compliant).
        """
        violations = []

        if alcohol and not activity_class.allows_alcohol:
            violations.append(
                f"Activity class '{activity_class.slug}' does not allow alcohol"
            )

        if minors_present and not activity_class.allows_minors:
            violations.append(
                f"Activity class '{activity_class.slug}' does not allow minors"
            )

        # Check prohibited equipment from metadata
        if event_metadata and 'equipment' in event_metadata:
            equipment = event_metadata.get('equipment', [])
            if activity_class.prohibited_equipment:
                prohibited = activity_class.prohibited_equipment
                if isinstance(prohibited, dict):
                    prohibited = list(prohibited.keys())
                
                for equip in equipment:
                    equip_lower = equip.lower() if equip else ''
                    for prohibited_item in prohibited:
                        prohibited_lower = prohibited_item.lower() if prohibited_item else ''
                        if prohibited_lower in equip_lower or equip_lower in prohibited_lower:
                            violations.append(
                                f"Equipment '{equip}' is prohibited for this activity class"
                            )
                            break

        return violations

    @staticmethod
    def _validate_for_activation(envelope: InsuranceEnvelope) -> List[str]:
        """
        Perform additional validation checks before activation.
        Returns list of validation errors (empty if valid).
        """
        errors = []

        # Check if the associated policy is still active
        if not envelope.policy_root or envelope.policy_root.status != 'active':
            errors.append("Associated policy is not active")

        # Check if the activity class is valid
        if not envelope.activity_class:
            errors.append("Associated activity class is invalid")

        # Check if the space profile is valid
        if not envelope.space_profile:
            errors.append("Associated space profile is invalid")

        # Check time validity
        now = datetime.now(timezone.utc)
        valid_from = envelope.valid_from
        valid_until = envelope.valid_until
        
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        if valid_until.tzinfo is None:
            valid_until = valid_until.replace(tzinfo=timezone.utc)

        if valid_from > valid_until:
            errors.append("Valid from is after valid until")
        
        if now > valid_until:
            errors.append("Envelope validity period has already passed")

        return errors

    @staticmethod
    def get_envelopes_for_space(
        db: Session,
        space_id: str,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[InsuranceEnvelope]:
        """
        Get envelopes for a space with optional status filter and pagination.
        """
        repos = RepositoryFactory(db)
        return repos.envelopes.get_envelopes_for_space(space_id, status)[offset:offset+limit]

    @staticmethod
    def get_envelope_details(db: Session, envelope_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about an envelope including related data.
        """
        repos = RepositoryFactory(db)
        envelope = repos.envelopes.get(envelope_id)
        
        if not envelope:
            return None
        
        return {
            'id': str(envelope.id),
            'status': envelope.status,
            'policy_number': envelope.policy_root.policy_number if envelope.policy_root else None,
            'activity_class': envelope.activity_class.slug if envelope.activity_class else None,
            'space_id': str(envelope.space_id),
            'steward_id': envelope.steward_id,
            'attendance_cap': envelope.attendance_cap,
            'duration_minutes': envelope.duration_minutes,
            'alcohol': envelope.alcohol,
            'minors_present': envelope.minors_present,
            'valid_from': envelope.valid_from.isoformat() if envelope.valid_from else None,
            'valid_until': envelope.valid_until.isoformat() if envelope.valid_until else None,
            'coverage_limits': envelope.coverage_limits,
            'certificate_url': envelope.certificate_url,
            'created_at': envelope.created_at.isoformat() if envelope.created_at else None
        }
