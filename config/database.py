"""
Database Configuration for Third Place Platform

Configures SQLAlchemy engine with proper settings for SQLite and PostgreSQL.
"""
import os
from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool, QueuePool
from dotenv import load_dotenv
import logging

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Database configuration
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./thirdplace.db"
)

# Connection pool settings
POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "5"))
MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "10"))
POOL_TIMEOUT = int(os.getenv("DB_POOL_TIMEOUT", "30"))
POOL_RECYCLE = int(os.getenv("DB_POOL_RECYCLE", "3600"))


def create_database_engine():
    """
    Create database engine with appropriate settings based on database type.
    
    Returns:
        SQLAlchemy engine instance
    """
    is_sqlite = "sqlite" in DATABASE_URL
    
    if is_sqlite:
        logger.info("Configuring SQLite database engine")
        
        # For SQLite, use StaticPool for single-threaded or check_same_thread=False for multi-threaded
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,  # Single connection for SQLite
            echo=os.getenv("SQL_ECHO", "false").lower() == "true"
        )
        
        # Enable SQLite optimizations via PRAGMA statements
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            """Configure SQLite with production-ready settings"""
            cursor = dbapi_connection.cursor()
            
            # Enable WAL mode for better concurrency
            # WAL allows concurrent reads while writes are happening
            cursor.execute("PRAGMA journal_mode=WAL")
            
            # Synchronous=NORMAL is safe for most use cases and faster than FULL
            cursor.execute("PRAGMA synchronous=NORMAL")
            
            # Increase cache size (pages, default is usually 2000)
            cursor.execute("PRAGMA cache_size=-10000")  # 10MB cache
            
            # Use memory for temp store instead of disk
            cursor.execute("PRAGMA temp_store=MEMORY")
            
            # Set busy timeout to wait for locks (5 seconds)
            cursor.execute("PRAGMA busy_timeout=5000")
            
            # Enable foreign keys
            cursor.execute("PRAGMA foreign_keys=ON")
            
            cursor.close()
            
            logger.info("SQLite PRAGMA settings applied: WAL mode, cache, timeouts")
        
        # Vacuum and analyze on startup for optimal performance
        @event.listens_for(engine, "begin")
        def do_begin(conn):
            """Optimize SQLite on first connection"""
            if not hasattr(do_begin, 'initialized'):
                conn.execute("PRAGMA optimize")
                do_begin.initialized = True
        
    else:
        logger.info(f"Configuring PostgreSQL database engine")
        
        # For PostgreSQL, use connection pooling
        engine = create_engine(
            DATABASE_URL,
            pool_size=POOL_SIZE,
            max_overflow=MAX_OVERFLOW,
            pool_timeout=POOL_TIMEOUT,
            pool_recycle=POOL_RECYCLE,
            pool_pre_ping=True,  # Verify connections before use
            echo=os.getenv("SQL_ECHO", "false").lower() == "true"
        )
        
        # PostgreSQL-specific optimizations
        @event.listens_for(engine, "connect")
        def set_postgresql_session_params(dbapi_connection, connection_record):
            """Configure PostgreSQL session parameters"""
            cursor = dbapi_connection.cursor()
            
            # Set statement timeout (30 seconds)
            cursor.execute("SET statement_timeout = 30000")
            
            # Set idle session timeout (10 minutes)
            cursor.execute("SET idle_in_transaction_session_timeout = 600000")
            
            cursor.close()
            
            logger.info("PostgreSQL session parameters applied")
    
    return engine


# Create engine
engine = create_database_engine()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base class for models
Base = declarative_base()


def get_db():
    """
    Dependency for getting database session.
    
    Yields:
        Database session
        
    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Initialize database tables.
    
    Note: For production, use Alembic migrations instead:
        alembic upgrade head
    """
    logger.info("Initializing database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully")


def get_engine():
    """Get the database engine instance"""
    return engine
