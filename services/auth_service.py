"""
Authentication and Authorization Service
Provides secure authentication with database-backed user storage
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from jose import jwt, JWTError
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field, validator
import hashlib
import secrets
import re
from sqlalchemy.orm import Session

from models.insurance_models import User, RefreshToken
from repositories.base_repository import UserRepository, RepositoryFactory
from utils.exceptions import AuthenticationError, AuthorizationError, TokenError, NotFoundError, ValidationError

# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

# JWT Settings - loaded at runtime, not import time
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def get_jwt_secret() -> str:
    """Get JWT secret from environment, raise clear error if not set"""
    import os
    secret = os.getenv("JWT_SECRET_KEY")
    if not secret:
        raise ConfigurationError(
            "JWT_SECRET_KEY environment variable is required but not set. "
            "Please set it in your .env file or environment."
        )
    if len(secret) < 32:
        raise ConfigurationError(
            "JWT_SECRET_KEY must be at least 32 characters long for security. "
            "Use a strong random string."
        )
    return secret


class ConfigurationError(Exception):
    """Raised when configuration is invalid"""
    pass


# Pydantic models for authentication
class TokenData(BaseModel):
    """JWT token payload"""
    user_id: str
    username: str
    email: str
    role: str
    scopes: List[str] = []
    exp: Optional[datetime] = None
    iat: Optional[datetime] = None


class UserCreate(BaseModel):
    """User creation request"""
    username: str = Field(..., min_length=3, max_length=50, pattern=r'^[a-zA-Z][a-zA-Z0-9_]{2,49}$')
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    role: str = Field(default='participant')
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r'[A-Z]', v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r'[a-z]', v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r'\d', v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserUpdate(BaseModel):
    """User update request"""
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8, max_length=128)
    disabled: Optional[bool] = None


class UserResponse(BaseModel):
    """User response (excludes sensitive data)"""
    id: str
    username: str
    email: str
    role: str
    disabled: bool
    created_at: Optional[datetime]
    last_login_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Token response"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class LoginRequest(BaseModel):
    """Login request"""
    username: str
    password: str


class AuthService:
    """
    Authentication and authorization service for the Third Place platform
    """
    
    def __init__(self, db: Session):
        self.db = db
        self.security = HTTPBearer(auto_error=False)
        self.user_repo = UserRepository(db)
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plain password against a hashed password"""
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except Exception:
            return False
    
    def get_password_hash(self, password: str) -> str:
        """Hash a password"""
        return pwd_context.hash(password)
    
    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """
        Authenticate a user by username and password
        Returns User if successful, None otherwise
        """
        user = self.user_repo.get_by_username(username)
        if not user:
            # Use constant-time comparison to prevent timing attacks
            pwd_context.verify("dummy", "dummy")
            return None
        
        if not self.verify_password(password, user.hashed_password):
            return None
        
        if user.disabled:
            return None
        
        return user
    
    def create_access_token(
        self,
        user: User,
        expires_delta: Optional[timedelta] = None
    ) -> str:
        """Create a JWT access token"""
        to_encode = {
            "sub": str(user.id),
            "username": user.username,
            "email": user.email,
            "role": user.role,
            "iat": datetime.now(timezone.utc),
        }
        
        if expires_delta:
            expire = datetime.now(timezone.utc) + expires_delta
        else:
            expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        
        to_encode["exp"] = expire
        
        try:
            encoded_jwt = jwt.encode(to_encode, get_jwt_secret(), algorithm=ALGORITHM)
            return encoded_jwt
        except Exception as e:
            raise TokenError(f"Failed to create access token: {e}")
    
    def create_refresh_token(self, user_id: str) -> tuple[str, RefreshToken]:
        """
        Create a refresh token and store in database
        Returns (token_string, RefreshToken_record)
        """
        # Generate secure random token
        token = secrets.token_urlsafe(64)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        expires_at = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        refresh_token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at
        )
        
        self.db.add(refresh_token)
        self.db.commit()
        self.db.refresh(refresh_token)
        
        return token, refresh_token
    
    def decode_token(self, token: str) -> Optional[TokenData]:
        """Decode a JWT token and return the payload"""
        try:
            payload = jwt.decode(token, get_jwt_secret(), algorithms=[ALGORITHM])
            return TokenData(**payload)
        except jwt.ExpiredSignatureError:
            raise TokenError("Token has expired")
        except jwt.JWTError as e:
            raise TokenError(f"Invalid token: {e}")
    
    def validate_refresh_token(self, token: str) -> Optional[RefreshToken]:
        """Validate refresh token against database"""
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        refresh_token = self.db.query(RefreshToken).filter(
            RefreshToken.token_hash == token_hash,
            RefreshToken.revoked == False,
            RefreshToken.expires_at > datetime.now(timezone.utc)
        ).first()
        
        return refresh_token
    
    def revoke_refresh_token(self, token: str) -> bool:
        """Revoke a refresh token"""
        refresh_token = self.validate_refresh_token(token)
        if refresh_token:
            refresh_token.revoked = True
            self.db.commit()
            return True
        return False
    
    def revoke_all_user_tokens(self, user_id: str) -> int:
        """Revoke all refresh tokens for a user"""
        result = self.db.query(RefreshToken).filter(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked == False
        ).update({"revoked": True})
        self.db.commit()
        return result
    
    def get_current_user(
        self,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))
    ) -> User:
        """
        Get the current authenticated user from JWT token
        """
        if not credentials:
            raise AuthenticationError(
                "Authentication required",
                error_code="AUTH_MISSING"
            )
        
        token = credentials.credentials
        
        try:
            token_data = self.decode_token(token)
        except TokenError as e:
            raise AuthenticationError(
                str(e),
                error_code="AUTH_INVALID_TOKEN"
            )
        
        user = self.user_repo.get(token_data.user_id)
        if not user:
            raise AuthenticationError(
                "User not found",
                error_code="AUTH_USER_NOT_FOUND"
            )
        
        if user.disabled:
            raise AuthenticationError(
                "User account is disabled",
                error_code="AUTH_USER_DISABLED"
            )
        
        return user
    
    def create_user(
        self,
        username: str,
        email: str,
        password: str,
        role: str = 'participant'
    ) -> User:
        """
        Create a new user with validation
        """
        # Check if username exists
        existing = self.user_repo.get_by_username(username)
        if existing:
            raise ValidationError("Username already exists")
        
        # Check if email exists
        existing = self.user_repo.get_by_email(email)
        if existing:
            raise ValidationError("Email already registered")
        
        # Validate role
        valid_roles = ['admin', 'platform_operator', 'space_owner', 'steward', 'participant']
        if role not in valid_roles:
            raise ValidationError(f"Invalid role. Must be one of: {valid_roles}")
        
        # Create user
        user_data = {
            "username": username,
            "email": email,
            "hashed_password": self.get_password_hash(password),
            "role": role,
            "disabled": False
        }
        
        return self.user_repo.create(user_data)
    
    def update_user(self, user_id: str, update_data: UserUpdate) -> User:
        """Update user information"""
        user = self.user_repo.get_or_raise(user_id)
        
        update_dict = update_data.model_dump(exclude_unset=True)
        
        if 'email' in update_dict and update_dict['email']:
            # Check email not in use
            existing = self.user_repo.get_by_email(update_dict['email'])
            if existing and str(existing.id) != user_id:
                raise ValidationError("Email already registered")
            user.email = update_dict['email']
        
        if 'password' in update_dict and update_dict['password']:
            user.hashed_password = self.get_password_hash(update_dict['password'])
        
        if 'disabled' in update_dict:
            user.disabled = update_dict['disabled']
        
        self.db.commit()
        self.db.refresh(user)
        return user
    
    def login(self, username: str, password: str, request: Optional[Request] = None) -> TokenResponse:
        """
        Authenticate user and return tokens
        """
        user = self.authenticate_user(username, password)
        
        if not user:
            raise AuthenticationError(
                "Invalid username or password",
                error_code="AUTH_INVALID_CREDENTIALS"
            )
        
        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        self.db.commit()
        
        # Create tokens
        access_token = self.create_access_token(user)
        refresh_token, _ = self.create_refresh_token(str(user.id))
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
    
    def logout(self, refresh_token: str) -> bool:
        """Logout user by revoking refresh token"""
        return self.revoke_refresh_token(refresh_token)
    
    def refresh_access_token(self, refresh_token_str: str) -> TokenResponse:
        """
        Refresh access token using refresh token
        Implements token rotation - old refresh token is revoked
        """
        # Validate refresh token
        token_record = self.validate_refresh_token(refresh_token_str)
        
        if not token_record:
            raise AuthenticationError(
                "Invalid or expired refresh token",
                error_code="AUTH_INVALID_REFRESH_TOKEN"
            )
        
        # Get user
        user = self.user_repo.get(str(token_record.user_id))
        if not user or user.disabled:
            raise AuthenticationError(
                "User not found or disabled",
                error_code="AUTH_USER_NOT_FOUND"
            )
        
        # Revoke old refresh token (token rotation)
        token_record.revoked = True
        token_record.used_at = datetime.now(timezone.utc)
        
        # Create new tokens
        access_token = self.create_access_token(user)
        new_refresh_token, _ = self.create_refresh_token(str(user.id))
        
        self.db.commit()
        
        return TokenResponse(
            access_token=access_token,
            refresh_token=new_refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )


# Role checker dependencies
class RoleChecker:
    """Authorization checker based on user roles"""
    
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles
    
    def __call__(self, current_user: User = Depends(AuthService(None).get_current_user)) -> User:
        if current_user.role not in self.allowed_roles:
            raise AuthorizationError(
                f"Required role: {', '.join(self.allowed_roles)}. Your role: {current_user.role}",
                error_code="AUTH_INSUFFICIENT_ROLE"
            )
        return current_user


# Predefined role checkers
admin_only = RoleChecker(["admin"])
admin_or_platform_operator = RoleChecker(["admin", "platform_operator"])
admin_or_space_owner = RoleChecker(["admin", "space_owner"])
admin_or_steward = RoleChecker(["admin", "steward"])


class PermissionChecker:
    """Fine-grained permission checker"""
    
    def __init__(self, permission: str):
        self.permission = permission
    
    def __call__(
        self,
        current_user: User = Depends(AuthService(None).get_current_user)
    ) -> User:
        if self._has_permission(current_user, self.permission):
            return current_user
        else:
            raise AuthorizationError(
                f"Permission '{self.permission}' required",
                error_code="AUTH_INSUFFICIENT_PERMISSION"
            )
    
    def _has_permission(self, user: User, permission: str) -> bool:
        """Check if user has a specific permission"""
        role_permissions = {
            "admin": [
                "read_anything", "write_anything", "delete_anything",
                "manage_users", "manage_spaces", "manage_policies",
                "view_reports", "process_claims", "emergency_revocation"
            ],
            "platform_operator": [
                "read_anything", "manage_policies",
                "view_reports", "process_claims"
            ],
            "space_owner": [
                "read_own_spaces", "create_envelopes_for_own_spaces",
                "read_own_envelopes", "manage_own_stewards", "manage_own_spaces",
                "view_own_reports"
            ],
            "steward": [
                "read_assigned_envelopes", "create_incident_reports",
                "check_in_participants", "manage_attendance"
            ],
            "participant": [
                "view_own_bookings", "update_own_profile"
            ]
        }
        
        user_permissions = role_permissions.get(user.role, [])
        return permission in user_permissions


# Common permission checkers
can_read_envelopes = PermissionChecker("read_own_envelopes")
can_create_envelopes = PermissionChecker("create_envelopes_for_own_spaces")
can_manage_spaces = PermissionChecker("manage_own_spaces")
can_process_claims = PermissionChecker("process_claims")
can_view_reports = PermissionChecker("view_reports")


# Dependency for getting auth service
def get_auth_service(db: Session = Depends(lambda: None)) -> AuthService:
    """Get auth service instance (for dependency injection)"""
    return AuthService(db)


# Utility functions for API routes
def get_current_active_user(
    current_user: User = Depends(AuthService(None).get_current_user)
) -> User:
    """Get the current active user"""
    if current_user.disabled:
        raise AuthenticationError("Inactive user", error_code="AUTH_USER_DISABLED")
    return current_user


def get_current_admin_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Get current user with admin role"""
    if current_user.role != "admin":
        raise AuthorizationError(
            "Admin privileges required",
            error_code="AUTH_INSUFFICIENT_ROLE"
        )
    return current_user


def get_current_platform_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Get current user with platform operator role"""
    if current_user.role not in ["admin", "platform_operator"]:
        raise AuthorizationError(
            "Platform operator privileges required",
            error_code="AUTH_INSUFFICIENT_ROLE"
        )
    return current_user


def get_current_space_owner_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Get current user with space owner role"""
    if current_user.role not in ["admin", "space_owner"]:
        raise AuthorizationError(
            "Space owner privileges required",
            error_code="AUTH_INSUFFICIENT_ROLE"
        )
    return current_user


def get_current_steward_user(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Get current user with steward role"""
    if current_user.role not in ["admin", "steward"]:
        raise AuthorizationError(
            "Steward privileges required",
            error_code="AUTH_INSUFFICIENT_ROLE"
        )
    return current_user
