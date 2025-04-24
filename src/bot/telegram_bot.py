from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.ext import MessageHandler, filters
from services.blockchain import start_blockchain_monitor
import httpx
import asyncio


class TelegramBot:
    def __init__(self, token: str):
        # Build the Telegram application with increased connection timeout
        self.app = (
            ApplicationBuilder()
            .token(token)
            .get_updates_http_version("1.1")
            .http_version("1.1")
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .pool_timeout(30.0)
            .build()
        )
        self.blockchain_monitor = None

    @staticmethod
    def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Log Errors caused by Updates."""
        print(f"Update {update} caused error {context.error}")

    def register_handlers(self):
        # Import handlers here to avoid circular dependencies
        from bot.handlers import (
            create_quiz_handler,
            link_wallet_handler,
            play_quiz_handler,
            quiz_answer_handler,
            private_message_handler,
            winners_handler,
        )

        # Register command handlers
        self.app.add_handler(CommandHandler("createquiz", create_quiz_handler))
        self.app.add_handler(CommandHandler("linkwallet", link_wallet_handler))
        self.app.add_handler(CommandHandler("playquiz", play_quiz_handler))
        self.app.add_handler(CommandHandler("winners", winners_handler))

        # Handle callback queries (for quiz answers)
        self.app.add_handler(CallbackQueryHandler(quiz_answer_handler))

        # Handle private text messages (e.g., reward structure inputs, wallet addresses)
        self.app.add_handler(
            MessageHandler(
                filters.ChatType.PRIVATE & filters.TEXT & ~filters.COMMAND,
                private_message_handler,
            )
        )

        # Register error handler
        self.app.add_error_handler(self.error_handler)

    async def init_blockchain(self):
        """Initialize the blockchain monitor."""
        self.blockchain_monitor = await start_blockchain_monitor(self.app.bot)

    async def start(self):
        """Start polling for updates and initialize services."""
        print("Initializing blockchain monitor...")
        await self.init_blockchain()

        print("Starting Telegram bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        print("Bot is running!")

        # Keep the application running with a simple infinite loop
        # This replaces the problematic wait_until_stopped() call
        try:
            # Create a never-ending task
            stop_signal = asyncio.Future()
            await stop_signal
        except asyncio.CancelledError:
            # Handle graceful shutdown
            pass
        finally:
            # Ensure proper cleanup when the bot is stopped
            if self.blockchain_monitor:
                try:
                    await self.blockchain_monitor.stop_monitoring()
                except Exception as e:
                    print(f"Error stopping blockchain monitor: {e}")
