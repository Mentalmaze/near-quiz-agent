from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from utils.config import Config
from models.user import Base as UserBase
from models.quiz import Base as QuizBase
import logging

logger = logging.getLogger(__name__)

# Try to create the database engine with proper error handling
try:
    # Check if we're using PostgreSQL and log the database type
    if Config.DATABASE_URL and "postgres" in Config.DATABASE_URL:
        logger.info("Using PostgreSQL database")
    else:
        logger.info("Using SQLite database")

    # Create the engine with the configured URL
    engine = create_engine(
        Config.DATABASE_URL,
        connect_args=(
            {"check_same_thread": False}
            if Config.DATABASE_URL.startswith("sqlite")
            else {}
        ),
    )
    logger.info(f"Database engine created successfully")

except Exception as e:
    logger.error(f"Failed to create database engine: {e}")
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
