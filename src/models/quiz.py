from sqlalchemy import Column, String, Enum, JSON, DateTime, Integer
from sqlalchemy.ext.declarative import declarative_base
import enum
import uuid
import datetime

Base = declarative_base()


class QuizStatus(enum.Enum):
    DRAFT = "DRAFT"
    FUNDING = "FUNDING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class Quiz(Base):
    __tablename__ = "quizzes"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    topic = Column(String, nullable=False)
    questions = Column(JSON, default=[])
    status = Column(Enum(QuizStatus), default=QuizStatus.DRAFT)
    # Reward details and on-chain address
    reward_schedule = Column(JSON, default={})
    deposit_address = Column(String, nullable=True)
    # New columns
    last_updated = Column(
        DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow
    )
    group_chat_id = Column(Integer, nullable=True)
