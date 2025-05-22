import asyncio
import os
import time
import logging
from datetime import datetime, timedelta
from models.quiz import Quiz, QuizStatus
from store.database import SessionLocal
from utils.config import Config
import traceback
from typing import Dict, List, Optional, Any

from py_near.account import Account

# Import py-near components
# from pynear.account import Account
from py_near.dapps.core import NEAR
import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import re

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

        logger.info(
            "Blockchain monitor initialized - no automatic monitoring enabled, using manual verification only"
        )
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
        logger.info(f"[distribute_rewards] called for quiz_id={quiz_id}")
        if not self.near_account:
            logger.error(
                "[distribute_rewards] Cannot distribute rewards - NEAR account not initialized"
            )
            return False
        logger.debug(f"[distribute_rewards] NEAR account present: {self.near_account}")

        # Open a new session for this operation
        session = SessionLocal()
        try:
            # Get quiz data and confirm it's in ACTIVE status
            quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
            logger.info(
                f"[distribute_rewards] Fetched quiz {quiz_id}: status={quiz.status}, reward_schedule={quiz.reward_schedule}"
            )
            if not quiz:
                logger.error(f"Quiz {quiz_id} not found")
                return False

            if quiz.status == QuizStatus.CLOSED:
                logger.info(f"Quiz {quiz_id} already closed and rewards distributed")
                return True

            if quiz.status != QuizStatus.ACTIVE:
                logger.error(
                    f"[distribute_rewards] Quiz {quiz_id} not in ACTIVE state ({quiz.status}), cannot distribute rewards"
                )
                return False

            # Get winners from database
            from models.quiz import QuizAnswer

            winners = QuizAnswer.compute_quiz_winners(session, quiz_id)
            logger.info(
                f"[distribute_rewards] Found {len(winners)} winner entries: {winners}"
            )
            if not winners:
                logger.warning(f"No winners found for quiz {quiz_id}")
                # If no winners, it's not a failure of distribution, but no one to distribute to.
                # Depending on desired behavior, could return True or a specific status.
                # For now, let's consider it a scenario where no rewards *can* be distributed.
                # Update quiz status to closed if no winners and quiz ended.
                quiz.status = QuizStatus.CLOSED
                quiz.rewards_distributed_at = datetime.utcnow()
                session.commit()
                logger.info(f"Quiz {quiz_id} closed as no winners were found.")
                return True  # Or False if this should be flagged as an issue. Let's say True for now.

            # Get wallet addresses for winners
            from models.user import User  # Already imported but good to note

            reward_schedule = quiz.reward_schedule
            logger.debug(
                f"[distribute_rewards] Using reward_schedule: {reward_schedule}"
            )

            # Track successful transfers
            successful_transfers = []

            # Process each winner according to reward schedule
            for rank, winner_data in enumerate(winners, 1):
                logger.debug(
                    f"[distribute_rewards] Processing rank={rank}, data={winner_data}"
                )
                user_id = winner_data["user_id"]
                user = session.query(User).filter(User.id == user_id).first()

                # Skip if no wallet linked
                if not user or not user.wallet_address:
                    logger.warning(
                        f"[distribute_rewards] User {user_id} (Username: {winner_data.get('username', 'N/A')}) has no wallet linked or user not found, skipping."
                    )
                    continue

                reward_amount_yoctonear = 0
                reward_amount_near_str = "0"

                if reward_schedule and isinstance(reward_schedule, dict):
                    schedule_type = reward_schedule.get("type")
                    if schedule_type == "wta_amount":  # Winner Takes All
                        amount_text = str(reward_schedule.get("details_text", ""))
                        # Expecting format like "1 NEAR" or "0.5 NEAR"
                        match = re.search(r"(\d+(?:\.\d+)?)", amount_text)
                        if match:
                            reward_amount_near_str = match.group(1)
                            try:
                                reward_amount_yoctonear = int(
                                    float(reward_amount_near_str) * NEAR
                                )  # NEAR is 10^24 yoctoNEAR
                            except ValueError:
                                logger.error(
                                    f"[distribute_rewards] Invalid reward amount in details_text: {amount_text} for quiz {quiz_id}"
                                )
                                continue
                        else:
                            logger.error(
                                f"[distribute_rewards] Could not parse reward amount from details_text: {amount_text} for quiz {quiz_id}"
                            )
                            continue
                    # Example for rank-based rewards (if you add this type later)
                    elif schedule_type == "rank_based" and str(
                        rank
                    ) in reward_schedule.get("ranks", {}):
                        reward_amount_near_str = str(
                            reward_schedule["ranks"][str(rank)]
                        )
                        try:
                            reward_amount_yoctonear = int(
                                float(reward_amount_near_str) * NEAR
                            )
                        except ValueError:
                            logger.error(
                                f"[distribute_rewards] Invalid reward amount for rank {rank}: {reward_amount_near_str} for quiz {quiz_id}"
                            )
                            continue
                    else:
                        logger.warning(
                            f"[distribute_rewards] Unknown or unhandled reward schedule type '{schedule_type}' or missing rank info for quiz {quiz_id}. Schedule: {reward_schedule}"
                        )
                        continue
                else:
                    logger.error(
                        f"[distribute_rewards] Invalid or missing reward_schedule for quiz {quiz_id}"
                    )
                    continue

                if reward_amount_yoctonear <= 0:
                    logger.warning(
                        f"[distribute_rewards] Calculated reward amount for user {user_id} is zero or negative ({reward_amount_near_str} NEAR), skipping transfer."
                    )
                    continue

                recipient_wallet = user.wallet_address
                logger.info(
                    f"[distribute_rewards] Attempting to send {reward_amount_near_str} NEAR ({reward_amount_yoctonear} yoctoNEAR) to {recipient_wallet} (User: {winner_data.get('username', 'N/A')}, Rank: {rank})"
                )

                try:
                    # THE ACTUAL TRANSFER CALL
                    tx_result = await self.near_account.send_money(
                        recipient_wallet, reward_amount_yoctonear
                    )
                    # py-near send_money usually returns a dict with transaction outcome or raises error.
                    # Let's assume tx_result contains a hash or success indicator.
                    # For robust check, one might inspect tx_result structure based on py-near documentation.
                    # Simplified: if it doesn't raise, assume success for now and log what we get.
                    tx_hash_str = str(
                        tx_result.get("transaction_outcome", {}).get("id", "N/A")
                        if isinstance(tx_result, dict)
                        else tx_result
                    )

                    logger.info(
                        f"[distribute_rewards] Successfully sent {reward_amount_near_str} NEAR to {recipient_wallet}. Tx details: {tx_hash_str}"
                    )
                    successful_transfers.append(
                        {
                            "user_id": user_id,
                            "username": winner_data.get(
                                "username", "N/A"
                            ),  # Changed from user.username
                            "wallet_address": recipient_wallet,
                            "amount_near_str": reward_amount_near_str,
                            "tx_hash": tx_hash_str,
                        }
                    )
                except Exception as transfer_exc:
                    logger.error(
                        f"[distribute_rewards] Failed to send NEAR to {recipient_wallet} for user {user_id}: {transfer_exc}"
                    )
                    traceback.print_exc()

            logger.info(
                f"[distribute_rewards] Total successful transfers: {len(successful_transfers)}"
            )
            # If at least some transfers were successful, mark quiz as closed
            if successful_transfers:
                quiz.status = QuizStatus.CLOSED
                quiz.rewards_distributed_at = datetime.utcnow()
                session.commit()
                logger.info(
                    f"Quiz {quiz_id} marked as CLOSED. Rewards distributed to {len(successful_transfers)} winner(s). Details: {successful_transfers}"
                )
                return True

            # This part is reached if successful_transfers is empty after processing all winners
            logger.warning(
                f"[distribute_rewards] No transfers were successfully performed for quiz {quiz_id}, though winners were found."
            )
            return False

        except Exception as e:
            logger.error(f"Error distributing rewards for quiz {quiz_id}: {e}")
            traceback.print_exc()
            return False
        finally:
            if session:
                session.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((httpx.TimeoutException, httpx.ReadTimeout)),
    )
    async def _make_rpc_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make an RPC request with retries and proper error handling"""
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(Config.NEAR_RPC_ENDPOINT_TRANS, json=payload)
            resp.raise_for_status()
            return resp.json()

    @retry(
        retry=retry_if_exception_type((httpx.ReadTimeout, httpx.ConnectTimeout)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
    )
    async def verify_transaction_by_hash(
        self, tx_hash: str, sender_account_id: str
    ) -> Dict[str, Any]:
        """
        Verify a transaction by its hash using NEAR RPC.
        Implements retry logic for timeout errors.

        Args:
            tx_hash: The transaction hash to verify
            sender_account_id: The sender's account ID

        Returns:
            Dict containing the transaction verification result

        Raises:
            httpx.TimeoutException: If all retry attempts fail
        """
        async with httpx.AsyncClient(timeout=30.0) as client:
            payload = {
                "jsonrpc": "2.0",
                "id": "dontcare",
                "method": "EXPERIMENTAL_tx_status",
                "params": {
                    "tx_hash": tx_hash,
                    "sender_account_id": sender_account_id,
                    "wait_until": "FINAL",
                },
            }

            try:
                resp = await client.post(Config.NEAR_RPC_ENDPOINT_TRANS, json=payload)
                resp.raise_for_status()
                result = resp.json()

                if "error" in result:
                    error_name = result["error"].get("name")
                    error_cause = result["error"].get("cause", {}).get("name")
                    logger.error(f"RPC Error: {error_name} - {error_cause}")
                    raise Exception(f"Transaction verification failed: {error_name}")

                return result["result"]

            except httpx.TimeoutException as e:
                logger.warning(
                    f"Timeout while verifying transaction {tx_hash}, retrying..."
                )
                raise
            except Exception as e:
                logger.error(f"Error verifying transaction {tx_hash}: {str(e)}")
                raise

    async def verify_transaction_by_hash(self, tx_hash: str, quiz_id: str) -> bool:
        """
        Verify a transaction by its hash to confirm a deposit was made.
        Uses direct JSON-RPC `tx` endpoint to fetch the transaction.
        """
        if not self.near_account:
            logger.error("Cannot verify transaction - NEAR account not initialized")
            return False

        # open session with retry logic
        quiz_data = {}
        from store.database import get_db

        with get_db() as session:
            quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
            if not quiz or quiz.status != QuizStatus.FUNDING:
                return False
            # Store all required attributes while session is open
            quiz_data = {
                "deposit_address": quiz.deposit_address,
                "required_amount": (
                    sum(int(v) for v in quiz.reward_schedule.values())
                    if quiz.reward_schedule
                    else 0
                ),
                "topic": quiz.topic,
                "group_chat_id": quiz.group_chat_id,
            }

        try:
            # call NEAR JSON-RPC tx method
            payload = {
                "jsonrpc": "2.0",
                "id": "verify",
                "method": "EXPERIMENTAL_tx_status",
                "params": {
                    "tx_hash": tx_hash,
                    "sender_account_id": quiz_data["deposit_address"],
                    "wait_until": "FINAL",
                },
            }

            try:
                data = await self._make_rpc_request(payload)
            except (httpx.TimeoutException, httpx.ReadTimeout) as e:
                logger.warning(
                    f"Timeout while verifying transaction {tx_hash}. Error: {str(e)}"
                )
                return False
            except httpx.HTTPError as e:
                logger.error(
                    f"HTTP error while verifying transaction {tx_hash}. Error: {str(e)}"
                )
                return False

            result = data.get("result")
            if not result or "status" not in result:
                logger.warning(f"RPC returned no result or status for tx {tx_hash}")
                return False

            status = result["status"]
            if isinstance(status, dict):
                if "SuccessValue" not in status and "success_value" not in status:
                    return False
            elif isinstance(status, str) and "SuccessValue" not in status:
                return False

            tx = result.get("transaction", {})
            if tx.get("receiver_id") != quiz_data["deposit_address"]:
                return False

            actions = tx.get("actions", [])
            total_yocto = 0
            for action in actions:
                if "Transfer" in action:
                    total_yocto += int(action["Transfer"].get("deposit", 0))

            if total_yocto >= quiz_data["required_amount"] * NEAR:
                # mark active and announce in new session with retry logic
                with get_db() as session:
                    quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
                    quiz.status = QuizStatus.ACTIVE
                    session.commit()

                # send announcement using stored quiz data
                if quiz_data["group_chat_id"]:
                    await self.bot.send_message(
                        chat_id=quiz_data["group_chat_id"],
                        text=(
                            f"📣 New quiz '{quiz_data['topic']}' is now active! 🎯\n"
                            f"Total rewards: {quiz_data['required_amount']} NEAR\n"
                            f"Type /playquiz to participate!"
                        ),
                    )
                return True
            return False
        except Exception as e:
            logger.error(f"Error verifying transaction {tx_hash}: {e}", exc_info=True)
            return False


# To be called during bot initialization
async def start_blockchain_monitor(bot):
    """Initialize and start the blockchain monitor with the bot instance."""
    logger.info(f"[start_blockchain_monitor] creating BlockchainMonitor with bot={bot}")
    monitor = BlockchainMonitor(bot)
    await monitor.start_monitoring()
    logger.info(f"[start_blockchain_monitor] monitor started: {monitor}")
    return monitor
