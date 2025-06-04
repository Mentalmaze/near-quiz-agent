#!/usr/bin/env python3
"""
Database Migration: Add Performance Indexes
This script adds critical indexes to improve quiz gameplay performance.

Usage: python migrations/add_performance_indexes.py
"""

import sys
import os

sys.path.append(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
)

from sqlalchemy import text, Index
from store.database import engine, SessionLocal
from models.quiz import QuizAnswer
import logging

logger = logging.getLogger(__name__)


def add_performance_indexes():
    """Add performance indexes for quiz gameplay optimization."""
    session = SessionLocal()

    try:
        # List of indexes to create
        indexes_to_create = [
            # Prevent duplicate submissions (unique constraint)
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_user_quiz_question ON quiz_answers (user_id, quiz_id, question_index);",
            # Optimize leaderboard queries (quiz_id + is_correct + answered_at)
            "CREATE INDEX IF NOT EXISTS idx_quiz_correct_time ON quiz_answers (quiz_id, is_correct, answered_at);",
            # Optimize user participation lookups
            "CREATE INDEX IF NOT EXISTS idx_user_quiz_lookup ON quiz_answers (user_id, quiz_id);",
            # Optimize time-based queries for quiz answers
            "CREATE INDEX IF NOT EXISTS idx_quiz_answers_time ON quiz_answers (answered_at);",
            # Optimize quiz status and group chat queries
            "CREATE INDEX IF NOT EXISTS idx_quiz_status_group ON quizzes (status, group_chat_id);",
            # Optimize quiz end time queries for active quiz filtering
            "CREATE INDEX IF NOT EXISTS idx_quiz_end_time ON quizzes (end_time) WHERE end_time IS NOT NULL;",
            # Optimize payment transaction hash lookups
            "CREATE INDEX IF NOT EXISTS idx_quiz_payment_hash ON quizzes (payment_transaction_hash) WHERE payment_transaction_hash IS NOT NULL;",
        ]

        print("Adding performance indexes for quiz gameplay optimization...")

        for i, index_sql in enumerate(indexes_to_create, 1):
            try:
                print(f"[{i}/{len(indexes_to_create)}] Creating index...")
                session.execute(text(index_sql))
                session.commit()
                print(f"✅ Successfully created index {i}")
            except Exception as e:
                print(f"❌ Error creating index {i}: {e}")
                session.rollback()
                continue

        print("\n✅ Performance indexes migration completed!")
        print("\nIndexes added:")
        print(
            "- Unique constraint on user_id + quiz_id + question_index (prevents duplicates)"
        )
        print("- Quiz leaderboard optimization (quiz_id + is_correct + answered_at)")
        print("- User participation lookup optimization")
        print("- Time-based query optimization")
        print("- Quiz status and group filtering optimization")
        print("- Quiz end time filtering optimization")
        print("- Payment hash lookup optimization")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    add_performance_indexes()
