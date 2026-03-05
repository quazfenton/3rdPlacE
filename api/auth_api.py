"""
Authentication API Router

Provides endpoints for:
- User registration
- Login/logout
- Token refresh
- User management
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from config.database import get_db
from services.auth_service import (
    AuthService, UserResponse, TokenResponse, LoginRequest,
    UserCreate, UserUpdate, get_current_active_user,
    admin_only, admin_or_platform_operator
)
from models.insurance_models import User
from middleware.rate_limiter import login_rate_limit, auth_rate_limit, standard_rate_limit
from utils.exceptions import AuthenticationError, AuthorizationError, ValidationError

logger = logging.getLogger(__name__)

router = APIRouter()


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    """Dependency to get auth service"""
    return AuthService(db)


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Authentication"],
    summary="Register a new user",
    description="Create a new user account with the specified role."
)
@auth_rate_limit
async def register(
    user_data: UserCreate,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_db)
):
    """
    Register a new user
    
    **Roles:**
    - `participant`: Default role for regular users
    - `steward`: Can manage events and check-ins
    - `space_owner`: Can create and manage spaces
    - `platform_operator`: Can manage policies and claims
    - `admin`: Full system access
    """
    client_ip = request.client.host if request.client else None
    
    try:
        user = auth_service.create_user(
            username=user_data.username,
            email=user_data.email,
            password=user_data.password,
            role=user_data.role
        )
        
        # Log user creation
        from services.audit_service import AuditService
        AuditService.log_user_created(
            db, str(user.id), user.username, user.role,
            ip_address=client_ip
        )
        
        logger.info(f"New user registered: {user.username} ({user.role})")
        
        return user
        
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.message),
            error_code="VALIDATION_ERROR"
        )


@router.post(
    "/login",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Login",
    description="Authenticate with username and password to obtain access and refresh tokens."
)
@login_rate_limit
async def login(
    login_data: LoginRequest,
    request: Request,
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_db)
):
    """
    Login and obtain tokens
    
    Returns:
    - `access_token`: JWT token for API access (expires in 30 minutes)
    - `refresh_token`: Token for obtaining new access tokens (expires in 7 days)
    - `token_type`: Always "bearer"
    - `expires_in`: Access token lifetime in seconds
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent", "unknown")
    
    try:
        tokens = auth_service.login(
            username=login_data.username,
            password=login_data.password,
            request=request
        )
        
        # Log successful login
        user = auth_service.authenticate_user(login_data.username, login_data.password)
        if user:
            from services.audit_service import AuditService
            AuditService.log_user_login(
                db, str(user.id), user.username,
                ip_address=client_ip, user_agent=user_agent
            )
        
        return tokens
        
    except AuthenticationError as e:
        logger.warning(f"Failed login attempt for: {login_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
            error_code=e.error_code,
            headers={"WWW-Authenticate": "Bearer"}
        )


@router.post(
    "/logout",
    tags=["Authentication"],
    summary="Logout",
    description="Logout by invalidating the refresh token."
)
@standard_rate_limit
async def logout(
    request: Request,
    refresh_token: str,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Logout and invalidate refresh token
    
    The access token will still be valid until it expires naturally,
    but the refresh token will be invalidated.
    """
    success = auth_service.logout(refresh_token)
    
    if success:
        return {"message": "Successfully logged out"}
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or already revoked refresh token"
        )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    tags=["Authentication"],
    summary="Refresh token",
    description="Obtain new access and refresh tokens using a valid refresh token."
)
@auth_rate_limit
async def refresh_token(
    request: Request,
    refresh_token: str,
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Refresh access token
    
    Implements token rotation - the old refresh token is invalidated
    and a new one is issued.
    """
    try:
        return auth_service.refresh_access_token(refresh_token)
    except AuthenticationError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=e.message,
            error_code=e.error_code
        )


@router.get(
    "/me",
    response_model=UserResponse,
    tags=["Authentication"],
    summary="Get current user",
    description="Get information about the currently authenticated user."
)
@standard_rate_limit
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """
    Get current user information
    
    Returns the authenticated user's profile without sensitive data.
    """
    return current_user


@router.put(
    "/me",
    response_model=UserResponse,
    tags=["Authentication"],
    summary="Update current user",
    description="Update the current user's profile."
)
@standard_rate_limit
async def update_current_user(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_db)
):
    """
    Update current user profile
    
    Can update:
    - Email address
    - Password
    - Disabled status (admin only)
    """
    try:
        updated_user = auth_service.update_user(
            user_id=str(current_user.id),
            update_data=user_data
        )
        return updated_user
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.message)
        )


@router.get(
    "/users",
    response_model=List[UserResponse],
    tags=["User Management"],
    summary="List users",
    description="List all users (admin only)."
)
@standard_rate_limit
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db)
):
    """
    List all users (admin only)
    
    Supports pagination with skip and limit parameters.
    """
    users = db.query(User).offset(skip).limit(limit).all()
    return users


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    tags=["User Management"],
    summary="Get user by ID",
    description="Get a specific user by ID (admin only)."
)
@standard_rate_limit
async def get_user(
    user_id: str,
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db)
):
    """
    Get user by ID (admin only)
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    return user


@router.post(
    "/users/{user_id}/disable",
    tags=["User Management"],
    summary="Disable user",
    description="Disable a user account (admin only)."
)
@standard_rate_limit
async def disable_user(
    user_id: str,
    reason: Optional[str] = None,
    current_user: User = Depends(admin_only),
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_db)
):
    """
    Disable a user account (admin only)
    
    Disabled users cannot login or access the API.
    """
    try:
        from services.audit_service import AuditService
        
        user = auth_service.update_user(
            user_id=user_id,
            update_data=UserUpdate(disabled=True)
        )
        
        # Log the action
        AuditService.log_event(
            db,
            event_type="user_disabled",
            entity_type="user",
            entity_id=user_id,
            action="disable",
            actor_id=str(current_user.id),
            reason=reason
        )
        
        return {"message": f"User {user.username} has been disabled"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/users/{user_id}/enable",
    tags=["User Management"],
    summary="Enable user",
    description="Enable a previously disabled user account (admin only)."
)
@standard_rate_limit
async def enable_user(
    user_id: str,
    current_user: User = Depends(admin_only),
    auth_service: AuthService = Depends(get_auth_service),
    db: Session = Depends(get_db)
):
    """
    Enable a user account (admin only)
    """
    try:
        user = auth_service.update_user(
            user_id=user_id,
            update_data=UserUpdate(disabled=False)
        )
        
        return {"message": f"User {user.username} has been enabled"}
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )


@router.post(
    "/emergency-revoke-tokens",
    tags=["Authentication"],
    summary="Emergency token revocation",
    description="Revoke all refresh tokens for the current user (kill switch)."
)
async def emergency_revoke_tokens(
    current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service)
):
    """
    Emergency token revocation
    
    Revokes ALL refresh tokens for the current user.
    Use this if you suspect your account has been compromised.
    """
    revoked_count = auth_service.revoke_all_user_tokens(str(current_user.id))
    
    return {
        "message": f"Revoked {revoked_count} refresh tokens",
        "action": "All sessions have been terminated. Please log in again."
    }
