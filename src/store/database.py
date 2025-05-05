from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from utils.config import Config
from models.user import Base as UserBase
from models.quiz import Base as QuizBase
import logging

logger = logging.getLogger(__name__)

# Try to create the database engine with proper error handling
try:
    # Check if we're using PostgreSQL and try to import the driver
    if Config.DATABASE_URL and "postgres" in Config.DATABASE_URL:
        try:
            import psycopg2

            logger.info("PostgreSQL driver found, using PostgreSQL database")
        except ImportError:
            # PostgreSQL driver not installed, warn the user
            logger.error("PostgreSQL URL detected but psycopg2 driver not installed!")
            logger.error(
                "Please install PostgreSQL driver: pip install psycopg2-binary"
            )
            raise ImportError(
                "PostgreSQL driver (psycopg2) not installed. Run: pip install psycopg2-binary"
            )

    # Create the engine with the configured URL
    engine = create_engine(
        Config.DATABASE_URL,
        connect_args=(
            {"check_same_thread": False}
            if Config.DATABASE_URL.startswith("sqlite")
            else {}
        ),
    )
    logger.info(f"Database engine created with URL: {Config.DATABASE_URL}")

except Exception as e:
    logger.error(f"Failed to create database engine: {e}")
    logger.error(
        "If you're switching to PostgreSQL, please install the required driver:"
    )
    logger.error("pip install psycopg2-binary")
    raise

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create database tables."""
    # Drop existing tables to sync new schema (dev only)
    UserBase.metadata.drop_all(bind=engine)
    QuizBase.metadata.drop_all(bind=engine)
    # Create fresh tables
    UserBase.metadata.create_all(bind=engine)
    QuizBase.metadata.create_all(bind=engine)
