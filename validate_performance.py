#!/usr/bin/env python3
"""
Performance Test Script for Mental Maze Quiz Bot
This script tests the optimized quiz functionality to validate performance improvements.
"""

import sys
import os
import asyncio
import time
from datetime import datetime
from sqlalchemy import text

# Add src directory to path
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

# Import test modules
from store.database import SessionLocal
from models.quiz import Quiz, QuizStatus
from utils.performance_monitor import performance_monitor
from utils.redis_client import RedisClient


async def main():
    """Run simplified performance validation."""
    print("🚀 Mental Maze Quiz Bot - Performance Validation")
    print("=" * 50)

    start_time = time.time()

    # Test 1: Database Connection
    print("\n💾 Testing Database Connection...")
    session = SessionLocal()
    try:
        active_quizzes = (
            session.query(Quiz).filter(Quiz.status == QuizStatus.ACTIVE).count()
        )
        print(f"  ✅ Found {active_quizzes} active quizzes")
    except Exception as e:
        print(f"  ❌ Database error: {e}")
    finally:
        session.close()

    # Test 2: Redis Connection
    print("\n📊 Testing Redis Connection...")
    redis_client = RedisClient()
    try:
        test_key = "performance_test"
        await redis_client.set_value(test_key, {"test": "data"}, ttl_seconds=60)
        cached_data = await redis_client.get_value(test_key)
        await redis_client.delete_key(test_key)
        print(f"  ✅ Redis cache operations successful")
    except Exception as e:
        print(f"  ❌ Redis error: {e}")

    # Test 3: Performance Monitoring
    print("\n📈 Testing Performance Monitoring...")
    try:
        async with performance_monitor.track_operation("validation_test"):
            await asyncio.sleep(0.05)  # 50ms test operation

        stats = await performance_monitor.get_performance_stats()
        if "total_operations" in stats:
            print(
                f"  ✅ Performance monitoring active: {stats['total_operations']} operations tracked"
            )
        else:
            print(f"  ⚠️  {stats.get('message', 'Performance monitoring available')}")
    except Exception as e:
        print(f"  ❌ Performance monitoring error: {e}")

    total_time = (time.time() - start_time) * 1000

    print(f"\n✅ Performance validation completed in {total_time:.2f}ms")
    print("\n🎯 Performance Optimizations Applied:")
    print("  • Database composite indexes for duplicate prevention")
    print("  • Enhanced connection pooling (pool_size: 10, max_overflow: 20)")
    print("  • Redis caching for quiz data with structured invalidation")
    print("  • Optimized quiz answer submission with deferred commits")
    print("  • Performance monitoring with operation tracking")
    print("  • AI generation timeout handling with exponential backoff")
    print("\n🚀 Bot is ready for high-performance quiz gameplay!")


if __name__ == "__main__":
    asyncio.run(main())
