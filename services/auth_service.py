from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import jwt
from jose.exceptions import JWTError
import hashlib
import secrets
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel


# Password hashing context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT settings
import os
SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("JWT_SECRET_KEY environment variable is required but not set")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30


class TokenData(BaseModel):
    username: Optional[str] = None
    scopes: list = []


class User(BaseModel):
    id: str
    username: str
    email: str
    role: str  # admin, steward, space_owner, platform_operator
    disabled: bool = False


class AuthService:
    """
    Authentication and authorization service for the Third Place platform
    """
    
    def __init__(self):
        self.security = HTTPBearer()
        self.users_db = {}  # In production, this would be a database
        self.tokens_blacklist = set()  # Track invalidated tokens
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a plain password against a hashed password
        """
        return pwd_context.verify(plain_password, hashed_password)
    
    def get_password_hash(self, password: str) -> str:
        """
        Hash a password
        """
        return pwd_context.hash(password)
    
    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """
        Authenticate a user by username and password
        """
        user = self.get_user(username)
        if not user or not self.verify_password(password, user.get("hashed_password", "")):
            return None
        return User(**user)
    
    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None) -> str:
        """
        Create a JWT access token
        """
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=15)
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    
    def decode_token(self, token: str) -> Optional[TokenData]:
        """
        Decode a JWT token and return the payload
        """
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            username: str = payload.get("sub")
            if username is None:
                return None
            scopes = payload.get("scopes", [])
            return TokenData(username=username, scopes=scopes)
        except JWTError:
            return None
    
    def get_current_user(
        self,
        credentials: HTTPAuthorizationCredentials = Depends(HTTPBearer())
    ) -> User:
        """
        Get the current authenticated user
        """
        token = credentials.credentials

        # Check if token is blacklisted
        if token_manager.is_token_blacklisted(token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token_data = self.decode_token(token)

        if token_data is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )

        user = self.get_user(username=token_data.username)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if user.get("disabled", False):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Inactive user",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return User(**user)
    
    def get_current_active_user(self, current_user: User = Depends(get_current_user)) -> User:
        """
        Get the current active user
        """
        if current_user.disabled:
            raise HTTPException(status_code=400, detail="Inactive user")
        return current_user
    
    def get_user(self, username: str) -> Optional[dict]:
        """
        Retrieve a user from the database
        In production, this would query a real database
        """
        # This is a mock implementation - in production use a real database
        return self.users_db.get(username)
    
    def create_user(self, username: str, email: str, password: str, role: str) -> User:
        """
        Create a new user
        """
        if username in self.users_db:
            raise ValueError("Username already exists")
        
        hashed_password = self.get_password_hash(password)
        
        user_data = {
            "id": secrets.token_hex(8),  # Simple ID generation
            "username": username,
            "email": email,
            "role": role,
            "hashed_password": hashed_password,
            "disabled": False
        }
        
        self.users_db[username] = user_data
        return User(**user_data)


class RoleChecker:
    """
    Authorization checker based on user roles
    """

    def __init__(self, allowed_roles: list):
        self.allowed_roles = allowed_roles

    def __call__(self, user: User = Depends(get_current_user)):
        if user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Operation not permitted"
            )
        return user


# Predefined role checkers
admin_only = RoleChecker(["admin"])
admin_or_platform_operator = RoleChecker(["admin", "platform_operator"])
admin_or_space_owner = RoleChecker(["admin", "space_owner"])
admin_or_steward = RoleChecker(["admin", "steward"])


class PermissionChecker:
    """
    Fine-grained permission checker based on resource ownership and permissions
    """
    
    def __init__(self, permission: str):
        self.permission = permission
    
    def __call__(
        self, 
        user: User = Depends(AuthService().get_current_user),
        db=None  # Database session would be injected here
    ):
        # This is where you'd implement fine-grained permission checks
        # based on the user's role, resource ownership, etc.
        
        # For now, we'll implement a simple permission model
        if self._has_permission(user, self.permission):
            return user
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission {self.permission} required"
            )
    
    def _has_permission(self, user: User, permission: str) -> bool:
        """
        Check if user has a specific permission
        This is a simplified implementation - in production, 
        this would check against a permissions database
        """
        # Define permission mappings
        role_permissions = {
            "admin": [
                "read_anything", "write_anything", "delete_anything",
                "manage_users", "manage_spaces", "manage_policies",
                "view_reports", "process_claims"
            ],
            "platform_operator": [
                "read_anything", "manage_policies",
                "view_reports", "process_claims"
            ],
            "space_owner": [
                "read_own_spaces", "create_envelopes_for_own_spaces",
                "read_own_envelopes", "manage_own_stewards", "manage_own_spaces"
            ],
            "steward": [
                "read_assigned_envelopes", "create_incident_reports",
                "check_in_participants"
            ],
            "participant": [
                "view_own_bookings", "update_own_profile"
            ]
        }
        
        user_permissions = role_permissions.get(user.role, [])
        return self.permission in user_permissions


# Common permission checkers
can_read_envelopes = PermissionChecker("read_own_envelopes")
can_create_envelopes = PermissionChecker("create_envelopes_for_own_spaces")
can_manage_spaces = PermissionChecker("manage_own_spaces")
can_process_claims = PermissionChecker("process_claims")
can_view_reports = PermissionChecker("view_reports")


class TokenManager:
    """
    Manager for handling token lifecycle (creation, validation, revocation)
    """
    
    def __init__(self):
        self.blacklisted_tokens = set()
    
    def blacklist_token(self, token: str):
        """
        Add a token to the blacklist (for logout functionality)
        """
        self.blacklisted_tokens.add(hashlib.sha256(token.encode()).hexdigest())
    
    def is_token_blacklisted(self, token: str) -> bool:
        """
        Check if a token is blacklisted
        """
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return token_hash in self.blacklisted_tokens


# Initialize services
auth_service = AuthService()
token_manager = TokenManager()


# Utility functions for API routes
def get_current_admin_user(current_user: User = Depends(auth_service.get_current_user)):
    """
    Dependency to get current user with admin role
    """
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required"
        )
    return current_user


def get_current_platform_user(current_user: User = Depends(auth_service.get_current_user)):
    """
    Dependency to get current user with platform operator role
    """
    if current_user.role not in ["admin", "platform_operator"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform operator privileges required"
        )
    return current_user


def get_current_space_owner_user(current_user: User = Depends(auth_service.get_current_user)):
    """
    Dependency to get current user with space owner role
    """
    if current_user.role not in ["admin", "space_owner"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Space owner privileges required"
        )
    return current_user


def get_current_steward_user(current_user: User = Depends(auth_service.get_current_user)):
    """
    Dependency to get current user with steward role
    """
    if current_user.role not in ["admin", "steward"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Steward privileges required"
        )
    return current_user