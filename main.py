"""
Third Place Platform - Main Application Entry Point

This is the main FastAPI application that serves as the API gateway
for the Third Place Platform.
"""
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import uvicorn
import os
import logging
import time

# Configure logging first
from middleware.logging_middleware import setup_logging, LoggingMiddleware, SecurityLoggingMiddleware

setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    log_file=os.getenv("LOG_FILE")
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager

    Handles startup and shutdown events
    """
    # ========== STARTUP ==========
    logger.info("=" * 60)
    logger.info("Starting Third Place Platform...")
    logger.info("=" * 60)

    # 1. Initialize .env file if needed
    from config.configuration import init_env_file
    if init_env_file():
        logger.info("Created new .env file with secure defaults")

    # 2. Validate all configuration BEFORE starting
    logger.info("Validating configuration...")
    from config.configuration import validate_configuration
    try:
        config = validate_configuration()
        logger.info("Configuration validation passed")
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        raise

    # 3. Initialize database
    logger.info("Initializing database...")
    from config.database import init_db
    init_db()
    logger.info("Database ready")

    # 4. Setup rate limiting
    logger.info("Setting up rate limiting...")
    from middleware.rate_limiter import setup_rate_limiting
    setup_rate_limiting(app)
    logger.info("Rate limiting configured")

    # 5. Initialize lock integration service
    logger.info("Initializing lock integration...")
    from services.lock_integration import AccessGrantService, KisiAdapter, SchlageAdapter, GenericQRAdapter

    access_grant_service = AccessGrantService()

    # Register lock adapters
    kisi_key = os.getenv("KISI_API_KEY")
    kisi_secret = os.getenv("KISI_API_SECRET")
    if kisi_key and kisi_secret:
        access_grant_service.register_adapter("kisi", KisiAdapter(kisi_key, kisi_secret))
        logger.info("✓ Kisi adapter registered")
    else:
        logger.warning("⚠ KISI_API_KEY or KISI_API_SECRET not set, Kisi adapter disabled")

    schlage_key = os.getenv("SCHLAGE_API_KEY")
    if schlage_key:
        access_grant_service.register_adapter("schlage", SchlageAdapter(schlage_key))
        logger.info("✓ Schlage adapter registered")
    else:
        logger.warning("⚠ SCHLAGE_API_KEY not set, Schlage adapter disabled")

    # Always register generic QR adapter
    jwt_secret = config["jwt_secret"]
    access_grant_service.register_adapter("generic", GenericQRAdapter(jwt_secret))
    logger.info("✓ Generic QR adapter registered")

    # Store in app state
    app.state.access_grant_service = access_grant_service
    app.state.jwt_secret = jwt_secret
    app.state.config = config

    logger.info("=" * 60)
    logger.info("Third Place Platform started successfully")
    logger.info(f"Environment: {os.getenv('ENV', 'development')}")
    logger.info(f"API Docs: /docs")
    logger.info(f"Health Check: /health")
    logger.info("=" * 60)

    yield

    # ========== SHUTDOWN ==========
    logger.info("Shutting down Third Place Platform...")

    # Cleanup lock adapters
    if hasattr(app.state, 'access_grant_service'):
        import asyncio
        for adapter in app.state.access_grant_service.adapters.values():
            if hasattr(adapter, 'close'):
                try:
                    asyncio.get_event_loop().run_until_complete(adapter.close())
                except Exception as e:
                    logger.error(f"Error closing adapter: {e}")

    logger.info("Third Place Platform shutdown complete")


# Main FastAPI application
app = FastAPI(
    title="Third Place Platform",
    version="2.0.0",
    description="""
## Infrastructure for Recurring Physical Community Spaces

The Third Place Platform provides insurance coverage and access control
for physical community gatherings.

### Key Features

**Insurance Abstraction Layer**
- Activity classification and risk assessment
- Dynamic pricing based on multiple factors
- Coverage verification and certificate generation

**Access Control Integration**
- Multiple lock vendor support (Kisi, Schlage, Generic QR)
- Capacity enforcement
- Real-time access revocation

**Claims and Incident Management**
- Incident reporting
- Claims processing
- Risk analysis

### Authentication

All endpoints require JWT authentication. Obtain a token via the `/auth/login` endpoint.
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan
)


# =============================================================================
# Request Size Limit Middleware
# =============================================================================

MAX_REQUEST_SIZE = 10 * 1024 * 1024  # 10MB


@app.middleware("http")
async def check_request_size(request: Request, call_next):
    """
    Middleware to check request size and reject large payloads.
    
    Prevents DoS attacks via large request bodies.
    """
    content_length = request.headers.get("content-length")
    
    if content_length:
        try:
            size = int(content_length)
            if size > MAX_REQUEST_SIZE:
                logger.warning(f"Request too large: {size} bytes (max: {MAX_REQUEST_SIZE})")
                return JSONResponse(
                    status_code=413,
                    content={
                        "error": "Request body too large",
                        "max_size_bytes": MAX_REQUEST_SIZE,
                        "received_bytes": size
                    }
                )
        except ValueError:
            pass
    
    # Also check during body read for chunked transfers
    try:
        body = await request.body()
        if len(body) > MAX_REQUEST_SIZE:
            return JSONResponse(
                status_code=413,
                content={
                    "error": "Request body too large",
                    "max_size_bytes": MAX_REQUEST_SIZE
                }
            )
    except Exception as e:
        return JSONResponse(
            status_code=400,
            content={"error": f"Invalid request body: {str(e)}"}
        )
    
    return await call_next(request)


# =============================================================================
# CORS Middleware
# =============================================================================

# Get validated CORS origins from config
def get_cors_origins():
    """Get CORS origins from validated config"""
    if hasattr(app.state, 'config'):
        return app.state.config.get('allowed_origins', ['*'])
    # Fallback for during middleware setup (before config is loaded)
    from config.configuration import validate_cors_origins
    try:
        return validate_cors_origins()
    except Exception:
        return ["http://localhost:3000", "http://localhost:8000"]


# Note: CORS is added after config is loaded in lifespan
# This is a placeholder that gets updated


# =============================================================================
# Logging Middleware
# =============================================================================

# Logging middleware (must be added before other middleware)
app.add_middleware(LoggingMiddleware, include_body=False)
app.add_middleware(SecurityLoggingMiddleware)

# Security headers middleware
try:
    from middleware.security_headers import setup_security_headers
    setup_security_headers(app)
except ImportError as e:
    logger.warning(f"Security headers middleware not available: {e}")


# =============================================================================
# API Routers
# =============================================================================

# Include API routers
from api.insurance_api import router as insurance_router
app.include_router(insurance_router, prefix="/api/v1", tags=["Insurance"])

# Add authentication router
try:
    from api.auth_api import router as auth_router
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
    logger.info("Auth router registered")
except ImportError as e:
    logger.warning(f"Auth router not available: {e}")

# Add audit log router
try:
    from api.audit_api import router as audit_router
    app.include_router(audit_router, prefix="/api/v1", tags=["Audit Logs"])
    logger.info("Audit router registered")
except ImportError as e:
    logger.warning(f"Audit router not available: {e}")

# Add metrics router
try:
    from api.metrics_api import router as metrics_router
    app.include_router(metrics_router)
    logger.info("Metrics router registered")
except ImportError as e:
    logger.warning(f"Metrics router not available: {e}")


# =============================================================================
# Health Check Endpoints
# =============================================================================

@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - API welcome message"""
    return {
        "message": "Welcome to the Third Place Platform API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health"
    }


@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Third Place Platform API",
        "version": "2.0.0"
    }


@app.get("/health/detailed", tags=["Health"])
async def health_detailed(request: Request):
    """
    Detailed health check with dependency status
    
    Checks:
    - Database connectivity
    - Lock adapter configuration
    - Configuration validation
    """
    from sqlalchemy import text
    from config.database import get_engine, DATABASE_URL
    
    health_status = {
        "status": "healthy",
        "service": "Third Place Platform API",
        "version": "2.0.0",
        "timestamp": time.time(),
        "dependencies": {}
    }
    
    # Check database
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        db_type = "sqlite" if "sqlite" in DATABASE_URL else "postgresql"
        health_status["dependencies"]["database"] = {
            "status": "healthy",
            "type": db_type,
            "url": DATABASE_URL.split("://")[0]
        }
    except Exception as e:
        health_status["dependencies"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }
        health_status["status"] = "degraded"
    
    # Check lock adapters
    lock_status = {}
    if hasattr(request.app.state, 'access_grant_service'):
        for vendor in request.app.state.access_grant_service.adapters.keys():
            lock_status[vendor] = {"status": "configured"}
    else:
        lock_status["status"] = "not_initialized"
    
    health_status["dependencies"]["lock_adapters"] = lock_status
    
    # Check configuration
    if hasattr(request.app.state, 'config'):
        health_status["dependencies"]["configuration"] = {"status": "validated"}
    else:
        health_status["dependencies"]["configuration"] = {"status": "not_validated"}
        health_status["status"] = "degraded"
    
    # Add warnings for production concerns
    warnings = []
    if "sqlite" in DATABASE_URL and os.getenv("ENV") == "production":
        warnings.append("Running SQLite in production is not recommended")
    
    if warnings:
        health_status["warnings"] = warnings
        if health_status["status"] == "healthy":
            health_status["status"] = "warning"
    
    # Return appropriate status code
    status_code = 200 if health_status["status"] in ["healthy", "warning"] else 503
    return JSONResponse(content=health_status, status_code=status_code)


# =============================================================================
# Rate Limit Info Endpoint
# =============================================================================

@app.get("/rate-limit-info", tags=["Health"])
async def rate_limit_info():
    """Get information about rate limiting"""
    return {
        "enabled": True,
        "limits": {
            "auth": "5/minute",
            "login": "10/minute",
            "register": "5/hour",
            "standard": "100/minute",
            "heavy_operations": "10/minute",
            "read": "200/minute",
            "void_envelope": "10/hour"
        }
    }


# =============================================================================
# Exception Handlers
# =============================================================================

from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from utils.exceptions import ThirdPlaceException


@app.exception_handler(ThirdPlaceException)
async def third_place_exception_handler(request: Request, exc: ThirdPlaceException):
    """Handle custom Third Place exceptions"""
    logger.warning(f"ThirdPlaceException: {exc.message}")
    return JSONResponse(
        status_code=400,
        content={
            "error": exc.message,
            "error_code": exc.error_code
        }
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle request validation errors"""
    logger.warning(f"Validation error: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "details": exc.errors()
        }
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors"""
    logger.warning(f"Pydantic validation error: {exc.errors()}")
    return JSONResponse(
        status_code=422,
        content={
            "error": "Validation error",
            "details": exc.errors()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unhandled exceptions"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": "An unexpected error occurred"
        }
    )


# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "false").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info")
    workers = int(os.getenv("WORKERS", "1"))

    logger.info(f"Starting server on {host}:{port} with {workers} workers")

    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level,
        workers=workers if not reload else 1
    )
