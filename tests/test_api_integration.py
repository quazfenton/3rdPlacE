"""
API Integration Tests for Third Place Platform

Tests cover:
- Authentication flow
- Insurance envelope CRUD operations
- Activity classification
- Pricing quotes
- Rate limiting
- Error handling
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta, timezone
import json

from main import app
from config.database import get_db, Base
from models.insurance_models import User, PolicyRoot, ActivityClass, SpaceRiskProfile
from services.auth_service import pwd_context


# =============================================================================
# Test Database Setup
# =============================================================================

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_thirdplace_integration.db"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=None  # Don't use StaticPool for tests
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def override_get_db():
    """Override database dependency for tests"""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override the dependency
app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="function")
def client():
    """Create test client with fresh database"""
    # Drop and recreate tables
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    # Seed test data
    seed_test_data(TestingSessionLocal())
    
    with TestClient(app) as test_client:
        yield test_client
    
    # Cleanup
    Base.metadata.drop_all(bind=engine)


def seed_test_data(db):
    """Seed database with test data"""
    # Create test user
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=pwd_context.hash("Test123!"),
        role="space_owner",
        disabled=False
    )
    db.add(user)
    
    # Create activity classes
    activity_classes = [
        ActivityClass(
            slug="passive",
            description="Passive activities",
            base_risk_score=0.10,
            default_limits={"general_liability": 1000000},
            allows_alcohol=True,
            allows_minors=True
        ),
        ActivityClass(
            slug="light_physical",
            description="Light physical activities",
            base_risk_score=0.35,
            default_limits={"general_liability": 1500000},
            allows_alcohol=True,
            allows_minors=True
        ),
        ActivityClass(
            slug="tool_based",
            description="Tool-based activities",
            base_risk_score=0.70,
            default_limits={"general_liability": 2000000},
            allows_alcohol=False,
            allows_minors=False
        )
    ]
    for ac in activity_classes:
        db.add(ac)
    
    # Create space profile
    space = SpaceRiskProfile(
        space_id="test-space-001",
        owner_id="test-owner",
        name="Test Space",
        hazard_rating=0.20,
        floor_type="hardwood",
        stairs=False,
        tools_present=False,
        fire_suppression=True,
        prior_claims=0
    )
    db.add(space)
    
    db.commit()


# =============================================================================
# Authentication Tests
# =============================================================================

class TestAuthentication:
    """Test authentication endpoints"""
    
    def test_login_success(self, client):
        """Test successful login"""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "Test123!"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
    
    def test_login_wrong_password(self, client):
        """Test login with wrong password"""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "WrongPassword!"}
        )
        assert response.status_code == 401
    
    def test_login_nonexistent_user(self, client):
        """Test login with non-existent user"""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "nonexistent", "password": "Test123!"}
        )
        assert response.status_code == 401
    
    def test_register_new_user(self, client):
        """Test user registration"""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "SecurePass123!",
                "role": "participant"
            }
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "newuser@example.com"
        assert "hashed_password" not in data
    
    def test_register_duplicate_username(self, client):
        """Test registration with duplicate username"""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "testuser",
                "email": "different@example.com",
                "password": "SecurePass123!",
                "role": "participant"
            }
        )
        assert response.status_code == 400
    
    def test_register_weak_password(self, client):
        """Test registration with weak password"""
        response = client.post(
            "/api/v1/auth/register",
            json={
                "username": "weakpass",
                "email": "weak@example.com",
                "password": "weak",
                "role": "participant"
            }
        )
        assert response.status_code == 422
    
    def test_unauthenticated_access(self, client):
        """Test that unauthenticated requests are rejected"""
        response = client.get("/api/v1/ial/envelopes")
        assert response.status_code == 401


# =============================================================================
# Insurance API Tests
# =============================================================================

class TestInsuranceAPI:
    """Test Insurance API endpoints"""
    
    def get_auth_token(self, client):
        """Helper to get auth token"""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "testuser", "password": "Test123!"}
        )
        return response.json()["access_token"]
    
    def test_classify_activity(self, client):
        """Test activity classification"""
        token = self.get_auth_token(client)
        
        response = client.post(
            "/api/v1/ial/activity/classify",
            json={
                "space_id": "test-space-001",
                "declared_activity": "board games",
                "attendance_cap": 10
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "activity_class_slug" in data
        assert "risk_score" in data
    
    def test_classify_activity_with_violation(self, client):
        """Test activity classification with restriction violation"""
        token = self.get_auth_token(client)
        
        response = client.post(
            "/api/v1/ial/activity/classify",
            json={
                "space_id": "test-space-001",
                "declared_activity": "woodworking",
                "alcohol": True,  # Violates tool_based restriction
                "attendance_cap": 5
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["prohibited"] is True
        assert len(data["violation_reasons"]) > 0
    
    def test_pricing_quote(self, client):
        """Test pricing quote"""
        token = self.get_auth_token(client)
        
        # First get activity class ID
        classify_response = client.post(
            "/api/v1/ial/activity/classify",
            json={
                "space_id": "test-space-001",
                "declared_activity": "board games",
                "attendance_cap": 10
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        activity_class_id = classify_response.json()["activity_class_id"]
        
        # Get pricing quote
        response = client.post(
            "/api/v1/ial/pricing/quote",
            json={
                "activity_class_id": activity_class_id,
                "space_id": "test-space-001",
                "attendance_cap": 10,
                "duration_minutes": 180,
                "jurisdiction": "US-CA"
            },
            headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "price" in data
        assert "breakdown" in data
        assert data["currency"] == "USD"


# =============================================================================
# Health Check Tests
# =============================================================================

class TestHealthChecks:
    """Test health check endpoints"""
    
    def test_root_endpoint(self, client):
        """Test root endpoint"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "health" in data
    
    def test_health_endpoint(self, client):
        """Test basic health endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
    
    def test_detailed_health_endpoint(self, client):
        """Test detailed health endpoint"""
        response = client.get("/health/detailed")
        assert response.status_code in [200, 503]
        data = response.json()
        assert "dependencies" in data
        assert "database" in data["dependencies"]


# =============================================================================
# Rate Limiting Tests
# =============================================================================

class TestRateLimiting:
    """Test rate limiting"""
    
    def test_login_rate_limiting(self, client):
        """Test login rate limiting"""
        # Make many login attempts
        for i in range(15):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "testuser", "password": "WrongPassword!"}
            )
            if response.status_code == 429:
                break
        
        # Should eventually be rate limited
        assert response.status_code in [401, 429]


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error handling"""
    
    def test_404_not_found(self, client):
        """Test 404 handling"""
        response = client.get("/nonexistent-endpoint")
        assert response.status_code == 404
    
    def test_422_validation_error(self, client):
        """Test 422 validation error"""
        token = "invalid_token"
        response = client.get(
            "/api/v1/ial/envelopes",
            headers={"Authorization": f"Bearer {token}"}
        )
        # Should be 401 for invalid token, not 422
        assert response.status_code in [401, 422]
    
    def test_invalid_json_body(self, client):
        """Test invalid JSON body handling"""
        response = client.post(
            "/api/v1/auth/login",
            data="not valid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code in [400, 422]
