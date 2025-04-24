import asyncio
from datetime import datetime, timedelta
from models.quiz import Quiz, QuizStatus
from store.database import SessionLocal
from utils.config import Config
import traceback


class BlockchainMonitor:
    """
    Simulated blockchain monitor - in a real implementation, this would connect to a NEAR RPC
    node and monitor for transactions to quiz deposit addresses.
    """

    def __init__(self, bot):
        """Initialize with access to the bot for sending notifications."""
        self.bot = bot
        self._running = False
        self._monitor_task = None

    async def start_monitoring(self):
        """Start the blockchain monitoring service."""
        if self._running:
            return

        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        print("Blockchain monitor started")

    async def stop_monitoring(self):
        """Stop the blockchain monitoring service."""
        if not self._running:
            return

        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        print("Blockchain monitor stopped")

    async def _monitor_loop(self):
        """Continuously monitor for deposits to quiz addresses."""
        while self._running:
            try:
                # Check for quizzes in FUNDING status
                session = SessionLocal()
                try:
                    funding_quizzes = (
                        session.query(Quiz)
                        .filter(
                            Quiz.status == QuizStatus.FUNDING,
                            Quiz.deposit_address != None,
                        )
                        .all()
                    )

                    # Important: Load all necessary attributes while session is active
                    # and create a list of quiz IDs to process
                    quiz_ids_to_process = []
                    for quiz in funding_quizzes:
                        quiz_ids_to_process.append(quiz.id)
                finally:
                    session.close()

                # Process each quiz with its own session
                for quiz_id in quiz_ids_to_process:
                    await self._check_deposit(quiz_id)

                # Check every 30 seconds (would be longer in production)
                await asyncio.sleep(30)
            except Exception as e:
                print(f"Error in blockchain monitor: {e}")
                traceback.print_exc()
                await asyncio.sleep(30)

    async def _check_deposit(self, quiz_id):
        """
        Simulate checking for deposits to a quiz address.

        In a real implementation, this would query the NEAR RPC for transactions
        to the deposit address and verify sufficient funds were received.
        """
        # Open a new session for this operation
        session = SessionLocal()
        try:
            # Reload the quiz to get current state
            quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
            if not quiz or quiz.status != QuizStatus.FUNDING:
                return

            # Check if quiz has been in FUNDING status for more than 1 minute
            # In a real implementation, we would check the blockchain for actual deposits
            if datetime.utcnow() - quiz.last_updated > timedelta(minutes=1):
                # Update quiz to ACTIVE and commit immediately
                quiz.status = QuizStatus.ACTIVE
                total_reward = (
                    sum(int(value) for value in quiz.reward_schedule.values())
                    if quiz.reward_schedule
                    else 0
                )
                group_chat_id = quiz.group_chat_id
                topic = quiz.topic

                session.commit()
                session.close()
                session = None  # Prevent further usage

                # Announce the quiz is active in the original group chat
                try:
                    if group_chat_id:
                        # Use longer timeout for the announcement
                        async with asyncio.timeout(10):  # 10 second timeout
                            await self.bot.send_message(
                                chat_id=group_chat_id,
                                text=f"📣 New quiz '{topic}' is now active! 🎯\n"
                                f"Total rewards: {total_reward} NEAR\n"
                                f"Type /playquiz to participate!",
                            )
                except asyncio.TimeoutError:
                    print(f"Failed to announce active quiz: Timed out")
                except Exception as e:
                    print(f"Failed to announce active quiz: {e}")
                    traceback.print_exc()
        except Exception as e:
            print(f"Error checking deposit: {e}")
            traceback.print_exc()
        finally:
            # Always ensure session is closed
            if session is not None:
                session.close()


# To be called during bot initialization
async def start_blockchain_monitor(bot):
    """Initialize and start the blockchain monitor with the bot instance."""
    monitor = BlockchainMonitor(bot)
    await monitor.start_monitoring()
    return monitor
