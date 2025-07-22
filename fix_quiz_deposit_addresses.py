#!/usr/bin/env python3
"""
Fix existing quizzes that have NULL deposit_address.
This script updates any quiz records that don't have a deposit_address set.
"""

import sys
import os

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from store.database import SessionLocal
from models.quiz import Quiz
from utils.config import Config
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fix_quiz_deposit_addresses():
    """Fix any quizzes that have NULL deposit_address."""
    if not Config.DEPOSIT_ADDRESS:
        logger.error("DEPOSIT_ADDRESS is not configured in Config. Cannot proceed.")
        return False

    session = SessionLocal()
    try:
        # Find quizzes with NULL deposit_address
        quizzes_to_fix = session.query(Quiz).filter(Quiz.deposit_address == None).all()

        if not quizzes_to_fix:
            logger.info("No quizzes found with NULL deposit_address. Nothing to fix.")
            return True

        logger.info(
            f"Found {len(quizzes_to_fix)} quizzes with NULL deposit_address. Fixing..."
        )

        # Update each quiz
        for quiz in quizzes_to_fix:
            quiz.deposit_address = Config.DEPOSIT_ADDRESS
            logger.info(
                f"Updated quiz {quiz.id} ({quiz.topic}) with deposit_address: {Config.DEPOSIT_ADDRESS}"
            )

        # Commit all changes
        session.commit()
        logger.info(
            f"Successfully updated {len(quizzes_to_fix)} quiz(s) with deposit addresses."
        )
        return True

    except Exception as e:
        logger.error(f"Error fixing quiz deposit addresses: {e}")
        session.rollback()
        return False
    finally:
        session.close()


if __name__ == "__main__":
    logger.info(
        f"Starting quiz deposit address fix. Using deposit address: {Config.DEPOSIT_ADDRESS}"
    )

    if fix_quiz_deposit_addresses():
        logger.info("✅ Quiz deposit address fix completed successfully.")
    else:
        logger.error("❌ Quiz deposit address fix failed.")
        sys.exit(1)
