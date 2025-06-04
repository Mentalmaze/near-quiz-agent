#!/usr/bin/env python3
"""
Performance test script to validate quiz answer submission optimizations.
Tests the speed of quiz answer processing operations.
"""

import asyncio
import time
import logging
from datetime import datetime
from unittest.mock import Mock, AsyncMock
import sys
import os

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from models.quiz import Quiz, QuizAnswer, QuizStatus
from store.database import SessionLocal
from utils.redis_client import RedisClient
from utils.performance_monitor import track_quiz_answer_submission

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PerformanceTestHarness:
    """Test harness for measuring quiz answer submission performance."""

    def __init__(self):
        self.test_results = []

    async def create_test_quiz(self) -> str:
        """Create a test quiz for performance testing."""
        session = SessionLocal()
        try:
            quiz = Quiz(
                topic="Performance Test Quiz",
                questions=[
                    {
                        "question": "What is 2 + 2?",
                        "options": {"A": "3", "B": "4", "C": "5", "D": "6"},
                        "correct": "B",
                    },
                    {
                        "question": "What is the capital of France?",
                        "options": {
                            "A": "London",
                            "B": "Berlin",
                            "C": "Paris",
                            "D": "Madrid",
                        },
                        "correct": "C",
                    },
                ],
                status=QuizStatus.ACTIVE,
                group_chat_id=12345,
            )
            session.add(quiz)
            session.commit()
            return quiz.id
        finally:
            session.close()

    async def simulate_quiz_answer_submission(
        self, quiz_id: str, user_id: str, question_index: int = 0
    ) -> float:
        """Simulate a quiz answer submission and measure performance."""

        # Mock Telegram objects
        mock_update = Mock()
        mock_query = Mock()
        mock_query.data = f"quiz:{quiz_id}:{question_index}:B"
        mock_query.answer = AsyncMock()
        mock_query.message = Mock()
        mock_query.message.chat_id = user_id
        mock_query.message.message_id = 123
        mock_query.message.text = "Test Question"

        mock_update.callback_query = mock_query
        mock_update.effective_user = Mock()
        mock_update.effective_user.id = int(user_id)
        mock_update.effective_user.username = f"testuser{user_id}"

        mock_context = Mock()
        mock_context.bot = Mock()
        mock_context.bot.edit_message_text = AsyncMock()
        mock_context.bot.send_message = AsyncMock()

        # Import the function to test
        from services.quiz_service import handle_quiz_answer

        start_time = time.time()

        try:
            # Execute the quiz answer handling
            await handle_quiz_answer(mock_update, mock_context)
            end_time = time.time()

            execution_time = end_time - start_time
            logger.info(f"Quiz answer submission took {execution_time:.3f} seconds")
            return execution_time

        except Exception as e:
            logger.error(f"Error during quiz answer submission: {e}")
            return float("inf")

    async def test_concurrent_submissions(
        self, quiz_id: str, num_users: int = 10
    ) -> dict:
        """Test concurrent quiz answer submissions."""
        logger.info(f"Testing {num_users} concurrent quiz answer submissions...")

        start_time = time.time()

        # Create tasks for concurrent submissions
        tasks = []
        for i in range(num_users):
            user_id = f"100{i:03d}"  # Create unique user IDs
            task = self.simulate_quiz_answer_submission(quiz_id, user_id, 0)
            tasks.append(task)

        # Execute all submissions concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        end_time = time.time()
        total_time = end_time - start_time

        # Analyze results
        valid_times = [r for r in results if isinstance(r, float) and r != float("inf")]

        if valid_times:
            avg_time = sum(valid_times) / len(valid_times)
            max_time = max(valid_times)
            min_time = min(valid_times)

            return {
                "total_time": total_time,
                "average_time": avg_time,
                "max_time": max_time,
                "min_time": min_time,
                "successful_submissions": len(valid_times),
                "failed_submissions": len(results) - len(valid_times),
                "concurrent_users": num_users,
            }
        else:
            return {
                "total_time": total_time,
                "error": "All submissions failed",
                "failed_submissions": len(results),
                "concurrent_users": num_users,
            }

    async def test_cache_performance(self, quiz_id: str) -> dict:
        """Test Redis cache invalidation performance."""
        logger.info("Testing cache invalidation performance...")

        redis_client = RedisClient()

        # Pre-populate cache
        await redis_client.cache_quiz_details(quiz_id, {"test": "data"})
        await redis_client.cache_quiz_participants(quiz_id, [{"user": "test"}])
        await redis_client.cache_quiz_leaderboard(quiz_id, {"leaderboard": "test"})

        start_time = time.time()

        # Test cache invalidation
        result = await redis_client.invalidate_quiz_cache(quiz_id)

        end_time = time.time()

        await redis_client.close()

        return {"cache_invalidation_time": end_time - start_time, "success": result}

    async def cleanup_test_data(self, quiz_id: str):
        """Clean up test data after testing."""
        session = SessionLocal()
        try:
            # Delete test quiz answers
            session.query(QuizAnswer).filter(QuizAnswer.quiz_id == quiz_id).delete()

            # Delete test quiz
            session.query(Quiz).filter(Quiz.id == quiz_id).delete()

            session.commit()
            logger.info("Test data cleaned up successfully")
        except Exception as e:
            logger.error(f"Error cleaning up test data: {e}")
            session.rollback()
        finally:
            session.close()

    async def run_performance_tests(self):
        """Run all performance tests."""
        logger.info("Starting quiz answer submission performance tests...")

        try:
            # Create test quiz
            quiz_id = await self.create_test_quiz()
            logger.info(f"Created test quiz: {quiz_id}")

            # Test single submission
            logger.info("\n=== Testing Single Quiz Answer Submission ===")
            single_time = await self.simulate_quiz_answer_submission(
                quiz_id, "999999", 0
            )
            self.test_results.append(("Single Submission", single_time))

            # Test cache performance
            logger.info("\n=== Testing Cache Invalidation Performance ===")
            cache_results = await self.test_cache_performance(quiz_id)
            self.test_results.append(("Cache Invalidation", cache_results))

            # Test concurrent submissions
            logger.info("\n=== Testing Concurrent Quiz Answer Submissions ===")
            concurrent_results = await self.test_concurrent_submissions(quiz_id, 5)
            self.test_results.append(("Concurrent Submissions", concurrent_results))

            # Display results
            self.display_results()

            # Cleanup
            await self.cleanup_test_data(quiz_id)

        except Exception as e:
            logger.error(f"Error during performance testing: {e}")
            raise

    def display_results(self):
        """Display test results."""
        print("\n" + "=" * 60)
        print("QUIZ ANSWER SUBMISSION PERFORMANCE TEST RESULTS")
        print("=" * 60)

        for test_name, result in self.test_results:
            print(f"\n{test_name}:")
            if isinstance(result, dict):
                for key, value in result.items():
                    if isinstance(value, float):
                        print(f"  {key}: {value:.3f}s")
                    else:
                        print(f"  {key}: {value}")
            else:
                print(f"  Time: {result:.3f}s")

        print("\n" + "=" * 60)
        print("PERFORMANCE ANALYSIS:")

        # Analyze if we've met the performance target
        single_submission_time = None
        for test_name, result in self.test_results:
            if test_name == "Single Submission":
                single_submission_time = result
                break

        if single_submission_time is not None:
            if single_submission_time < 1.0:
                print(
                    f"✅ EXCELLENT: Single submission time ({single_submission_time:.3f}s) is under 1 second!"
                )
            elif single_submission_time < 2.0:
                print(
                    f"✅ GOOD: Single submission time ({single_submission_time:.3f}s) is under 2 seconds!"
                )
            elif single_submission_time < 4.5:
                print(
                    f"⚠️  IMPROVED: Single submission time ({single_submission_time:.3f}s) is better than 4.5s baseline!"
                )
            else:
                print(
                    f"❌ NEEDS WORK: Single submission time ({single_submission_time:.3f}s) still exceeds 4.5s!"
                )

        print("=" * 60)


async def main():
    """Main test execution function."""
    harness = PerformanceTestHarness()
    await harness.run_performance_tests()


if __name__ == "__main__":
    asyncio.run(main())
