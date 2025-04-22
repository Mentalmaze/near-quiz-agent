from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from utils.config import Config
from models.user import Base as UserBase
from models.quiz import Base as QuizBase

# SQLite default; adjust connect_args for SQLite
engine = create_engine(
    Config.DATABASE_URL,
    connect_args=(
        {"check_same_thread": False} if Config.DATABASE_URL.startswith("sqlite") else {}
    ),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create database tables."""
    UserBase.metadata.create_all(bind=engine)
    QuizBase.metadata.create_all(bind=engine)
