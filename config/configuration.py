"""
Configuration Validation for Third Place Platform

Validates all required configuration at application startup.
"""
import os
import secrets
import warnings
from pathlib import Path
from typing import List


class ConfigurationError(Exception):
    """Raised when configuration is invalid"""
    pass


# Default/weak secrets that should never be used
DEFAULT_SECRETS = [
    "your-super-secret-key-change-in-production",
    "default-secret",
    "change-me",
    "secret-key",
    "test-secret",
    "changeme",
    "password",
    "admin",
    "123456",
]


def validate_jwt_secret() -> str:
    """
    Validate JWT secret configuration.
    
    Returns:
        str: Validated JWT secret
        
    Raises:
        ConfigurationError: If JWT secret is missing or weak
    """
    jwt_secret = os.getenv("JWT_SECRET_KEY")
    
    if not jwt_secret:
        raise ConfigurationError(
            "JWT_SECRET_KEY environment variable is required but not set. "
            "Generate a secure random string using: "
            "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    
    if len(jwt_secret) < 32:
        raise ConfigurationError(
            f"JWT_SECRET_KEY must be at least 32 characters long (got {len(jwt_secret)}). "
            "Generate a secure random string using: "
            "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    
    if jwt_secret in DEFAULT_SECRETS:
        raise ConfigurationError(
            "JWT_SECRET_KEY is set to a default/weak value. "
            "Generate a secure random string using: "
            "python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    
    return jwt_secret


def validate_database_url() -> str:
    """
    Validate database URL configuration.
    
    Returns:
        str: Validated database URL
        
    Raises:
        ConfigurationError: If database URL is missing
    """
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        raise ConfigurationError(
            "DATABASE_URL environment variable is required. "
            "Examples: "
            "sqlite:///./thirdplace.db or "
            "postgresql://user:pass@localhost:5432/thirdplace"
        )
    
    # Warn about SQLite in production
    if "sqlite" in database_url and os.getenv("ENV") == "production":
        warnings.warn(
            "WARNING: Using SQLite in production is not recommended. "
            "Consider using PostgreSQL for better concurrency and reliability."
        )
    
    return database_url


def validate_cors_origins() -> List[str]:
    """
    Validate CORS origins configuration.
    
    Returns:
        List[str]: List of allowed origins
        
    Raises:
        ConfigurationError: If CORS configuration is invalid
    """
    allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
    
    if allowed_origins == "*":
        if os.getenv("ENV") == "production":
            raise ConfigurationError(
                "CORS wildcard (*) not allowed in production. "
                "Set ALLOWED_ORIGINS to specific domains (comma-separated). "
                "Example: ALLOWED_ORIGINS=https://app.example.com,https://admin.example.com"
            )
        else:
            warnings.warn(
                "WARNING: CORS is set to allow all origins (*). "
                "This is acceptable for development but should be restricted in production."
            )
            return ["*"]
    
    # Parse and validate origins
    origins = [o.strip() for o in allowed_origins.split(",") if o.strip()]
    
    for origin in origins:
        if not origin.startswith(("http://", "https://")):
            raise ConfigurationError(
                f"Invalid CORS origin format: {origin}. "
                "Origins must start with http:// or https://"
            )
    
    return origins


def validate_configuration() -> dict:
    """
    Validate all required configuration at application startup.
    
    Returns:
        dict: Validated configuration values
        
    Raises:
        ConfigurationError: If any required configuration is invalid
    """
    config = {}
    
    # Validate JWT secret
    config["jwt_secret"] = validate_jwt_secret()
    
    # Validate database URL
    config["database_url"] = validate_database_url()
    
    # Validate CORS origins
    config["allowed_origins"] = validate_cors_origins()
    
    # Log configuration summary (without sensitive values)
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info("Configuration validation passed")
    logger.info(f"  - JWT Secret: configured ({len(config['jwt_secret'])} chars)")
    logger.info(f"  - Database: {config['database_url'].split('://')[0]}")
    logger.info(f"  - CORS Origins: {config['allowed_origins']}")
    logger.info(f"  - Environment: {os.getenv('ENV', 'development')}")
    
    return config


def generate_secure_jwt_secret() -> str:
    """
    Generate a secure random JWT secret.
    
    Returns:
        str: Secure random secret (32 bytes, URL-safe base64 encoded)
    """
    return secrets.token_urlsafe(32)


def init_env_file() -> bool:
    """
    Initialize .env file with secure defaults if it doesn't exist.
    
    Returns:
        bool: True if .env file was created, False if it already existed
    """
    env_file = Path(".env")
    
    if env_file.exists():
        return False
    
    # Generate secure JWT secret
    jwt_secret = generate_secure_jwt_secret()
    
    # Create .env file with secure defaults
    env_content = f"""# Third Place Platform Configuration
# Generated on startup - REVIEW AND UPDATE THESE VALUES

# Database
DATABASE_URL=sqlite:///./thirdplace.db

# JWT Configuration - KEEP THIS SECRET!
JWT_SECRET_KEY={jwt_secret}
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# Lock Integration API Keys (add your own)
KISI_API_KEY=
KISI_API_SECRET=
SCHLAGE_API_KEY=

# CORS - Comma-separated list of allowed origins
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000

# Logging
LOG_LEVEL=INFO
LOG_FILE=

# Environment (development, staging, production)
ENV=development
"""
    
    env_file.write_text(env_content)
    
    # Print security notice
    print("=" * 60)
    print("SECURITY NOTICE: New .env file created")
    print("=" * 60)
    print()
    print("A secure JWT_SECRET_KEY has been generated for you.")
    print("IMPORTANT: Back up this secret - if lost, all sessions will be invalidated!")
    print()
    print("To view your secret:")
    print("  cat .env | grep JWT_SECRET_KEY")
    print()
    print("For production deployment, set these environment variables:")
    print("  - DATABASE_URL (use PostgreSQL)")
    print("  - JWT_SECRET_KEY (use a secure random string)")
    print("  - ALLOWED_ORIGINS (your production domains)")
    print("=" * 60)
    
    return True
