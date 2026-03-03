from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, Any


# Create limiter instance
limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """
    Custom handler for rate limit exceeded errors
    """
    return JSONResponse(
        status_code=429,
        content={
            "error": "Rate limit exceeded",
            "detail": str(exc.detail),
            "retry_after": getattr(exc, 'retry_after', None)
        }
    )


def setup_rate_limiting(app):
    """
    Setup rate limiting for the FastAPI application
    """
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)


# Rate limit presets for different use cases
class RateLimitPresets:
    """
    Preset rate limits for different scenarios
    """

    # Strict limits for authentication endpoints
    AUTH_LIMIT = "5/minute"  # 5 attempts per minute
    LOGIN_LIMIT = "10/minute"  # 10 login attempts per minute

    # Standard API limits
    STANDARD_LIMIT = "100/minute"  # 100 requests per minute
    STANDARD_HOUR_LIMIT = "1000/hour"  # 1000 requests per hour

    # Heavy operations
    HEAVY_OPERATION_LIMIT = "10/minute"  # 10 heavy operations per minute
    ENVELOPE_CREATION_LIMIT = "20/minute"  # 20 envelope creations per minute

    # Read-heavy endpoints
    READ_LIMIT = "200/minute"  # 200 read operations per minute

    # Critical operations (claims, incidents)
    CRITICAL_OPERATION_LIMIT = "30/minute"  # 30 operations per minute


def get_limit_by_endpoint(endpoint_path: str) -> str:
    """
    Get appropriate rate limit based on endpoint path
    """
    # Authentication endpoints - stricter limits
    if any(pattern in endpoint_path for pattern in ['/auth', '/login', '/token']):
        return RateLimitPresets.AUTH_LIMIT

    # Heavy operations
    if any(pattern in endpoint_path for pattern in ['/ial/envelopes', '/claims']):
        return RateLimitPresets.HEAVY_OPERATION_LIMIT

    # Read operations
    if endpoint_path.endswith('/verify') or 'get' in endpoint_path.lower():
        return RateLimitPresets.READ_LIMIT

    # Default standard limit
    return RateLimitPresets.STANDARD_LIMIT
