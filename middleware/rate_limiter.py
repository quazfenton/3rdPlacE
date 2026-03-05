"""
Rate Limiting Middleware for Third Place Platform

Provides rate limiting with:
- Per-endpoint limits
- Per-user limits
- IP-based limits
- Custom limit decorators
"""
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from functools import wraps
from typing import Optional, Callable, Dict, Any
import logging

logger = logging.getLogger(__name__)


# Create limiter instance with Redis support option
def get_key_func():
    """
    Get rate limit key function.
    Uses X-Forwarded-For header for proxy-aware IP detection.
    """
    def key_func(request: Request) -> str:
        # Try to get real IP from headers (for proxied requests)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take the first IP in the chain
            return forwarded_for.split(",")[0].strip()
        
        # Fall back to direct client IP
        if request.client:
            return request.client.host
        
        return "unknown"
    
    return key_func


limiter = Limiter(key_func=get_key_func())


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors
    """
    # Get retry-after from exception
    retry_after = getattr(exc, 'retry_after', None)
    
    logger.warning(
        f"Rate limit exceeded: {request.method} {request.url.path}"
        f" from {request.client.host if request.client else 'unknown'}"
    )
    
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": str(exc.detail),
            "retry_after": retry_after,
            "error_code": "RATE_LIMIT_EXCEEDED"
        },
        headers={"Retry-After": str(retry_after)} if retry_after else {}
    )


def setup_rate_limiting(app) -> None:
    """
    Setup rate limiting for the FastAPI application
    
    Args:
        app: FastAPI application instance
    """
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
    logger.info("Rate limiting enabled")


# Rate limit presets for different use cases
class RateLimitPresets:
    """
    Preset rate limits for different scenarios
    """
    
    # Authentication endpoints - strict limits to prevent brute force
    AUTH_LIMIT = "5/minute"
    LOGIN_LIMIT = "10/minute"
    REGISTER_LIMIT = "5/hour"
    PASSWORD_RESET_LIMIT = "3/hour"
    
    # Standard API limits
    STANDARD_LIMIT = "100/minute"
    STANDARD_HOUR_LIMIT = "1000/hour"
    
    # Heavy operations
    HEAVY_OPERATION_LIMIT = "10/minute"
    ENVELOPE_CREATION_LIMIT = "20/minute"
    CLAIM_SUBMISSION_LIMIT = "5/hour"
    
    # Read-heavy endpoints
    READ_LIMIT = "200/minute"
    VERIFY_LIMIT = "300/minute"
    
    # Critical operations
    CRITICAL_OPERATION_LIMIT = "30/minute"
    EMERGENCY_REVOCATION_LIMIT = "3/hour"
    
    # WebSocket/Streaming
    WS_CONNECT_LIMIT = "10/minute"


# Decorator functions for easy rate limiting
def rate_limit(
    limit_string: str,
    key_func: Optional[Callable] = None,
    exempt_when: Optional[Callable] = None
):
    """
    Decorator to apply rate limiting to an endpoint
    
    Args:
        limit_string: Rate limit string (e.g., "10/minute")
        key_func: Optional custom key function
        exempt_when: Optional function to check if request is exempt
    
    Example:
        @router.post("/login")
        @rate_limit(RateLimitPresets.LOGIN_LIMIT)
        async def login(...):
            ...
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)
        
        # Apply slowapi limiter
        return limiter.limit(
            limit_string,
            key_func=key_func,
            exempt_when=exempt_when
        )(wrapper)
    
    return decorator


# Pre-configured decorators for common use cases
def auth_rate_limit(func: Callable) -> Callable:
    """Rate limit for authentication endpoints"""
    return limiter.limit(RateLimitPresets.AUTH_LIMIT)(func)


def login_rate_limit(func: Callable) -> Callable:
    """Rate limit for login endpoint"""
    return limiter.limit(RateLimitPresets.LOGIN_LIMIT)(func)


def standard_rate_limit(func: Callable) -> Callable:
    """Standard rate limit for most endpoints"""
    return limiter.limit(RateLimitPresets.STANDARD_LIMIT)(func)


def heavy_operation_rate_limit(func: Callable) -> Callable:
    """Rate limit for heavy operations"""
    return limiter.limit(RateLimitPresets.HEAVY_OPERATION_LIMIT)(func)


def read_rate_limit(func: Callable) -> Callable:
    """Rate limit for read operations"""
    return limiter.limit(RateLimitPresets.READ_LIMIT)(func)


def get_limit_by_endpoint(endpoint_path: str) -> str:
    """
    Get appropriate rate limit based on endpoint path
    
    Args:
        endpoint_path: The API endpoint path
    
    Returns:
        Rate limit string
    """
    path_lower = endpoint_path.lower()
    
    # Authentication endpoints - stricter limits
    if any(pattern in path_lower for pattern in ['/auth', '/login', '/token', '/register']):
        return RateLimitPresets.AUTH_LIMIT
    
    # Password reset
    if 'password' in path_lower and ('reset' in path_lower or 'recover' in path_lower):
        return RateLimitPresets.PASSWORD_RESET_LIMIT
    
    # Heavy operations
    if any(pattern in path_lower for pattern in ['/ial/envelopes', '/claims']):
        if 'get' in path_lower or 'verify' in path_lower:
            return RateLimitPresets.READ_LIMIT
        return RateLimitPresets.HEAVY_OPERATION_LIMIT
    
    # Read operations
    if path_lower.endswith('/verify') or 'get' in path_lower:
        return RateLimitPresets.READ_LIMIT
    
    # Default standard limit
    return RateLimitPresets.STANDARD_LIMIT


class RateLimitStats:
    """
    Track rate limit statistics for monitoring
    """
    
    def __init__(self):
        self.requests: Dict[str, int] = {}
        self.limited: Dict[str, int] = {}
    
    def record_request(self, key: str) -> None:
        """Record a request"""
        self.requests[key] = self.requests.get(key, 0) + 1
    
    def record_limited(self, key: str) -> None:
        """Record a rate-limited request"""
        self.limited[key] = self.limited.get(key, 0) + 1
    
    def get_stats(self) -> Dict[str, Any]:
        """Get rate limit statistics"""
        return {
            "total_requests": sum(self.requests.values()),
            "total_limited": sum(self.limited.values()),
            "by_key": {
                key: {
                    "requests": self.requests.get(key, 0),
                    "limited": self.limited.get(key, 0)
                }
                for key in set(self.requests.keys()) | set(self.limited.keys())
            }
        }


# Global stats instance (in production, use Redis)
rate_limit_stats = RateLimitStats()
