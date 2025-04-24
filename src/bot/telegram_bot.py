import asyncio
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.ext import MessageHandler, filters
from telegram.error import TimedOut, NetworkError, RetryAfter, TelegramError, BadRequest
from services.blockchain import start_blockchain_monitor
import httpx
import traceback

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self, token: str):
        # Build the Telegram application with increased connection timeout and retry settings
        self.app = (
            ApplicationBuilder()
            .token(token)
            .get_updates_http_version("1.1")
            .http_version("1.1")
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .pool_timeout(30.0)
            .connection_pool_size(8)  # Increase connection pool size
            .build()
        )
        self.blockchain_monitor = None

    @staticmethod
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors raised during callback execution."""
        # Extract the error from context
        error = context.error

        try:
            if update:
                # If we have an update object, we can respond to the user
                if isinstance(error, TimedOut):
                    logger.warning(f"Timeout error when processing update {update}")
                    # Don't try to respond on timeout errors, it might cause another timeout
                    return

                if isinstance(error, NetworkError):
                    logger.error(
                        f"Network error when processing update {update}: {error}"
                    )
                    # Don't try to respond on network errors, it might cause another error
                    return

                if isinstance(error, TelegramError):
                    logger.error(
                        f"Telegram API error when processing update {update}: {error}"
                    )
            else:
                # We don't have an update object
                logger.error(f"Error without update object: {error}")

            # Log the full traceback for any error
            logger.error(f"Exception while handling an update:", exc_info=context.error)

        except Exception as e:
            # If error handling itself fails, log it but don't crash
            logger.error(f"Error in error handler: {e}")
            logger.error(traceback.format_exc())

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
        logger.info("Initializing blockchain monitor...")
        await self.init_blockchain()

        logger.info("Starting Telegram bot...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(
            drop_pending_updates=True,
            allowed_updates=[
                "message",
                "callback_query",
            ],  # Only process specific updates
            read_timeout=30,  # Increase read timeout
            timeout=30,  # Increase timeout
        )
        logger.info("Bot is running!")

        # Keep the application running with a simple infinite loop
        try:
            # Create a never-ending task
            stop_signal = asyncio.Future()
            await stop_signal
        except asyncio.CancelledError:
            # Handle graceful shutdown
            logger.info("Shutting down...")
            pass
        finally:
            # Ensure proper cleanup when the bot is stopped
            if self.blockchain_monitor:
                try:
                    await self.blockchain_monitor.stop_monitoring()
                except Exception as e:
                    logger.error(f"Error stopping blockchain monitor: {e}")
