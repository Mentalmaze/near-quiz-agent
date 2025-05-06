from sqlalchemy import Column, String, Enum, JSON, DateTime, BigInteger, Boolean
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
    group_chat_id = Column(
        BigInteger, nullable=True
    )  # Changed from Integer to BigInteger
    # Quiz end time
    end_time = Column(DateTime, nullable=True)
    # Track if winners have been announced
    winners_announced = Column(String, default=False)


class QuizAnswer(Base):
    """Model to track user answers to quizzes"""

    __tablename__ = "quiz_answers"
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    quiz_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    username = Column(String, nullable=True)  # For displaying winners
    answer = Column(String, nullable=False)  # User's selected answer (e.g., "A", "B")
    is_correct = Column(String, nullable=False, default=False)  # Whether it's correct
    answered_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Quick helper to compute rank based on correct answers and speed
    @staticmethod
    def compute_quiz_winners(session, quiz_id):
        """Compute winners for a quiz based on correct answers and timing"""
        # Get all correct answers for this quiz
        # Fix: Use string 'True' instead of boolean True for comparison
        correct_answers = (
            session.query(QuizAnswer)
            .filter(QuizAnswer.quiz_id == quiz_id, QuizAnswer.is_correct == "True")
            .order_by(QuizAnswer.answered_at)
            .all()
        )

        # Group by user and count correct answers
        user_scores = {}
        for answer in correct_answers:
            if answer.user_id not in user_scores:
                user_scores[answer.user_id] = {
                    "user_id": answer.user_id,
                    "username": answer.username,
                    "correct_count": 1,
                    "first_answer_time": answer.answered_at,
                }
            else:
                user_scores[answer.user_id]["correct_count"] += 1

        # Sort by correct count (desc) and then by time (asc)
        sorted_scores = sorted(
            user_scores.values(),
            key=lambda x: (-x["correct_count"], x["first_answer_time"]),
        )

        return sorted_scores
