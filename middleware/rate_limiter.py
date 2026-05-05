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
from fastapi import Request
from fastapi.responses import JSONResponse
from functools import wraps
from typing import Optional, Callable, Dict, Any
import logging

logger = logging.getLogger(__name__)


# =============================================================================
# Rate Limit Key Function
# =============================================================================

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


# Create limiter instance
limiter = Limiter(key_func=get_key_func())


# =============================================================================
# Rate Limit Exceeded Handler
# =============================================================================

def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors
    """
    # Get retry-after from exception
    retry_after = getattr(exc, 'retry_after', None)

    logger.warning(
        f"Rate limit exceeded: {request.method} {request.url.path}"
        f" from {request.client.host if request.client else 'unknown'}"
        f" (retry after: {retry_after}s)"
    )

    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": str(exc.detail),
            "retry_after_seconds": retry_after,
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


# =============================================================================
# Rate Limit Presets
# =============================================================================

class RateLimitPresets:
    """
    Preset rate limits for different scenarios
    
    All limits are per IP address unless otherwise specified.
    """

    # Authentication endpoints - strict limits to prevent brute force
    AUTH_LIMIT = "5/minute"
    LOGIN_LIMIT = "10/minute"
    REGISTER_LIMIT = "5/hour"
    PASSWORD_RESET_LIMIT = "3/hour"
    TOKEN_REFRESH_LIMIT = "30/minute"

    # Standard API limits
    STANDARD_LIMIT = "100/minute"
    STANDARD_HOUR_LIMIT = "1000/hour"

    # Heavy operations - stricter limits
    HEAVY_OPERATION_LIMIT = "10/minute"
    ENVELOPE_CREATION_LIMIT = "20/minute"
    ACCESS_GRANT_CREATION_LIMIT = "30/minute"

    # Critical operations - VERY strict limits
    VOID_ENVELOPE_LIMIT = "10/hour"
    EMERGENCY_REVOCATION_LIMIT = "3/hour"
    CLAIM_SUBMISSION_LIMIT = "5/hour"

    # Read-heavy endpoints - more permissive
    READ_LIMIT = "200/minute"
    VERIFY_LIMIT = "300/minute"
    LIST_LIMIT = "100/minute"

    # WebSocket/Streaming
    WS_CONNECT_LIMIT = "10/minute"


# =============================================================================
# Rate Limit Decorators
# =============================================================================

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


def register_rate_limit(func: Callable) -> Callable:
    """Rate limit for registration endpoint"""
    return limiter.limit(RateLimitPresets.REGISTER_LIMIT)(func)


def standard_rate_limit(func: Callable) -> Callable:
    """Standard rate limit for most endpoints"""
    return limiter.limit(RateLimitPresets.STANDARD_LIMIT)(func)


def heavy_operation_rate_limit(func: Callable) -> Callable:
    """Rate limit for heavy operations"""
    return limiter.limit(RateLimitPresets.HEAVY_OPERATION_LIMIT)(func)


def read_rate_limit(func: Callable) -> Callable:
    """Rate limit for read operations"""
    return limiter.limit(RateLimitPresets.READ_LIMIT)(func)


def verify_rate_limit(func: Callable) -> Callable:
    """Rate limit for verify operations"""
    return limiter.limit(RateLimitPresets.VERIFY_LIMIT)(func)


def void_envelope_rate_limit(func: Callable) -> Callable:
    """Strict rate limit for voiding envelopes"""
    return limiter.limit(RateLimitPresets.VOID_ENVELOPE_LIMIT)(func)


def emergency_revocation_rate_limit(func: Callable) -> Callable:
    """Very strict rate limit for emergency revocation"""
    return limiter.limit(RateLimitPresets.EMERGENCY_REVOCATION_LIMIT)(func)


# =============================================================================
# Rate Limit Stats
# =============================================================================

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
