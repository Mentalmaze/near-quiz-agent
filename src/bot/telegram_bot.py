import asyncio
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
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
            start_createquiz_group,
            topic_received,
            size_received,
            context_choice,
            context_input,
            duration_choice,
            duration_input,
            confirm_prompt,
            confirm_choice,
            TOPIC,
            SIZE,
            CONTEXT_CHOICE,
            CONTEXT_INPUT,
            DURATION_CHOICE,
            DURATION_INPUT,
            CONFIRM,
            link_wallet_handler,
            play_quiz_handler,
            quiz_answer_handler,
            private_message_handler,
            winners_handler,
            distribute_rewards_handler,
        )

        # Conversation for interactive quiz creation needs to be registered FIRST
        # to ensure it gets priority for handling messages
        logger.info("Registering conversation handler for quiz creation")
        conv = ConversationHandler(
            entry_points=[CommandHandler("createquiz", start_createquiz_group)],
            states={
                # In TOPIC state we only accept text messages in private chat
                TOPIC: [
                    MessageHandler(
                        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
                        topic_received,
                    )
                ],
                # In SIZE state we only accept text messages in private chat
                SIZE: [
                    MessageHandler(
                        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
                        size_received,
                    )
                ],
                # For callback queries, we don't need to filter by chat type as they're handled correctly
                CONTEXT_CHOICE: [
                    CallbackQueryHandler(
                        context_choice, pattern="^(paste|skip_context)$"
                    )
                ],
                # Text input for context should be in private chat
                CONTEXT_INPUT: [
                    MessageHandler(
                        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
                        context_input,
                    )
                ],
                # For callback queries, we don't need to filter by chat type
                DURATION_CHOICE: [
                    CallbackQueryHandler(
                        duration_choice, pattern="^(set_duration|skip_duration)$"
                    )
                ],
                # Text input for duration should be in private chat
                DURATION_INPUT: [
                    MessageHandler(
                        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
                        duration_input,
                    )
                ],
                # Final confirmation is a callback query
                CONFIRM: [CallbackQueryHandler(confirm_choice, pattern="^(yes|no)$")],
            },
            fallbacks=[
                CommandHandler(
                    "cancel", lambda update, context: ConversationHandler.END
                )
            ],
            # Allow the conversation to be restarted if the user runs /createquiz again
            allow_reentry=True,
            # Set a higher conversation timeout - default is 30s which is too short
            conversation_timeout=300,  # 5 minutes
            # Important: Set a name for debugging purposes
            name="quiz_creation",
            # Key conversation by user_id, not by chat_id, for group->DM flow
            per_chat=False,
            # Better mapping strategy for conversation states
            map_to_parent=True,
        )
        self.app.add_handler(conv)

        # Handle confirmation callbacks globally to catch any that might be missed by the conversation handler
        self.app.add_handler(CallbackQueryHandler(confirm_choice, pattern="^(yes|no)$"))
        
        # THEN register other command handlers
        logger.info("Registering command handlers")
        self.app.add_handler(CommandHandler("linkwallet", link_wallet_handler))
        self.app.add_handler(CommandHandler("playquiz", play_quiz_handler))
        self.app.add_handler(CommandHandler("winners", winners_handler))
        self.app.add_handler(
            CommandHandler("distributerewards", distribute_rewards_handler)
        )

        # Handle callback queries for quiz answers
        self.app.add_handler(CallbackQueryHandler(quiz_answer_handler))

        # Handle private text messages (MUST BE LAST as it's the most generic)
        # Only messages not handled by other handlers will reach this
        logger.info("Registering private message handler (lowest priority)")
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

        self.app.blockchain_monitor = self.blockchain_monitor

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
