"""
Security Headers Middleware for Third Place Platform

Adds security headers to all responses:
- X-Content-Type-Options: nosniff
- X-Frame-Options: DENY
- X-XSS-Protection: 1; mode=block
- Strict-Transport-Security: max-age=31536000; includeSubDomains
- Content-Security-Policy: default-src 'self'
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: geolocation=(), microphone=(), camera=()
- Cache-Control: no-store (for sensitive endpoints)
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from typing import Callable, Awaitable, List, Optional
import logging

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Middleware to add security headers to all responses
    
    Headers added:
    - X-Content-Type-Options: Prevents MIME type sniffing
    - X-Frame-Options: Prevents clickjacking
    - X-XSS-Protection: XSS filter (legacy browsers)
    - Strict-Transport-Security: Forces HTTPS
    - Content-Security-Policy: Restricts resource loading
    - Referrer-Policy: Controls referrer information
    - Permissions-Policy: Disables browser features
    - Cache-Control: Prevents caching of sensitive data
    """
    
    def __init__(
        self,
        app,
        hsts_max_age: int = 31536000,  # 1 year
        hsts_include_subdomains: bool = True,
        csp_directives: Optional[str] = None,
        exempt_paths: Optional[List[str]] = None
    ):
        """
        Initialize security headers middleware
        
        Args:
            app: FastAPI application
            hsts_max_age: HSTS max-age in seconds
            hsts_include_subdomains: Include includeSubDomains in HSTS
            csp_directives: Custom CSP directives (default: restrictive default)
            exempt_paths: Paths to exempt from security headers (e.g., static files)
        """
        super().__init__(app)
        
        self.hsts_max_age = hsts_max_age
        self.hsts_include_subdomains = hsts_include_subdomains
        self.csp_directives = csp_directives or self._default_csp()
        self.exempt_paths = exempt_paths or ["/static", "/docs", "/redoc"]
    
    def _default_csp(self) -> str:
        """Default Content Security Policy"""
        return (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' cdnjs.cloudflare.com; "
            "font-src 'self' fonts.gstatic.com; "
            "img-src 'self' data: https:; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
    
    def _should_exempt(self, path: str) -> bool:
        """Check if path should be exempt from security headers"""
        for exempt in self.exempt_paths:
            if path.startswith(exempt):
                return True
        return False
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Add security headers to response"""
        response = await call_next(request)
        
        # Skip exempt paths
        if self._should_exempt(request.url.path):
            return response
        
        # X-Content-Type-Options: Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # X-Frame-Options: Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        
        # X-XSS-Protection: XSS filter for legacy browsers
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Strict-Transport-Security: Force HTTPS
        hsts_value = f"max-age={self.hsts_max_age}"
        if self.hsts_include_subdomains:
            hsts_value += "; includeSubDomains"
        response.headers["Strict-Transport-Security"] = hsts_value
        
        # Content-Security-Policy: Restrict resource loading
        response.headers["Content-Security-Policy"] = self.csp_directives
        
        # Referrer-Policy: Control referrer information
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions-Policy: Disable unnecessary browser features
        response.headers["Permissions-Policy"] = (
            "geolocation=(), "
            "microphone=(), "
            "camera=(), "
            "payment=(), "
            "usb=(), "
            "magnetometer=(), "
            "gyroscope=(), "
            "accelerometer=()"
        )
        
        # X-Permitted-Cross-Domain-Policies: Restrict Adobe Flash/PDF
        response.headers["X-Permitted-Cross-Domain-Policies"] = "none"
        
        # Cross-Origin-Opener-Policy: Isolate browsing context
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        
        # Cross-Origin-Resource-Policy: Restrict resource loading
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        
        # Add correlation ID header if present
        if hasattr(request.state, 'correlation_id'):
            response.headers["X-Correlation-ID"] = request.state.correlation_id
        
        return response


class SensitiveDataCacheMiddleware(BaseHTTPMiddleware):
    """
    Middleware to prevent caching of sensitive endpoints
    
    Adds Cache-Control: no-store, no-cache, must-revalidate
    to sensitive endpoints like auth, user data, etc.
    """
    
    SENSITIVE_PATHS = [
        "/api/v1/auth",
        "/api/v1/users",
        "/api/v1/ial/envelopes",
        "/api/v1/claims",
        "/health/detailed"
    ]
    
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Add no-cache headers to sensitive endpoints"""
        response = await call_next(request)
        
        # Check if path is sensitive
        is_sensitive = any(
            request.url.path.startswith(path)
            for path in self.SENSITIVE_PATHS
        )
        
        if is_sensitive:
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, private"
            )
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        
        return response


def setup_security_headers(app, **kwargs):
    """
    Setup security headers middleware for FastAPI app
    
    Usage:
        from middleware.security_headers import setup_security_headers
        setup_security_headers(app)
    """
    app.add_middleware(SecurityHeadersMiddleware, **kwargs)
    app.add_middleware(SensitiveDataCacheMiddleware)
    
    logger.info("Security headers middleware enabled")
