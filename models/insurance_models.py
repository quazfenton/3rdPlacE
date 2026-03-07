from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean, Text, ForeignKey, CheckConstraint, Index, event
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func
import uuid
from config.database import Base, engine
import json
import re


# Cross-platform UUID type that works with both PostgreSQL and SQLite
class UUID(TypeDecorator):
    """Platform-independent UUID type.
    Uses PostgreSQL's UUID type when available, otherwise uses CHAR(32).
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql':
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        else:
            return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        elif dialect.name == 'postgresql':
            return value if isinstance(value, str) else str(value)
        else:
            if isinstance(value, uuid.UUID):
                return "%032x" % value.int
            elif isinstance(value, str):
                # Validate UUID format
                try:
                    return "%032x" % uuid.UUID(value).int
                except (ValueError, AttributeError):
                    # If invalid UUID, treat as string ID
                    return value
            else:
                return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if isinstance(value, uuid.UUID):
                return value
            try:
                return uuid.UUID(value)
            except (ValueError, AttributeError):
                # If invalid UUID format, return as string
                return value


# Cross-platform JSONB type
try:
    from sqlalchemy.dialects.postgresql import JSONB as PGJSONB
except ImportError:
    PGJSONB = None


class JSONB(TypeDecorator):
    """Platform-independent JSONB type.
    Uses PostgreSQL's JSONB when available, otherwise uses Text with JSON.
    """
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == 'postgresql' and PGJSONB:
            return dialect.type_descriptor(PGJSONB())
        else:
            return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None or value == '':
            return {}
        if isinstance(value, dict):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}


class PolicyRoot(Base):
    __tablename__ = "policy_root"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    insurer_name = Column(String(255), nullable=False)
    policy_number = Column(String(100), nullable=False, unique=True)
    jurisdiction = Column(String(10), nullable=False)  # e.g. "US-CA"
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_until = Column(DateTime(timezone=True), nullable=False)
    activity_classes = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    base_limits = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    exclusions = Column(MutableDict.as_mutable(JSONB), default=dict)
    status = Column(String(20), nullable=False, default='active')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'expired', 'suspended')",
            name='policy_root_status_check'
        ),
        Index('idx_policy_root_jurisdiction', 'jurisdiction'),
        Index('idx_policy_root_status', 'status'),
    )

    @validates('insurer_name', 'policy_number', 'jurisdiction')
    def validate_strings(self, key, value):
        if value is None:
            raise ValueError(f"{key} cannot be None")
        if not value or len(value.strip()) == 0:
            raise ValueError(f"{key} cannot be empty")
        if key == 'jurisdiction' and not re.match(r'^[A-Z]{2}(-[A-Z]{2})?$', value):
            raise ValueError(f"Invalid jurisdiction format: {value}")
        return value.strip()


class ActivityClass(Base):
    __tablename__ = "activity_class"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    slug = Column(String(50), unique=True, nullable=False)
    description = Column(Text)
    base_risk_score = Column(Numeric(3, 2), default=0.00)  # 0.00–1.00
    default_limits = Column(MutableDict.as_mutable(JSONB), default=dict)
    prohibited_equipment = Column(MutableDict.as_mutable(JSONB), default=dict)
    allows_alcohol = Column(Boolean, default=False)
    allows_minors = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint('base_risk_score >= 0.00 AND base_risk_score <= 1.00', name='activity_class_risk_score_check'),
        Index('idx_activity_class_slug', 'slug'),
    )

    @validates('slug')
    def validate_slug(self, key, value):
        if not value or len(value.strip()) == 0:
            raise ValueError("slug cannot be empty")
        if not re.match(r'^[a-z][a-z0-9_]*$', value):
            raise ValueError(f"Invalid slug format: {value}. Must be lowercase alphanumeric with underscores.")
        return value.strip()

    @validates('base_risk_score')
    def validate_risk_score(self, key, value):
        if value is None:
            return 0.00
        numeric_value = float(value)
        if numeric_value < 0.00 or numeric_value > 1.00:
            raise ValueError(f"Risk score must be between 0.00 and 1.00, got: {numeric_value}")
        return value


class SpaceRiskProfile(Base):
    __tablename__ = "space_risk_profile"

    space_id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    owner_id = Column(String(100), nullable=True)  # Reference to space owner
    name = Column(String(255), nullable=True)
    hazard_rating = Column(Numeric(3, 2), default=0.00)  # 0.00–1.00
    floor_type = Column(String(100))
    stairs = Column(Boolean, default=False)
    tools_present = Column(Boolean, default=False)
    fire_suppression = Column(Boolean, default=False)
    prior_claims = Column(Integer, default=0)
    restrictions = Column(MutableDict.as_mutable(JSONB), default=dict)
    last_inspected_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint('hazard_rating >= 0.00 AND hazard_rating <= 1.00', name='space_risk_profile_hazard_rating_check'),
        CheckConstraint('prior_claims >= 0', name='space_risk_profile_prior_claims_check'),
    )

    @validates('hazard_rating')
    def validate_hazard_rating(self, key, value):
        if value is None:
            return 0.00
        numeric_value = float(value)
        if numeric_value < 0.00 or numeric_value > 1.00:
            raise ValueError(f"Hazard rating must be between 0.00 and 1.00, got: {numeric_value}")
        return value

    @validates('prior_claims')
    def validate_prior_claims(self, key, value):
        if value is None:
            return 0
        if value < 0:
            raise ValueError(f"Prior claims cannot be negative, got: {value}")
        return value


class InsuranceEnvelope(Base):
    __tablename__ = "insurance_envelope"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    policy_root_id = Column(UUID(), ForeignKey("policy_root.id", ondelete="RESTRICT"), nullable=False)
    activity_class_id = Column(UUID(), ForeignKey("activity_class.id", ondelete="RESTRICT"), nullable=False)
    space_id = Column(UUID(), ForeignKey("space_risk_profile.space_id", ondelete="RESTRICT"), nullable=False)
    steward_id = Column(String(100), nullable=False)
    platform_entity_id = Column(String(100), nullable=False)

    event_metadata = Column(MutableDict.as_mutable(JSONB), default=dict)

    attendance_cap = Column(Integer, nullable=False)
    duration_minutes = Column(Integer, nullable=False)

    alcohol = Column(Boolean, default=False)
    minors_present = Column(Boolean, default=False)

    coverage_limits = Column(MutableDict.as_mutable(JSONB), default=dict)
    exclusions = Column(MutableDict.as_mutable(JSONB), default=dict)

    jurisdiction = Column(String(10), nullable=False)

    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)

    certificate_url = Column(String(500))
    certificate_hash = Column(String(64))  # SHA-256 hash for verification

    status = Column(String(20), default='pending')

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'voided', 'expired', 'claim_open')",
            name='insurance_envelope_status_check'
        ),
        CheckConstraint('attendance_cap > 0', name='insurance_envelope_attendance_cap_check'),
        CheckConstraint('duration_minutes > 0', name='insurance_envelope_duration_minutes_check'),
        Index('idx_insurance_envelope_status', 'status'),
        Index('idx_insurance_envelope_validity', 'valid_from', 'valid_until'),
        Index('idx_insurance_envelope_space', 'space_id'),
        Index('idx_insurance_envelope_steward', 'steward_id'),
        Index('idx_insurance_envelope_status_validity', 'status', 'valid_until'),
    )

    # Relationships
    policy_root = relationship("PolicyRoot", lazy="joined")
    activity_class = relationship("ActivityClass", lazy="joined")
    space_profile = relationship("SpaceRiskProfile", foreign_keys=[space_id], lazy="joined")

    @validates('attendance_cap')
    def validate_attendance_cap(self, key, value):
        if value is None or value <= 0:
            raise ValueError(f"Attendance cap must be greater than 0, got: {value}")
        if value > 10000:
            raise ValueError(f"Attendance cap exceeds maximum allowed (10000), got: {value}")
        return value

    @validates('duration_minutes')
    def validate_duration_minutes(self, key, value):
        if value is None or value <= 0:
            raise ValueError(f"Duration must be greater than 0 minutes, got: {value}")
        if value > 1440:  # 24 hours max
            raise ValueError(f"Duration exceeds maximum allowed (1440 minutes), got: {value}")
        return value

    @validates('jurisdiction')
    def validate_jurisdiction(self, key, value):
        if not value or len(value.strip()) == 0:
            raise ValueError("Jurisdiction cannot be empty")
        if not re.match(r'^[A-Z]{2}(-[A-Z]{2})?$', value):
            raise ValueError(f"Invalid jurisdiction format: {value}")
        return value.strip()


class InsurancePricing(Base):
    __tablename__ = "insurance_pricing"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(), ForeignKey("insurance_envelope.id", ondelete="CASCADE"), nullable=False, unique=True)
    base_rate = Column(Numeric(10, 2), nullable=False)
    duration_factor = Column(Numeric(5, 2), default=1.00)
    attendance_factor = Column(Numeric(5, 2), default=1.00)
    jurisdiction_factor = Column(Numeric(5, 2), default=1.00)
    risk_factor = Column(Numeric(5, 2), default=1.00)
    final_price = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default='USD')
    computed_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint('base_rate >= 0', name='insurance_pricing_base_rate_check'),
        CheckConstraint('final_price >= 0', name='insurance_pricing_final_price_check'),
        Index('idx_insurance_pricing_envelope', 'envelope_id'),
    )


class IncidentReport(Base):
    __tablename__ = "incident_report"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(), ForeignKey("insurance_envelope.id", ondelete="CASCADE"), nullable=False)
    reported_by = Column(String(100), nullable=False)
    incident_type = Column(String(50), nullable=False)  # injury, property, behavioral
    severity = Column(String(20), nullable=False)  # low, medium, high
    description = Column(Text)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    evidence_urls = Column(MutableDict.as_mutable(JSONB), default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "incident_type IN ('injury', 'property', 'behavioral', 'other')",
            name='incident_report_type_check'
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name='incident_report_severity_check'
        ),
        Index('idx_incident_report_envelope', 'envelope_id'),
        Index('idx_incident_report_occurred_at', 'occurred_at'),
        Index('idx_incident_report_severity', 'severity'),
    )

    @validates('incident_type', 'severity')
    def validate_enum_fields(self, key, value):
        if not value or len(value.strip()) == 0:
            raise ValueError(f"{key} cannot be empty")
        return value.strip()


class Claim(Base):
    __tablename__ = "claim"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(), ForeignKey("insurance_envelope.id", ondelete="CASCADE"), nullable=False)
    claimant_type = Column(String(50), nullable=False)  # space_owner, participant, platform
    status = Column(String(20), default='opened')
    payout_amount = Column(Numeric(10, 2))
    insurer_reference = Column(String(100))
    description = Column(Text, default="")
    review_notes = Column(Text, default="")  # Separate field for review notes
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True))
    reviewed_by = Column(String(100))

    __table_args__ = (
        CheckConstraint(
            "status IN ('opened', 'under_review', 'approved', 'denied', 'paid')",
            name='claim_status_check'
        ),
        CheckConstraint(
            "claimant_type IN ('space_owner', 'participant', 'platform')",
            name='claim_claimant_type_check'
        ),
        CheckConstraint('payout_amount IS NULL OR payout_amount >= 0', name='claim_payout_amount_check'),
        Index('idx_claim_envelope', 'envelope_id'),
        Index('idx_claim_status', 'status'),
    )

    @validates('claimant_type', 'status')
    def validate_enum_fields(self, key, value):
        if not value or len(value.strip()) == 0:
            raise ValueError(f"{key} cannot be empty")
        return value.strip()


class AccessGrant(Base):
    __tablename__ = "access_grant"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(), ForeignKey("insurance_envelope.id", ondelete="CASCADE"), nullable=False)
    lock_id = Column(String(255), nullable=False)
    lock_vendor = Column(String(50), nullable=False)  # kisi, schlage, generic, etc.
    access_type = Column(String(20), nullable=False)  # qr, pin, bluetooth, api_unlock
    access_payload = Column(MutableDict.as_mutable(JSONB), default=dict)  # Store credential data

    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)

    attendance_cap = Column(Integer, nullable=False)
    checkins_used = Column(Integer, default=0)

    status = Column(String(20), default='active')

    issued_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True))
    revoke_reason = Column(String(255))

    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'revoked', 'expired')",
            name='access_grant_status_check'
        ),
        CheckConstraint(
            "access_type IN ('qr', 'pin', 'bluetooth', 'api_unlock')",
            name='access_grant_type_check'
        ),
        CheckConstraint('attendance_cap > 0', name='access_grant_attendance_cap_check'),
        CheckConstraint('checkins_used >= 0', name='access_grant_checkins_used_check'),
        Index('idx_access_grant_envelope', 'envelope_id'),
        Index('idx_access_grant_lock', 'lock_id'),
        Index('idx_access_grant_validity', 'valid_from', 'valid_until'),
        Index('idx_access_grant_status', 'status'),
    )

    @validates('lock_vendor', 'access_type')
    def validate_enum_fields(self, key, value):
        if not value or len(value.strip()) == 0:
            raise ValueError(f"{key} cannot be empty")
        return value.strip()

    @validates('checkins_used')
    def validate_checkins_used(self, key, value):
        if value is None:
            return 0
        if value < 0:
            raise ValueError(f"checkins_used cannot be negative, got: {value}")
        return value


class AuditLog(Base):
    """
    Audit log model for tracking important system events
    """
    __tablename__ = "audit_log"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    event_type = Column(String(50), nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(), nullable=False)
    actor_id = Column(String(100))
    action = Column(String(50), nullable=False)
    reason = Column(Text)
    metadata = Column(JSONB, default=dict)
    ip_address = Column(String(45))  # IPv6 max length
    user_agent = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index('idx_audit_log_entity', 'entity_type', 'entity_id'),
        Index('idx_audit_log_event_type', 'event_type'),
        Index('idx_audit_log_created_at', 'created_at'),
        Index('idx_audit_log_actor', 'actor_id'),
    )

    @validates('event_type', 'entity_type', 'action')
    def validate_enum_fields(self, key, value):
        if not value or len(value.strip()) == 0:
            raise ValueError(f"{key} cannot be empty")
        return value.strip()


class User(Base):
    """
    User model for authentication
    """
    __tablename__ = "users"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    username = Column(String(50), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default='participant')
    disabled = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_login_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'platform_operator', 'space_owner', 'steward', 'participant')",
            name='user_role_check'
        ),
    )

    @validates('username', 'email', 'role')
    def validate_strings(self, key, value):
        if value is None:
            raise ValueError(f"{key} cannot be None")
        if not value or len(value.strip()) == 0:
            raise ValueError(f"{key} cannot be empty")
        if key == 'email' and not re.match(r'^[^@]+@[^@]+\.[^@]+$', value):
            raise ValueError(f"Invalid email format: {value}")
        if key == 'username' and not re.match(r'^[a-zA-Z][a-zA-Z0-9_]{2,49}$', value):
            raise ValueError(f"Invalid username format: {value}")
        return value.strip()


class RefreshToken(Base):
    """
    Refresh token model for token rotation
    """
    __tablename__ = "refresh_tokens"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    used_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index('idx_refresh_tokens_user', 'user_id'),
        Index('idx_refresh_tokens_expires', 'expires_at'),
    )
