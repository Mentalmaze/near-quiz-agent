# Application entrypoint
from utils.config import Config
from bot.telegram_bot import TelegramBot
from store.database import init_db


def main():
    """Initialize and start the Telegram quiz bot."""
    init_db()
    bot = TelegramBot(token=Config.TELEGRAM_TOKEN)
    bot.register_handlers()
    bot.start()


if __name__ == "__main__":
    main()
