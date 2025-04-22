from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes


class TelegramBot:
    def __init__(self, token: str):
        # Build the Telegram application
        self.app = ApplicationBuilder().token(token).build()

    def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log Errors caused by Updates."""
        print(f"Update {update} caused error {context.error}")

    def register_handlers(self):
        # Import handlers here to avoid circular dependencies
        from bot.handlers import (
            create_quiz_handler,
            # link_wallet_handler,
            play_quiz_handler,
        )

        # Register command handlers
        self.app.add_handler(CommandHandler("createquiz", create_quiz_handler))
        # self.app.add_handler(CommandHandler("linkwallet", link_wallet_handler))
        self.app.add_handler(CommandHandler("playquiz", play_quiz_handler))
        self.app.add_error_handler(self.error_handler)

    def start(self):
        """Start polling for updates."""
        print("Starting Telegram bot...")
        self.app.run_polling(3, drop_pending_updates=True)
