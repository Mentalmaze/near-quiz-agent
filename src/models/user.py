from sqlalchemy import Column, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)  # Telegram user ID as string
    wallet_address = Column(String, nullable=True)
    linked_at = Column(DateTime, default=datetime.datetime.utcnow)
