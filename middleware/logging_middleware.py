"""
Logging Middleware for Third Place Platform

Provides comprehensive request/response logging with:
- Request timing
- IP address tracking
- User agent logging
- Correlation IDs
- Sensitive data masking
"""
import time
import uuid
import logging
import re
from typing import Callable
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


# Patterns to mask in logs (for security)
SENSITIVE_PATTERNS = [
    (re.compile(r'password["\']?\s*[:=]\s*["\']?[^"\',\s]+', re.IGNORECASE), 'password=***'),
    (re.compile(r'token["\']?\s*[:=]\s*["\']?[^"\',\s]+', re.IGNORECASE), 'token=***'),
    (re.compile(r'api[_-]?key["\']?\s*[:=]\s*["\']?[^"\',\s]+', re.IGNORECASE), 'api_key=***'),
    (re.compile(r'secret["\']?\s*[:=]\s*["\']?[^"\',\s]+', re.IGNORECASE), 'secret=***'),
    (re.compile(r'authorization["\']?\s*[:=]\s*["\']?[^"\',\s]+', re.IGNORECASE), 'authorization=***'),
    (re.compile(r'Bearer\s+[A-Za-z0-9\-_\.]+', re.IGNORECASE), 'Bearer ***'),
]


def mask_sensitive_data(text: str) -> str:
    """Mask sensitive data in log messages"""
    for pattern, replacement in SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class LoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for comprehensive request/response logging
    """
    
    def __init__(
        self,
        app: ASGIApp,
        logger: logging.Logger = None,
        include_body: bool = False,
        max_body_length: int = 1000
    ):
        super().__init__(app)
        self.logger = logger or logging.getLogger(__name__)
        self.include_body = include_body
        self.max_body_length = max_body_length

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process each request with logging"""
        
        # Generate correlation ID for request tracing
        correlation_id = str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        
        # Get client info
        client_host = request.client.host if request.client else "unknown"
        client_port = request.client.port if request.client else 0
        
        # Get request details
        method = request.method
        path = request.url.path
        query_string = str(request.url.query)
        user_agent = request.headers.get("user-agent", "unknown")
        
        # Mask sensitive data in query string
        query_string = mask_sensitive_data(query_string)
        
        # Log request start
        start_time = time.time()
        
        self.logger.info(
            f"[{correlation_id}] REQUEST: {method} {path}"
            f" from {client_host}:{client_port}"
            f" | Query: {query_string}"
            f" | UA: {user_agent[:100]}"
        )
        
        # Get request body if configured
        request_body = None
        if self.include_body and method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.body()
                body_str = body.decode()[:self.max_body_length]
                body_str = mask_sensitive_data(body_str)
                request_body = body_str
                if request_body:
                    self.logger.debug(f"[{correlation_id}] Request body: {request_body}")
            except Exception as e:
                self.logger.debug(f"[{correlation_id}] Could not read request body: {e}")
        
        # Process request
        try:
            response = await call_next(request)
        except Exception as e:
            # Log exception
            process_time = time.time() - start_time
            self.logger.error(
                f"[{correlation_id}] EXCEPTION: {method} {path}"
                f" after {process_time:.3f}s"
                f" | Error: {str(e)}"
            )
            raise
        
        # Calculate process time
        process_time = time.time() - start_time
        
        # Log response
        status_code = response.status_code
        self.logger.info(
            f"[{correlation_id}] RESPONSE: {status_code}"
            f" | {method} {path}"
            f" | Time: {process_time:.3f}s"
        )
        
        # Add headers for tracing
        response.headers["X-Correlation-ID"] = correlation_id
        response.headers["X-Process-Time"] = str(process_time)
        
        # Log response body if configured and not too large
        if self.include_body and status_code < 500:
            try:
                response_body = None
                async for chunk in response.body_iterator:
                    if response_body is None:
                        response_body = chunk
                    else:
                        response_body += chunk
                
                if response_body:
                    body_str = response_body.decode()[:self.max_body_length]
                    body_str = mask_sensitive_data(body_str)
                    self.logger.debug(f"[{correlation_id}] Response body: {body_str}")
                
                # Need to recreate the response body iterator
                response = Response(
                    content=response_body or b"",
                    status_code=status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type
                )
            except Exception as e:
                self.logger.debug(f"[{correlation_id}] Could not read response body: {e}")
        
        return response


class SecurityLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware for security-related logging
    Logs authentication failures, suspicious patterns, etc.
    """
    
    def __init__(self, app: ASGIApp, logger: logging.Logger = None):
        super().__init__(app)
        self.logger = logger or logging.getLogger("security")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Log security-relevant events"""
        
        client_host = request.client.host if request.client else "unknown"
        path = request.url.path
        method = request.method
        
        # Check for suspicious patterns
        suspicious_paths = [
            '/admin', '/api/v1/admin',
            '/.env', '/.git',
            '/wp-admin', '/phpmyadmin',
            '/actuator', '/metrics',
            '/graphql', '/api/graphql'
        ]
        
        for suspicious in suspicious_paths:
            if suspicious in path.lower():
                self.logger.warning(
                    f"SUSPICIOUS ACCESS: {method} {path}"
                    f" from {client_host}"
                )
        
        response = await call_next(request)
        
        # Log 4xx and 5xx errors
        if response.status_code >= 400:
            log_level = logging.WARNING if response.status_code >= 500 else logging.INFO
            self.logger.log(
                log_level,
                f"ERROR RESPONSE: {response.status_code}"
                f" | {method} {path}"
                f" from {client_host}"
            )
        
        return response


def setup_logging(
    level: str = "INFO",
    format_string: str = None,
    log_file: str = None
) -> None:
    """
    Configure application logging
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_string: Custom log format
        log_file: Optional file to log to
    """
    if format_string is None:
        format_string = (
            "%(asctime)s | %(levelname)-8s | "
            "%(name)s | %(message)s"
        )
    
    # Configure root logger
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=format_string,
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Add file handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter(format_string))
        logging.getLogger().addHandler(file_handler)
    
    # Set quieter loggers for noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("passlib").setLevel(logging.WARNING)
    
    logger.info(f"Logging configured at level {level}")


def get_correlation_id(request: Request) -> str:
    """Get correlation ID from request"""
    return getattr(request.state, 'correlation_id', 'unknown')
