#!/usr/bin/env python3
"""
Database Migration: Add question_index column to quiz_answers table
This script adds the question_index column required for duplicate prevention.

Usage: python migrations/add_question_index_column.py
"""

import sys
import os

sys.path.append(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
)

from sqlalchemy import text
from store.database import engine, SessionLocal
import logging

logger = logging.getLogger(__name__)


def add_question_index_column():
    """Add question_index column to quiz_answers table."""
    session = SessionLocal()

    try:
        print("Adding question_index column to quiz_answers table...")

        # Check if column already exists
        check_column = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'quiz_answers' AND column_name = 'question_index';
        """

        result = session.execute(text(check_column)).fetchone()

        if result:
            print("✅ question_index column already exists!")
            return

        # Add the column
        add_column_sql = """
        ALTER TABLE quiz_answers
        ADD COLUMN question_index INTEGER DEFAULT 0 NOT NULL;
        """

        session.execute(text(add_column_sql))
        session.commit()

        print("✅ Successfully added question_index column!")

        # Update existing records to have proper question_index values
        print("Updating existing records with question_index values...")

        update_sql = """
        WITH ranked_answers AS (
            SELECT id,
                   ROW_NUMBER() OVER (PARTITION BY user_id, quiz_id ORDER BY answered_at) - 1 as question_idx
            FROM quiz_answers
        )
        UPDATE quiz_answers
        SET question_index = ranked_answers.question_idx
        FROM ranked_answers
        WHERE quiz_answers.id = ranked_answers.id;
        """

        session.execute(text(update_sql))
        session.commit()

        print("✅ Successfully updated existing records!")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    add_question_index_column()
