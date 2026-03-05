"""
Third Place Platform - Main Application Entry Point

This is the main FastAPI application that serves as the API gateway
for the Third Place Platform.
"""
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from config.database import engine, Base
import uvicorn
import os
import logging

# Configure logging first
from middleware.logging_middleware import setup_logging, LoggingMiddleware, SecurityLoggingMiddleware
setup_logging(
    level=os.getenv("LOG_LEVEL", "INFO"),
    log_file=os.getenv("LOG_FILE")
)

logger = logging.getLogger(__name__)


# Import API routers
from api.insurance_api import router as insurance_router


# Import middleware
from middleware.rate_limiter import setup_rate_limiting, limiter
from middleware.logging_middleware import LoggingMiddleware, SecurityLoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager
    
    Handles startup and shutdown events
    """
    # Startup
    logger.info("Starting Third Place Platform...")
    
    # Create database tables
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables ready")
    
    # Setup rate limiting
    logger.info("Setting up rate limiting...")
    setup_rate_limiting(app)
    
    # Initialize lock integration service
    logger.info("Initializing lock integration...")
    from services.lock_integration import AccessGrantService, KisiAdapter, SchlageAdapter, GenericQRAdapter
    
    access_grant_service = AccessGrantService()
    
    # Register lock adapters
    kisi_key = os.getenv("KISI_API_KEY")
    kisi_secret = os.getenv("KISI_API_SECRET")
    if kisi_key and kisi_secret:
        access_grant_service.register_adapter("kisi", KisiAdapter(kisi_key, kisi_secret))
        logger.info("Kisi adapter registered")
    else:
        logger.warning("KISI_API_KEY or KISI_API_SECRET not set, Kisi adapter disabled")
    
    schlage_key = os.getenv("SCHLAGE_API_KEY")
    if schlage_key:
        access_grant_service.register_adapter("schlage", SchlageAdapter(schlage_key))
        logger.info("Schlage adapter registered")
    else:
        logger.warning("SCHLAGE_API_KEY not set, Schlage adapter disabled")
    
    # Always register generic QR adapter
    jwt_secret = os.getenv("JWT_SECRET_KEY", "default-secret")
    access_grant_service.register_adapter("generic", GenericQRAdapter(jwt_secret))
    logger.info("Generic QR adapter registered")
    
    # Store in app state
    app.state.access_grant_service = access_grant_service
    app.state.jwt_secret = jwt_secret
    
    logger.info("Third Place Platform started successfully")
    
    yield
    
    # Shutdown
    logger.info("Shutting down Third Place Platform...")
    
    # Cleanup lock adapters
    if hasattr(app.state, 'access_grant_service'):
        for adapter in app.state.access_grant_service.adapters.values():
            if hasattr(adapter, 'close'):
                try:
                    await adapter.close()
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

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging middleware (must be added before other middleware)
app.add_middleware(LoggingMiddleware, include_body=False)
app.add_middleware(SecurityLoggingMiddleware)

# Include API routers
app.include_router(insurance_router, prefix="/api/v1", tags=["Insurance"])

# Add authentication router
try:
    from api.auth_api import router as auth_router
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
    logger.info("Auth router registered")
except ImportError:
    logger.warning("Auth router not available")


# Root endpoint
@app.get("/", tags=["Health"])
async def root():
    """Root endpoint - API welcome message"""
    return {
        "message": "Welcome to the Third Place Platform API",
        "version": "2.0.0",
        "docs": "/docs",
        "health": "/health"
    }


# Health check endpoint
@app.get("/health", tags=["Health"])
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "Third Place Platform API",
        "version": "2.0.0"
    }


# Detailed health check
@app.get("/health/detailed", tags=["Health"])
async def health_detailed(request: Request):
    """
    Detailed health check with dependency status
    """
    from sqlalchemy import text
    
    health_status = {
        "status": "healthy",
        "service": "Third Place Platform API",
        "version": "2.0.0",
        "dependencies": {}
    }
    
    # Check database
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        health_status["dependencies"]["database"] = "healthy"
    except Exception as e:
        health_status["dependencies"]["database"] = f"unhealthy: {str(e)}"
        health_status["status"] = "degraded"
    
    # Check lock adapters
    lock_status = {}
    if hasattr(request.app.state, 'access_grant_service'):
        for vendor in request.app.state.access_grant_service.adapters.keys():
            lock_status[vendor] = "registered"
    health_status["dependencies"]["lock_adapters"] = lock_status
    
    return health_status


# Rate limit info endpoint
@app.get("/rate-limit-info", tags=["Health"])
async def rate_limit_info():
    """Get information about rate limiting"""
    return {
        "enabled": True,
        "limits": {
            "auth": "5/minute",
            "standard": "100/minute",
            "heavy_operations": "10/minute",
            "read": "200/minute"
        }
    }


if __name__ == "__main__":
    # Get configuration from environment
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "false").lower() == "true"
    log_level = os.getenv("LOG_LEVEL", "info")
    
    logger.info(f"Starting server on {host}:{port}")
    
    uvicorn.run(
        "main:app",
        host=host,
        port=port,
        reload=reload,
        log_level=log_level
    )
