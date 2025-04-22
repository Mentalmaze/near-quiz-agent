from sqlalchemy import Column, String, Enum, JSON
from sqlalchemy.ext.declarative import declarative_base
import enum
import uuid

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