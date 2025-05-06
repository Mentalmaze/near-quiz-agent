import asyncio
import os
import time
import logging
from datetime import datetime, timedelta
from models.quiz import Quiz, QuizStatus
from store.database import SessionLocal
from utils.config import Config
import traceback
from typing import Dict, List, Optional

from py_near.account import Account

# Import py-near components
# from pynear.account import Account
from py_near.dapps.core import NEAR

logger = logging.getLogger(__name__)


class BlockchainMonitor:
    """
    NEAR blockchain monitor - connects to NEAR RPC nodes to monitor transactions
    and handle deposits/withdrawals for quiz rewards.
    """

    def __init__(self, bot):
        """Initialize with access to the bot for sending notifications."""
        self.bot = bot
        self._running = False
        self._monitor_task = None
        self.near_account: Optional[Account] = None
        self._init_near_account()

    def _init_near_account(self):
        """Initialize NEAR account for blockchain operations."""
        try:
            private_key = Config.NEAR_WALLET_PRIVATE_KEY
            account_id = Config.NEAR_WALLET_ADDRESS
            rpc_addr = Config.NEAR_RPC_ENDPOINT

            if not private_key or not account_id:
                logger.error("Missing NEAR wallet credentials in configuration")
                return

            if not rpc_addr:
                logger.error("Missing NEAR RPC endpoint in configuration")
                return

            # Initialize the NEAR account
            self.near_account = Account(account_id, private_key, rpc_addr=rpc_addr)
            logger.info(f"NEAR account initialized with address: {account_id}")
        except Exception as e:
            logger.error(f"Failed to initialize NEAR account: {e}")
            traceback.print_exc()

    async def startup_near_account(self):
        """Start up the NEAR account connection."""
        if not self.near_account:
            logger.error("Cannot start NEAR account - not initialized")
            return False

        try:
            # Initialize connection to NEAR blockchain
            await self.near_account.startup()
            balance = await self.near_account.get_balance()
            logger.info(
                f"Connected to NEAR blockchain. Account balance: {balance/NEAR:.4f} NEAR"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to connect to NEAR blockchain: {e}")
            traceback.print_exc()
            return False

    async def start_monitoring(self):
        """Start the blockchain monitoring service."""
        # Initialize NEAR connection first
        if not await self.startup_near_account():
            logger.error(
                "Failed to start blockchain monitor due to NEAR connection failure"
            )
            return
            
        logger.info("Blockchain monitor initialized - no automatic monitoring enabled, using manual verification only")
        return

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
        logger.info("Blockchain monitor stopped")

    # We're keeping the monitor_loop and _check_deposit methods for backwards compatibility
    # but they won't be automatically used anymore

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

                # Check every 60 seconds
                await asyncio.sleep(60)
            except Exception as e:
                logger.error(f"Error in blockchain monitor: {e}")
                traceback.print_exc()
                await asyncio.sleep(60)

    async def _check_deposit(self, quiz_id):
        """
        Check for deposits to a quiz address on the NEAR blockchain.

        Verifies if sufficient funds were received using NEAR RPC calls.
        """
        if not self.near_account:
            logger.error("Cannot check deposits - NEAR account not initialized")
            return

        # Open a new session for this operation
        session = SessionLocal()
        try:
            # Reload the quiz to get current state
            quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
            if not quiz or quiz.status != QuizStatus.FUNDING:
                return

            deposit_address = quiz.deposit_address
            required_amount = (
                sum(int(value) for value in quiz.reward_schedule.values())
                if quiz.reward_schedule
                else 0
            )

            # Use py-near to check the blockchain for deposits
            try:
                # Fetch the balance of the deposit address
                deposit_balance = await self.near_account.get_balance(deposit_address)
                logger.info(
                    f"Checked balance for quiz {quiz_id}: {deposit_balance/NEAR:.4f} NEAR"
                )

                # Check if sufficient funds received
                if deposit_balance >= required_amount * NEAR:
                    # Update quiz to ACTIVE and commit immediately
                    quiz.status = QuizStatus.ACTIVE
                    total_reward = required_amount
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
                                logger.info(
                                    f"Quiz {quiz_id} activated with {total_reward} NEAR"
                                )
                    except asyncio.TimeoutError:
                        logger.error(f"Failed to announce active quiz: Timed out")
                    except Exception as e:
                        logger.error(f"Failed to announce active quiz: {e}")
                        traceback.print_exc()
                else:
                    logger.debug(
                        f"Insufficient funds for quiz {quiz_id}: {deposit_balance/NEAR:.4f}/{required_amount} NEAR"
                    )
            except Exception as e:
                logger.error(f"Error checking blockchain for deposits: {e}")
                traceback.print_exc()

        except Exception as e:
            logger.error(f"Error checking deposit: {e}")
            traceback.print_exc()
        finally:
            # Always ensure session is closed
            if session is not None:
                session.close()

    async def distribute_rewards(self, quiz_id: str) -> bool:
        """
        Distribute rewards to quiz winners based on the defined reward schedule.

        Args:
            quiz_id: ID of the quiz to distribute rewards for

        Returns:
            bool: True if rewards were successfully distributed, False otherwise
        """
        if not self.near_account:
            logger.error("Cannot distribute rewards - NEAR account not initialized")
            return False

        # Open a new session for this operation
        session = SessionLocal()
        try:
            # Get quiz data and confirm it's in ACTIVE status
            quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
            if not quiz:
                logger.error(f"Quiz {quiz_id} not found")
                return False

            if quiz.status == QuizStatus.CLOSED:
                logger.info(f"Quiz {quiz_id} already closed and rewards distributed")
                return True

            if quiz.status != QuizStatus.ACTIVE:
                logger.error(
                    f"Quiz {quiz_id} not in ACTIVE state, cannot distribute rewards"
                )
                return False

            # Get winners from database
            from models.quiz import QuizAnswer

            winners = QuizAnswer.compute_quiz_winners(session, quiz_id)
            if not winners:
                logger.warning(f"No winners found for quiz {quiz_id}")
                return False

            # Get wallet addresses for winners
            from models.user import User

            reward_schedule = quiz.reward_schedule

            # Track successful transfers
            successful_transfers = []

            # Process each winner according to reward schedule
            for rank, winner_data in enumerate(winners, 1):
                user_id = winner_data["user_id"]
                user = session.query(User).filter(User.id == user_id).first()

                # Skip if no wallet linked
                if not user or not user.wallet_address:
                    logger.warning(f"No wallet linked for user {user_id}, rank {rank}")
                    continue

                # Check if there's a reward for this rank
                reward_amount = None
                if str(rank) in reward_schedule:
                    reward_amount = int(reward_schedule[str(rank)])
                elif rank in reward_schedule:
                    reward_amount = int(reward_schedule[rank])

                if not reward_amount:
                    logger.debug(f"No reward defined for rank {rank}")
                    continue

                # Send NEAR to the winner's wallet
                try:
                    logger.info(
                        f"Sending {reward_amount} NEAR to {user.wallet_address} (rank {rank})"
                    )

                    # Convert to yoctoNEAR (1 NEAR = 10^24 yoctoNEAR)
                    yocto_amount = reward_amount * NEAR

                    # Execute transfer
                    transaction = await self.near_account.send_money(
                        user.wallet_address, yocto_amount
                    )

                    # Record successful transfer
                    successful_transfers.append(
                        {
                            "user_id": user_id,
                            "wallet": user.wallet_address,
                            "amount": reward_amount,
                            "tx_hash": transaction.transaction.hash,
                        }
                    )

                    logger.info(
                        f"Successfully sent {reward_amount} NEAR to {user.wallet_address}, tx: {transaction.transaction.hash}"
                    )

                except Exception as e:
                    logger.error(
                        f"Failed to transfer {reward_amount} NEAR to {user.wallet_address}: {e}"
                    )
                    traceback.print_exc()

            # If at least some transfers were successful, mark quiz as closed
            if successful_transfers:
                quiz.status = QuizStatus.CLOSED
                session.commit()

                # Announce winners in group chat
                if quiz.group_chat_id:
                    winners_text = "🏆 Quiz Results! 🏆\n\n"

                    for rank, winner in enumerate(winners[:3], 1):  # Show top 3
                        username = winner["username"] or f"User{winner['user_id'][-4:]}"
                        reward = (
                            reward_schedule.get(str(rank))
                            or reward_schedule.get(rank)
                            or "0"
                        )

                        # Check if this user received payment
                        paid_status = (
                            "✅"
                            if any(
                                t["user_id"] == winner["user_id"]
                                for t in successful_transfers
                            )
                            else "⏳"
                        )
                        winners_text += f"{rank}. @{username}: {winner['correct_count']} correct - {reward} NEAR {paid_status}\n"

                    try:
                        await self.bot.send_message(
                            chat_id=quiz.group_chat_id,
                            text=winners_text
                            + "\n💰 Rewards have been distributed to winners' NEAR wallets!",
                        )
                    except Exception as e:
                        logger.error(f"Failed to announce winners: {e}")

                return True
            return False

        except Exception as e:
            logger.error(f"Error distributing rewards for quiz {quiz_id}: {e}")
            traceback.print_exc()
            return False
        finally:
            if session:
                session.close()

    async def verify_transaction_by_hash(self, tx_hash: str, quiz_id: str) -> bool:
        """
        Verify a transaction by its hash to confirm a deposit was made.

        Args:
            tx_hash: The transaction hash to verify
            quiz_id: The quiz ID the deposit is for

        Returns:
            bool: True if the transaction is valid and has sufficient funds, False otherwise
        """
        if not self.near_account:
            logger.error("Cannot verify transaction - NEAR account not initialized")
            return False

        try:
            # Open a new session for this operation
            session = SessionLocal()
            try:
                # Get quiz data
                quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
                if not quiz:
                    logger.error(f"Quiz {quiz_id} not found")
                    return False

                if quiz.status != QuizStatus.FUNDING:
                    logger.info(f"Quiz {quiz_id} is not in FUNDING state")
                    return False

                deposit_address = quiz.deposit_address
                required_amount = (
                    sum(int(value) for value in quiz.reward_schedule.values())
                    if quiz.reward_schedule
                    else 0
                )

                # Use NEAR RPC to verify the transaction
                try:
                    # Get transaction status to verify it exists and is successful
                    tx_info = await self.near_account.provider.get_transaction(tx_hash)

                    # Check if transaction exists and was successful
                    if not tx_info or "status" not in tx_info:
                        logger.warning(
                            f"Transaction {tx_hash} not found or status missing"
                        )
                        return False

                    # Check if the transaction is a success
                    if "SuccessValue" not in str(tx_info["status"]):
                        logger.warning(f"Transaction {tx_hash} was not successful")
                        return False

                    # Check if this is a transfer transaction to our deposit address
                    if (
                        "transaction" not in tx_info
                        or "receiver_id" not in tx_info["transaction"]
                    ):
                        logger.warning(f"Transaction {tx_hash} has invalid format")
                        return False

                    # Verify the receiver is our deposit address
                    if tx_info["transaction"]["receiver_id"] != deposit_address:
                        logger.warning(
                            f"Transaction receiver {tx_info['transaction']['receiver_id']} does not match deposit address {deposit_address}"
                        )
                        return False

                    # Check for amount in the transaction
                    actions = tx_info["transaction"].get("actions", [])
                    total_amount = 0

                    for action in actions:
                        if "Transfer" in action:
                            transfer_amount = int(
                                action["Transfer"].get("deposit", "0")
                            )
                            total_amount += transfer_amount

                    # Convert to NEAR for comparison (1 NEAR = 10^24 yoctoNEAR)
                    total_amount_near = total_amount / NEAR
                    logger.info(
                        f"Found transfer of {total_amount_near} NEAR in transaction {tx_hash}"
                    )

                    # Check if the transferred amount is sufficient
                    if total_amount >= required_amount * NEAR:
                        # Update quiz to ACTIVE and commit immediately
                        quiz.status = QuizStatus.ACTIVE
                        total_reward = required_amount
                        group_chat_id = quiz.group_chat_id
                        topic = quiz.topic

                        session.commit()

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
                                    logger.info(
                                        f"Quiz {quiz_id} activated with {total_reward} NEAR via transaction {tx_hash}"
                                    )
                        except asyncio.TimeoutError:
                            logger.error(f"Failed to announce active quiz: Timed out")
                        except Exception as e:
                            logger.error(f"Failed to announce active quiz: {e}")
                            traceback.print_exc()

                        return True
                    else:
                        logger.warning(
                            f"Insufficient funds in transaction {tx_hash}: {total_amount_near}/{required_amount} NEAR"
                        )
                        return False

                except Exception as e:
                    logger.error(f"Error verifying transaction {tx_hash}: {e}")
                    traceback.print_exc()
                    return False

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Error during transaction verification: {e}")
            traceback.print_exc()
            return False


# To be called during bot initialization
async def start_blockchain_monitor(bot):
    """Initialize and start the blockchain monitor with the bot instance."""
    monitor = BlockchainMonitor(bot)
    await monitor.start_monitoring()
    return monitor
