# Add src directory to sys.path for module resolution
import sys, os
import asyncio
import logging

sys.path.append(os.path.dirname(__file__))

# Configure logging first
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# Application entrypoint
from utils.config import Config
from bot.telegram_bot import TelegramBot
from store.database import init_db, migrate_schema

logger = logging.getLogger(__name__)


async def main():
    """Start the bot and initialize necessary services."""

    # Try to migrate schema if using PostgreSQL
    if "postgresql" in Config.DATABASE_URL or "postgres" in Config.DATABASE_URL:
        logger.info("Attempting to migrate database schema for PostgreSQL...")
        migrate_schema()

    # Initialize database tables if they don't exist
    init_db()

    # Start telegram bot
    bot = TelegramBot(token=Config.TELEGRAM_TOKEN)
    bot.register_handlers()
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        sys.exit(1)
