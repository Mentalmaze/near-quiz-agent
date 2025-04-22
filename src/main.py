# Application entrypoint
from utils.config import Config
from bot.telegram_bot import TelegramBot


def main():
    """Initialize and start the Telegram quiz bot."""
    bot = TelegramBot(token=Config.TELEGRAM_TOKEN)
    bot.register_handlers()
    bot.start()


if __name__ == "__main__":
    main()
