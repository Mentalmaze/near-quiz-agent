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
    def __init__(
        self,
        token: str,
        webhook_url: str = None,
        webhook_listen_ip: str = None,
        webhook_port: int = None,
        webhook_url_path: str = None,
    ):
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
        self.webhook_url = webhook_url
        self.webhook_listen_ip = webhook_listen_ip
        self.webhook_port = webhook_port
        self.webhook_url_path = webhook_url_path

        self._stop_signal = asyncio.Future()  # For graceful shutdown signal

    @staticmethod
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle errors raised during callback execution."""
        # Extract the error from context
        error = context.error

        try:
            if update:
        
                if isinstance(error, TimedOut):
                    logger.warning(f"Timeout error when processing update {update}")
                    # Prompt user to retry when a timeout occurs
                    try:
                        if isinstance(update, Update) and update.effective_chat:
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text="⏱️ Sorry, that operation took too long. Please reenter the last text again.",
                            )
                    except Exception as e:
                        logger.error(f"Failed to notify user of timeout: {e}")
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
            unlink_wallet_handler,
            play_quiz_handler,
            play_quiz_selection_callback,  # New multi-quiz selection handler
            quiz_answer_handler,
            private_message_handler,
            winners_handler,
            distribute_rewards_handler,
            start_reward_setup_callback,  # Import new reward setup handlers
            handle_reward_method_choice,
            show_all_active_leaderboards_command,
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

        # Handle reward setup initiation callback
        self.app.add_handler(
            CallbackQueryHandler(
                start_reward_setup_callback, pattern="^reward_setup_start:"
            )
        )
        # Handle reward method choices
        self.app.add_handler(
            CallbackQueryHandler(handle_reward_method_choice, pattern="^reward_method:")
        )

        # THEN register other command handlers
        logger.info("Registering command handlers")
        self.app.add_handler(CommandHandler("linkwallet", link_wallet_handler))
        self.app.add_handler(
            CommandHandler("unlinkwallet", unlink_wallet_handler)
        )  # Register the new handler
        self.app.add_handler(CommandHandler("playquiz", play_quiz_handler))
        self.app.add_handler(CommandHandler("winners", winners_handler))
        self.app.add_handler(
            CommandHandler("leaderboards", show_all_active_leaderboards_command)
        )

        # self.app.add_handler(
        #     CommandHandler("distributerewards", distribute_rewards_handler)
        # )

        # Handle callback queries for quiz answers
        self.app.add_handler(
            CallbackQueryHandler(quiz_answer_handler, pattern=r"^quiz:")
        )

        # New: handle quiz selection callback when multiple quizzes are active in a group
        self.app.add_handler(
            CallbackQueryHandler(
                play_quiz_selection_callback, pattern=r"^playquiz_select:"
            )
        )

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
        # Confirm monitor was attached correctly
        logger.info(
            f"[init_blockchain] application.blockchain_monitor is set: {self.app.blockchain_monitor}"
        )

    async def start(self):
        """Start the bot using webhook or polling, and initialize services."""
        logger.info("Initializing blockchain monitor...")
        await self.init_blockchain()

        await self.app.initialize()
        await self.app.start()

        allowed_updates_list = ["message", "callback_query"]

        if (
            self.webhook_url
            and self.webhook_listen_ip
            and self.webhook_port
            and self.webhook_url_path
        ):
            logger.info(
                f"Starting Telegram bot in WEBHOOK mode. Base URL: {self.webhook_url}, Path: {self.webhook_url_path}, Listen IP: {self.webhook_listen_ip}, Port: {self.webhook_port}"
            )

            max_retries = 3
            retry_delay = 5  # seconds
            current_port = self.webhook_port
            # Try to delete any existing webhook before setting a new one to prevent conflicts
            try:
                logger.info("Removing any existing webhook...")
                await self.app.bot.delete_webhook(drop_pending_updates=True)
            except Exception as e:
                logger.warning(f"Failed to delete existing webhook: {e}")

            # Start the webhook server with retry logic for port binding
            for retry in range(max_retries):
                try:
                    logger.info(
                        f"Attempt {retry + 1}/{max_retries} to start webhook on port {current_port}"
                    )
                    await self.app.updater.start_webhook(
                        listen=self.webhook_listen_ip,
                        port=current_port,
                        url_path=self.webhook_url_path,  # We need to specify this explicitly
                        webhook_url=f"{self.webhook_url}/{self.webhook_url_path}",
                        allowed_updates=allowed_updates_list,
                        drop_pending_updates=True,
                    )
                    logger.info(
                        f"Webhook server set up to listen on {self.webhook_listen_ip}:{current_port} for path /{self.webhook_url_path} and registered with URL {self.webhook_url}/{self.webhook_url_path}"
                    )
                    # Success! Break out of retry loop
                    break
                except OSError as e:
                    if e.errno == 98:  # Address already in use
                        current_port = current_port + 1
                        logger.warning(
                            f"Port {current_port - 1} is already in use. Trying port {current_port}..."
                        )
                        if retry == max_retries - 1:
                            # This was our last retry
                            logger.error(
                                f"All ports in range {self.webhook_port} to {current_port} are in use."
                            )
                            raise
                        await asyncio.sleep(retry_delay)
                    else:
                        # Some other OSError occurred
                        logger.error(f"OSError when starting webhook: {e}")
                        raise
                except Exception as e:
                    logger.error(f"Failed to start webhook: {e}", exc_info=True)
                    raise

            # Since start_webhook is blocking, the bot will run until updater.stop() is called.
            try:
                await self._stop_signal  # This will block until stop() is called
            except asyncio.CancelledError:
                logger.info("Webhook stop signal received via CancelledError.")
            finally:
                logger.info("Webhook event loop part ended.")
        else:
            logger.info("Starting Telegram bot in POLLING mode.")
            await self.app.updater.start_polling(
                drop_pending_updates=True,
                allowed_updates=allowed_updates_list,
            )
            logger.info("Bot is running with polling!")
            # Keep the application running with polling
            try:
                await self._stop_signal  # Wait for stop signal
            except asyncio.CancelledError:
                logger.info("Polling stop signal received via CancelledError.")
            finally:
                logger.info("Polling loop ended.")

    async def stop(self):
        """Gracefully stop the bot and its services."""
        logger.info("Attempting to gracefully stop the bot...")

        # Signal the polling loop to stop if it's waiting on _stop_signal
        if not self._stop_signal.done():
            self._stop_signal.set_result(True)

        if self.blockchain_monitor:
            try:
                logger.info("Stopping blockchain monitor...")
                await self.blockchain_monitor.stop_monitoring()
                logger.info("Blockchain monitor stopped.")
            except Exception as e:
                logger.error(f"Error stopping blockchain monitor: {e}", exc_info=True)

        if self.app.updater and self.app.updater.running:
            logger.info("Stopping Telegram updater (polling/webhook)...")
            await self.app.updater.stop()
            logger.info("Telegram updater stopped.")

        if self.webhook_url:
            try:
                logger.info(
                    f"Attempting to delete webhook: {self.webhook_url}/{self.webhook_url_path}"
                )
                # Only delete if a webhook was actually set by this instance
                # Check if bot is not None and has a last_webhook_info or similar attribute if available,
                # or just attempt deletion.
                if await self.app.bot.delete_webhook(drop_pending_updates=True):
                    logger.info("Webhook deleted successfully.")
                else:
                    logger.warning("Failed to delete webhook or no webhook was set.")
            except Exception as e:
                logger.error(f"Error deleting webhook: {e}", exc_info=True)

        if self.app.running:  # Check if application is running before stopping
            logger.info("Stopping Telegram application...")
            await self.app.stop()
            logger.info("Telegram application stopped.")

        logger.info("Shutting down Telegram application...")
        await self.app.shutdown()
        logger.info("Telegram application shut down.")

        logger.info("Bot shutdown process complete.")
