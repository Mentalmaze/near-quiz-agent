# Add src directory to sys.path for module resolution
import sys, os
import asyncio

sys.path.append(os.path.dirname(__file__))

# Application entrypoint
from utils.config import Config
from bot.telegram_bot import TelegramBot
from store.database import init_db


async def main_async():
    """Initialize and start the Telegram quiz bot asynchronously."""
    init_db()
    bot = TelegramBot(token=Config.TELEGRAM_TOKEN)
    bot.register_handlers()
    await bot.start()


def main():
    """Run the async main function."""
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
