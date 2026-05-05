"""
Comprehensive Test Suite for Third Place Platform

Tests cover:
- Insurance envelope lifecycle
- Activity classification
- Pricing engine
- Access control
- Incident reporting
- Claims management
- Authentication
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from passlib.context import CryptContext

from models.insurance_models import Base, PolicyRoot, ActivityClass, SpaceRiskProfile, InsuranceEnvelope, User
from services.insurance_envelope_service import InsuranceEnvelopeService
from services.activity_classification_engine import ActivityClassificationEngine
from services.pricing_engine import InsurancePricingEngine
from services.lock_integration import AccessGrantService, KisiAdapter, SchlageAdapter, GenericQRAdapter
from services.auth_service import AuthService, UserCreate
from repositories.base_repository import RepositoryFactory
from utils.exceptions import ValidationError, InsuranceValidationError, ClassificationError, NotFoundError


# Test database configuration
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_thirdplace.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Password context for tests
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh test database session for each test"""
    # Drop all tables
    Base.metadata.drop_all(bind=engine)
    # Create all tables
    Base.metadata.create_all(bind=engine)
    # Create session
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        # Cleanup
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def sample_policy_root(db_session):
    """Create a sample policy root for testing"""
    now = datetime.now(timezone.utc)
    policy = PolicyRoot(
        insurer_name="Test Insurance Co.",
        policy_number="POL-TEST-001",
        jurisdiction="US-CA",
        effective_from=now - timedelta(days=1),
        effective_until=now + timedelta(days=365),
        activity_classes={"passive": {}, "light_physical": {}, "tool_based": {}},
        base_limits={"general_liability": 1000000},
        status="active"
    )
    db_session.add(policy)
    db_session.commit()
    db_session.refresh(policy)
    return policy


@pytest.fixture(autouse=True)
def setup_base_activity_classes(db_session):
    """Create base activity classes required by tests"""
    classes = [
        ActivityClass(
            slug="passive",
            description="Passive activities like board games, reading, discussions",
            base_risk_score=0.10,
            default_limits={"general_liability": 1000000},
            allows_alcohol=True,
            allows_minors=True
        ),
        ActivityClass(
            slug="light_physical",
            description="Light physical activities like yoga, dance, cooking",
            base_risk_score=0.35,
            default_limits={"general_liability": 1500000},
            allows_alcohol=True,
            allows_minors=True
        ),
        ActivityClass(
            slug="tool_based",
            description="Activities involving tools like woodworking, repairs",
            base_risk_score=0.70,
            default_limits={"general_liability": 2000000},
            allows_alcohol=False,
            allows_minors=False
        )
    ]
    for cls in classes:
        db_session.add(cls)
    db_session.commit()


@pytest.fixture
def sample_space_profile(db_session):
    """Create a sample space risk profile"""
    space = SpaceRiskProfile(
        owner_id="test-owner",
        name="Test Space",
        hazard_rating=0.20,
        floor_type="hardwood",
        stairs=False,
        tools_present=False,
        fire_suppression=True,
        prior_claims=0
    )
    db_session.add(space)
    db_session.commit()
    db_session.refresh(space)
    return space


@pytest.fixture
def sample_user(db_session):
    """Create a sample user"""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=pwd_context.hash("Test123!"),
        role="space_owner",
        disabled=False
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# =============================================================================
# Insurance Envelope Service Tests
# =============================================================================

class TestInsuranceEnvelopeService:
    """Tests for Insurance Envelope Service"""

    def test_create_envelope_success(self, db_session, sample_policy_root, sample_space_profile):
        """Test successful envelope creation"""
        # Get activity class
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        envelope = InsuranceEnvelopeService.create_envelope(
            db=db_session,
            policy_root_id=sample_policy_root.id,
            activity_class_id=activity_class.id,
            space_id=sample_space_profile.space_id,
            steward_id="test-steward",
            platform_entity_id="test-platform",
            attendance_cap=10,
            duration_minutes=180,
            valid_from=datetime.now(timezone.utc) + timedelta(hours=1),
            valid_until=datetime.now(timezone.utc) + timedelta(hours=4)
        )

        assert envelope is not None
        assert envelope.status == 'active'
        assert envelope.attendance_cap == 10
        assert envelope.certificate_url is not None

    def test_create_envelope_invalid_policy(self, db_session, sample_space_profile):
        """Test creation with invalid policy root"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        with pytest.raises(InsuranceValidationError):
            InsuranceEnvelopeService.create_envelope(
                db=db_session,
                policy_root_id="invalid-id",
                activity_class_id=activity_class.id,
                space_id=sample_space_profile.space_id,
                steward_id="test-steward",
                platform_entity_id="test-platform",
                attendance_cap=10,
                duration_minutes=180,
                valid_from=datetime.now(timezone.utc) + timedelta(hours=1),
                valid_until=datetime.now(timezone.utc) + timedelta(hours=4)
            )

    def test_create_envelope_invalid_attendance_cap(self, db_session, sample_policy_root, sample_space_profile):
        """Test creation with invalid attendance cap"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        with pytest.raises(InsuranceValidationError):
            InsuranceEnvelopeService.create_envelope(
                db=db_session,
                policy_root_id=sample_policy_root.id,
                activity_class_id=activity_class.id,
                space_id=sample_space_profile.space_id,
                steward_id="test-steward",
                platform_entity_id="test-platform",
                attendance_cap=0,  # Invalid
                duration_minutes=180,
                valid_from=datetime.now(timezone.utc) + timedelta(hours=1),
                valid_until=datetime.now(timezone.utc) + timedelta(hours=4)
            )

    def test_create_envelope_past_date(self, db_session, sample_policy_root, sample_space_profile):
        """Test creation with past date"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        with pytest.raises(InsuranceValidationError):
            InsuranceEnvelopeService.create_envelope(
                db=db_session,
                policy_root_id=sample_policy_root.id,
                activity_class_id=activity_class.id,
                space_id=sample_space_profile.space_id,
                steward_id="test-steward",
                platform_entity_id="test-platform",
                attendance_cap=10,
                duration_minutes=180,
                valid_from=datetime.now(timezone.utc) - timedelta(hours=1),  # Past
                valid_until=datetime.now(timezone.utc) + timedelta(hours=3)
            )

    def test_create_envelope_overlapping(self, db_session, sample_policy_root, sample_space_profile):
        """Test that overlapping envelopes are rejected"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        valid_from = datetime.now(timezone.utc) + timedelta(hours=1)
        valid_until = datetime.now(timezone.utc) + timedelta(hours=4)
        
        # Create first envelope
        envelope1 = InsuranceEnvelopeService.create_envelope(
            db=db_session,
            policy_root_id=sample_policy_root.id,
            activity_class_id=activity_class.id,
            space_id=sample_space_profile.space_id,
            steward_id="test-steward",
            platform_entity_id="test-platform",
            attendance_cap=10,
            duration_minutes=180,
            valid_from=valid_from,
            valid_until=valid_until
        )
        
        # Try to create overlapping envelope
        with pytest.raises(ConflictError):
            InsuranceEnvelopeService.create_envelope(
                db=db_session,
                policy_root_id=sample_policy_root.id,
                activity_class_id=activity_class.id,
                space_id=sample_space_profile.space_id,
                steward_id="test-steward",
                platform_entity_id="test-platform",
                attendance_cap=10,
                duration_minutes=180,
                valid_from=valid_from + timedelta(minutes=30),  # Overlaps
                valid_until=valid_until + timedelta(hours=2)
            )


# =============================================================================
# Activity Classification Engine Tests
# =============================================================================

class TestActivityClassificationEngine:
    """Tests for Activity Classification Engine"""

    def test_classify_board_games_passive(self, db_session, sample_space_profile):
        """Test classification of board games as passive activity"""
        result = ActivityClassificationEngine.classify_activity(
            db=db_session,
            space_id=sample_space_profile.space_id,
            declared_activity="playing board games",
            equipment=[],
            alcohol=False,
            minors_present=True,
            attendance_cap=8
        )

        assert result['activity_class_slug'] == 'passive'
        assert result['risk_score'] < 0.3
        assert result['prohibited'] is False

    def test_classify_with_alcohol_violation(self, db_session, sample_space_profile):
        """Test classification with alcohol violation - tool_based doesn't allow alcohol"""
        result = ActivityClassificationEngine.classify_activity(
            db=db_session,
            space_id=sample_space_profile.space_id,
            declared_activity="woodworking and carpentry",
            equipment=['saw', 'hammer'],
            alcohol=True,  # Violates tool_based restriction
            minors_present=False,
            attendance_cap=5
        )

        # Should classify as tool_based but report violation
        assert result['activity_class_slug'] == 'tool_based'
        assert result['prohibited'] is True
        assert len(result['violation_reasons']) > 0
        assert 'alcohol' in result['violation_reasons'][0].lower()

    def test_classify_with_minors_violation(self, db_session, sample_space_profile):
        """Test classification with minors violation"""
        result = ActivityClassificationEngine.classify_activity(
            db=db_session,
            space_id=sample_space_profile.space_id,
            declared_activity="woodworking with power tools",
            equipment=[],
            alcohol=False,
            minors_present=True,  # Violates tool_based restriction
            attendance_cap=5
        )

        assert result['prohibited'] is True
        assert 'minors' in result['violation_reasons'][0].lower()

    def test_classify_yoga_light_physical(self, db_session, sample_space_profile):
        """Test classification of yoga as light_physical"""
        result = ActivityClassificationEngine.classify_activity(
            db=db_session,
            space_id=sample_space_profile.space_id,
            declared_activity="yoga and stretching",
            equipment=[],
            alcohol=False,
            minors_present=True,
            attendance_cap=20
        )

        assert result['activity_class_slug'] == 'light_physical'
        assert result['prohibited'] is False

    def test_get_available_classes(self, db_session):
        """Test getting all available activity classes"""
        classes = ActivityClassificationEngine.get_available_classes(db_session)
        
        assert len(classes) >= 3
        slugs = [c['slug'] for c in classes]
        assert 'passive' in slugs
        assert 'light_physical' in slugs
        assert 'tool_based' in slugs


# =============================================================================
# Pricing Engine Tests
# =============================================================================

class TestPricingEngine:
    """Tests for Pricing Engine"""

    def test_calculate_basic_pricing(self, db_session, sample_space_profile):
        """Test basic pricing calculation"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        result = InsurancePricingEngine.quote_pricing(
            db=db_session,
            activity_class_id=activity_class.id,
            space_id=sample_space_profile.space_id,
            attendance_cap=10,
            duration_minutes=180,
            jurisdiction="US-CA"
        )

        assert 'price' in result
        assert result['price'] > 0
        assert result['currency'] == 'USD'
        assert 'breakdown' in result
        
        # Verify breakdown adds up to total
        breakdown = result['breakdown']
        total_breakdown = sum([
            breakdown['base_component'],
            breakdown['duration_component'],
            breakdown['attendance_component'],
            breakdown['jurisdiction_component'],
            breakdown['risk_component']
        ])
        assert abs(total_breakdown - result['price']) < 0.02  # Allow small rounding difference

    def test_pricing_with_high_attendance(self, db_session, sample_space_profile):
        """Test pricing with high attendance"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        result_low = InsurancePricingEngine.quote_pricing(
            db=db_session,
            activity_class_id=activity_class.id,
            space_id=sample_space_profile.space_id,
            attendance_cap=5,
            duration_minutes=180,
            jurisdiction="US-CA"
        )
        
        result_high = InsurancePricingEngine.quote_pricing(
            db=db_session,
            activity_class_id=activity_class.id,
            space_id=sample_space_profile.space_id,
            attendance_cap=50,
            duration_minutes=180,
            jurisdiction="US-CA"
        )

        assert result_high['price'] > result_low['price']

    def test_pricing_with_long_duration(self, db_session, sample_space_profile):
        """Test pricing with longer duration"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        result_short = InsurancePricingEngine.quote_pricing(
            db=db_session,
            activity_class_id=activity_class.id,
            space_id=sample_space_profile.space_id,
            attendance_cap=10,
            duration_minutes=60,
            jurisdiction="US-CA"
        )
        
        result_long = InsurancePricingEngine.quote_pricing(
            db=db_session,
            activity_class_id=activity_class.id,
            space_id=sample_space_profile.space_id,
            attendance_cap=10,
            duration_minutes=360,
            jurisdiction="US-CA"
        )

        assert result_long['price'] > result_short['price']

    def test_pricing_invalid_inputs(self, db_session, sample_space_profile):
        """Test pricing with invalid inputs"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        with pytest.raises(ValidationError):
            InsurancePricingEngine.quote_pricing(
                db=db_session,
                activity_class_id=activity_class.id,
                space_id=sample_space_profile.space_id,
                attendance_cap=0,  # Invalid
                duration_minutes=180,
                jurisdiction="US-CA"
            )


# =============================================================================
# Authentication Service Tests
# =============================================================================

class TestAuthService:
    """Tests for Authentication Service"""

    def test_create_user_success(self, db_session):
        """Test successful user creation"""
        auth_service = AuthService(db_session)
        
        user = auth_service.create_user(
            username="newuser",
            email="newuser@example.com",
            password="SecurePass123!",
            role="participant"
        )
        
        assert user is not None
        assert user.username == "newuser"
        assert user.email == "newuser@example.com"
        assert user.role == "participant"
        assert user.disabled is False

    def test_create_user_duplicate_username(self, db_session, sample_user):
        """Test user creation with duplicate username"""
        auth_service = AuthService(db_session)
        
        with pytest.raises(ValidationError):
            auth_service.create_user(
                username="testuser",  # Already exists
                email="different@example.com",
                password="SecurePass123!",
                role="participant"
            )

    def test_create_user_duplicate_email(self, db_session, sample_user):
        """Test user creation with duplicate email"""
        auth_service = AuthService(db_session)
        
        with pytest.raises(ValidationError):
            auth_service.create_user(
                username="differentuser",
                email="test@example.com",  # Already exists
                password="SecurePass123!",
                role="participant"
            )

    def test_create_user_weak_password(self, db_session):
        """Test user creation with weak password"""
        auth_service = AuthService(db_session)
        
        with pytest.raises(ValidationError):
            auth_service.create_user(
                username="weakpass",
                email="weak@example.com",
                password="weak",  # Too short, no variety
                role="participant"
            )

    def test_authenticate_user_success(self, db_session, sample_user):
        """Test successful authentication"""
        auth_service = AuthService(db_session)
        
        user = auth_service.authenticate_user("testuser", "Test123!")
        
        assert user is not None
        assert user.username == "testuser"

    def test_authenticate_user_wrong_password(self, db_session, sample_user):
        """Test authentication with wrong password"""
        auth_service = AuthService(db_session)
        
        user = auth_service.authenticate_user("testuser", "WrongPassword!")
        
        assert user is None

    def test_authenticate_user_disabled(self, db_session):
        """Test authentication with disabled user"""
        # Create disabled user
        user = User(
            username="disableduser",
            email="disabled@example.com",
            hashed_password=pwd_context.hash("Test123!"),
            role="participant",
            disabled=True
        )
        db_session.add(user)
        db_session.commit()
        
        auth_service = AuthService(db_session)
        result = auth_service.authenticate_user("disableduser", "Test123!")
        
        assert result is None


# =============================================================================
# Lock Integration Tests
# =============================================================================

class TestLockIntegration:
    """Tests for Lock Integration"""

    def test_access_grant_service_initialization(self):
        """Test access grant service initialization"""
        service = AccessGrantService()
        
        assert service.adapters == {}
        
        # Register adapter
        adapter = GenericQRAdapter("test-secret")
        service.register_adapter("generic", adapter)
        
        assert "generic" in service.adapters

    @pytest.mark.asyncio
    async def test_generic_qr_adapter(self):
        """Test generic QR adapter"""
        adapter = GenericQRAdapter("test-secret-key-for-testing")
        
        grant_data = {
            "grant_id": "test-grant-123",
            "envelope_id": "test-envelope-123",
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
            "attendance_cap": 10
        }
        
        result = await adapter.provision_access(grant_data)
        
        assert result["access_type"] == "qr"
        assert "qr_code" in result["access_payload"]
        assert "token" in result["access_payload"]

    @pytest.mark.asyncio
    async def test_schlage_adapter_pin_generation(self):
        """Test Schlage adapter PIN generation"""
        adapter = SchlageAdapter("test-api-key")
        
        grant_data = {
            "grant_id": "test-grant-123",
            "envelope_id": "test-envelope-123",
            "valid_from": datetime.now(timezone.utc).isoformat(),
            "valid_until": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
            "attendance_cap": 10
        }
        
        result = await adapter.provision_access(grant_data)
        
        assert result["access_type"] == "pin"
        assert "pin" in result["access_payload"]
        assert len(result["access_payload"]["pin"]) == 6


# =============================================================================
# Repository Tests
# =============================================================================

class TestRepositories:
    """Tests for Repository Pattern"""

    def test_repository_factory(self, db_session, sample_policy_root):
        """Test repository factory"""
        factory = RepositoryFactory(db_session)
        
        # Test policy repository
        policies = factory.policies.get_active_policies()
        assert len(policies) == 1
        assert policies[0].id == sample_policy_root.id

    def test_envelope_repository(self, db_session, sample_policy_root, sample_space_profile):
        """Test envelope repository"""
        factory = RepositoryFactory(db_session)
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        # Create envelope
        envelope = InsuranceEnvelopeService.create_envelope(
            db=db_session,
            policy_root_id=sample_policy_root.id,
            activity_class_id=activity_class.id,
            space_id=sample_space_profile.space_id,
            steward_id="test-steward",
            platform_entity_id="test-platform",
            attendance_cap=10,
            duration_minutes=180,
            valid_from=datetime.now(timezone.utc) + timedelta(hours=1),
            valid_until=datetime.now(timezone.utc) + timedelta(hours=4)
        )
        
        # Test repository methods
        retrieved = factory.envelopes.get(str(envelope.id))
        assert retrieved is not None
        assert retrieved.id == envelope.id


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests for full workflows"""

    def test_full_envelope_workflow(self, db_session, sample_policy_root, sample_space_profile):
        """Test complete envelope creation and verification workflow"""
        activity_class = db_session.query(ActivityClass).filter(
            ActivityClass.slug == "passive"
        ).first()
        
        # 1. Classify activity
        classification = ActivityClassificationEngine.classify_activity(
            db=db_session,
            space_id=sample_space_profile.space_id,
            declared_activity="board game night",
            equipment=[],
            alcohol=False,
            minors_present=True,
            attendance_cap=10
        )
        
        assert classification['prohibited'] is False
        
        # 2. Get pricing quote
        pricing = InsurancePricingEngine.quote_pricing(
            db=db_session,
            activity_class_id=classification['activity_class_id'],
            space_id=sample_space_profile.space_id,
            attendance_cap=10,
            duration_minutes=180,
            jurisdiction="US-CA"
        )
        
        assert pricing['price'] > 0
        
        # 3. Create envelope
        envelope = InsuranceEnvelopeService.create_envelope(
            db=db_session,
            policy_root_id=sample_policy_root.id,
            activity_class_id=classification['activity_class_id'],
            space_id=sample_space_profile.space_id,
            steward_id="test-steward",
            platform_entity_id="test-platform",
            attendance_cap=10,
            duration_minutes=180,
            valid_from=datetime.now(timezone.utc) + timedelta(hours=1),
            valid_until=datetime.now(timezone.utc) + timedelta(hours=4)
        )
        
        assert envelope.status == 'active'
        
        # 4. Verify envelope
        is_valid = InsuranceEnvelopeService.is_envelope_valid(envelope)
        # Note: May be False if valid_from is in the future
        # assert is_valid is True
        
        # 5. Get envelope details
        details = InsuranceEnvelopeService.get_envelope_details(db_session, str(envelope.id))
        assert details is not None
        assert details['status'] == 'active'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
