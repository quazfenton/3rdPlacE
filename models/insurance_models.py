from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean, Text, ForeignKey, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.types import TypeDecorator, CHAR
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from config.database import Base, engine

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
            return str(value)
        else:
            if not isinstance(value, uuid.UUID):
                return "%032x" % uuid.UUID(value).int
            return "%032x" % value.int

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        else:
            if not isinstance(value, uuid.UUID):
                value = uuid.UUID(value)
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
        import json
        return json.dumps(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        import json
        if isinstance(value, str):
            return json.loads(value)
        return value


class PolicyRoot(Base):
    __tablename__ = "policy_root"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    insurer_name = Column(String, nullable=False)
    policy_number = Column(String, nullable=False)
    jurisdiction = Column(String, nullable=False)  # e.g. "US-CA"
    effective_from = Column(DateTime(timezone=True), nullable=False)
    effective_until = Column(DateTime(timezone=True), nullable=False)
    activity_classes = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    base_limits = Column(MutableDict.as_mutable(JSONB), nullable=False, default=dict)
    exclusions = Column(MutableDict.as_mutable(JSONB), default=dict)
    status = Column(String, nullable=False)  # active, expired, suspended
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            status.in_(['active', 'expired', 'suspended']),
            name='policy_root_status_check'
        ),
    )


class ActivityClass(Base):
    __tablename__ = "activity_class"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    slug = Column(String, unique=True, nullable=False)  # passive, light_physical, tool_based
    description = Column(Text)
    base_risk_score = Column(Numeric(3, 2), default=0.00)  # 0.00–1.00
    default_limits = Column(MutableDict.as_mutable(JSONB), default=dict)
    prohibited_equipment = Column(MutableDict.as_mutable(JSONB), default=dict)
    allows_alcohol = Column(Boolean, default=False)
    allows_minors = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SpaceRiskProfile(Base):
    __tablename__ = "space_risk_profile"

    space_id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    hazard_rating = Column(Numeric(3, 2), default=0.00)  # 0.00–1.00
    floor_type = Column(String)
    stairs = Column(Boolean, default=False)
    tools_present = Column(Boolean, default=False)
    fire_suppression = Column(Boolean, default=False)
    prior_claims = Column(Integer, default=0)
    restrictions = Column(MutableDict.as_mutable(JSONB), default=dict)
    last_inspected_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InsuranceEnvelope(Base):
    __tablename__ = "insurance_envelope"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    policy_root_id = Column(UUID(), ForeignKey("policy_root.id"), nullable=False)
    activity_class_id = Column(UUID(), ForeignKey("activity_class.id"), nullable=False)
    space_id = Column(UUID(), ForeignKey("space_risk_profile.space_id"), nullable=False)
    steward_id = Column(String, nullable=False)
    platform_entity_id = Column(String, nullable=False)

    event_metadata = Column(MutableDict.as_mutable(JSONB), default=dict)  # declared activity, equipment, notes

    attendance_cap = Column(Integer, nullable=False)
    duration_minutes = Column(Integer, nullable=False)

    alcohol = Column(Boolean, default=False)
    minors_present = Column(Boolean, default=False)

    coverage_limits = Column(MutableDict.as_mutable(JSONB), default=dict)
    exclusions = Column(MutableDict.as_mutable(JSONB), default=dict)

    jurisdiction = Column(String, nullable=False)

    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)

    certificate_url = Column(String)

    status = Column(String, default='pending')  # pending, active, voided, expired, claim_open

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            status.in_(['pending', 'active', 'voided', 'expired', 'claim_open']),
            name='insurance_envelope_status_check'
        ),
    )

    # Relationships
    policy_root = relationship("PolicyRoot", lazy="joined")
    activity_class = relationship("ActivityClass", lazy="joined")
    space_profile = relationship("SpaceRiskProfile", foreign_keys=[space_id], lazy="joined")


class InsurancePricing(Base):
    __tablename__ = "insurance_pricing"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(), ForeignKey("insurance_envelope.id"), nullable=False)
    base_rate = Column(Numeric(10, 2), nullable=False)
    duration_factor = Column(Numeric(5, 2), default=1.00)
    attendance_factor = Column(Numeric(5, 2), default=1.00)
    jurisdiction_factor = Column(Numeric(5, 2), default=1.00)
    risk_factor = Column(Numeric(5, 2), default=1.00)
    final_price = Column(Numeric(10, 2), nullable=False)
    computed_at = Column(DateTime(timezone=True), server_default=func.now())


class IncidentReport(Base):
    __tablename__ = "incident_report"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(), ForeignKey("insurance_envelope.id"), nullable=False)
    reported_by = Column(String, nullable=False)
    incident_type = Column(String, nullable=False)  # injury, property, behavioral
    severity = Column(String, nullable=False)  # low, medium, high
    description = Column(Text)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    evidence_urls = Column(MutableDict.as_mutable(JSONB), default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Claim(Base):
    __tablename__ = "claim"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(), ForeignKey("insurance_envelope.id"), nullable=False)
    claimant_type = Column(String, nullable=False)  # space_owner, participant, platform
    status = Column(String, default='opened')  # opened, under_review, approved, denied, paid
    payout_amount = Column(Numeric(10, 2))
    insurer_reference = Column(String)
    description = Column(Text, default="")
    opened_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_at = Column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            status.in_(['opened', 'under_review', 'approved', 'denied', 'paid']),
            name='claim_status_check'
        ),
    )


class AccessGrant(Base):
    __tablename__ = "access_grant"

    id = Column(UUID(), primary_key=True, default=uuid.uuid4)
    envelope_id = Column(UUID(), ForeignKey("insurance_envelope.id"), nullable=False)
    lock_id = Column(String, nullable=False)
    access_type = Column(String, nullable=False)  # qr, pin, bluetooth, api_unlock

    valid_from = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=False)

    attendance_cap = Column(Integer, nullable=False)
    checkins_used = Column(Integer, default=0)

    status = Column(String, default='active')  # active, revoked, expired

    issued_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            status.in_(['active', 'revoked', 'expired']),
            name='access_grant_status_check'
        ),
        CheckConstraint(
            access_type.in_(['qr', 'pin', 'bluetooth', 'api_unlock']),
            name='access_grant_type_check'
        ),
    )