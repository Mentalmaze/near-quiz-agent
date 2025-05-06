from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from utils.config import Config
from models.user import Base as UserBase
from models.quiz import Base as QuizBase
import logging
import os

logger = logging.getLogger(__name__)

# Try to create the database engine with proper error handling
try:
    database_url = Config.DATABASE_URL

    # Fix the postgres dialect issue - replace 'postgres:' with 'postgresql:'
    if database_url and database_url.startswith("postgres:"):
        database_url = database_url.replace("postgres:", "postgresql:", 1)
        logger.info("Modified database URL from postgres: to postgresql: format")

    # For better debugging
    if database_url and ("postgresql" in database_url or "postgres" in database_url):
        logger.info("Using PostgreSQL database")
        try:
            # For remote PostgreSQL connections, we need the psycopg2 driver
            import psycopg2

            logger.info("PostgreSQL driver (psycopg2) found")
        except ImportError:
            logger.error("PostgreSQL driver not found. Falling back to SQLite.")
            database_url = "sqlite:///./mental_maze.db"

        # Additional logging for remote connections
        if "@" in database_url:
            # Extract host without exposing credentials
            host_part = database_url.split("@")[1].split("/")[0]
            logger.info(f"Connecting to remote PostgreSQL database at {host_part}")
    else:
        logger.info("Using SQLite database")

    # Create the engine with the configured URL
    logger.info(f"Attempting database connection...")

    # For PostgreSQL, add connection pool settings for better handling of remote connections
    engine_args = {}
    if "postgresql" in database_url:
        engine_args.update(
            {
                "pool_size": 5,
                "max_overflow": 10,
                "pool_timeout": 30,
                "pool_recycle": 1800,  # Recycle connections after 30 minutes
            }
        )

    engine = create_engine(
        database_url,
        connect_args=(
            {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        ),
        **engine_args,
    )
    logger.info(f"Database engine created successfully")

except Exception as e:
    logger.error(f"Failed to create database engine: {e}")
    logger.error("Falling back to SQLite database")

    # Fallback to SQLite in case of any error
    sqlite_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "mental_maze.db"
    )
    fallback_url = f"sqlite:///{sqlite_path}"
    logger.info(f"Using fallback database URL: {fallback_url}")

    engine = create_engine(fallback_url, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create database tables."""
    # Drop existing tables to sync new schema (dev only)
    # This is potentially dangerous in production, so add a safety check
    if not Config.is_production():
        logger.info("Development environment detected. Recreating database tables...")
        UserBase.metadata.drop_all(bind=engine)
        QuizBase.metadata.drop_all(bind=engine)
        # Create fresh tables
        UserBase.metadata.create_all(bind=engine)
        QuizBase.metadata.create_all(bind=engine)
    else:
        logger.info(
            "Production environment detected. Creating tables if they don't exist..."
        )
        # Only create tables that don't exist
        UserBase.metadata.create_all(bind=engine)
        QuizBase.metadata.create_all(bind=engine)


def migrate_schema():
    """Handle schema migrations for existing database structures."""
    try:
        # For BigInteger migration, we need to recreate the table
        # This is destructive, so we'll log it clearly
        logger.warning(
            "Migrating database schema - this may involve dropping and recreating tables"
        )

        # We specifically need to update the quizzes table for the BigInteger change
        QuizBase.metadata.drop_all(
            bind=engine, tables=[QuizBase.metadata.tables["quizzes"]]
        )
        QuizBase.metadata.create_all(
            bind=engine, tables=[QuizBase.metadata.tables["quizzes"]]
        )

        logger.info("Schema migration completed successfully")
        return True
    except Exception as e:
        logger.error(f"Schema migration failed: {e}")
        return False
