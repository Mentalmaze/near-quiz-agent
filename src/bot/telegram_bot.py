from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext


class TelegramBot:
    def __init__(self, token: str):
        self.updater = Updater(token)
        self.dispatcher = self.updater.dispatcher

    def register_handlers(self):
        # Import handlers here to avoid circular dependencies
        from bot.handlers import (
            create_quiz_handler,
            link_wallet_handler,
            play_quiz_handler,
        )

        self.dispatcher.add_handler(CommandHandler("createquiz", create_quiz_handler))
        self.dispatcher.add_handler(CommandHandler("linkwallet", link_wallet_handler))
        self.dispatcher.add_handler(CommandHandler("playquiz", play_quiz_handler))

    def start(self):
        """Start polling for updates."""
        self.updater.start_polling()
        self.updater.idle()
