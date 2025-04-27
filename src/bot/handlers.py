from telegram import Update
from telegram.ext import CallbackContext
from services.quiz_service import (
    create_quiz,
    play_quiz,
    handle_quiz_answer,
    handle_reward_structure,
    get_winners,
    distribute_quiz_rewards,
)
from services.user_service import link_wallet


async def create_quiz_handler(update: Update, context: CallbackContext):
    """Handler for /createquiz command."""
    await create_quiz(update, context)


async def link_wallet_handler(update: Update, context: CallbackContext):
    """Handler for /linkwallet command."""
    await link_wallet(update, context)


async def play_quiz_handler(update: Update, context: CallbackContext):
    """Handler for /playquiz command."""
    await play_quiz(update, context)


async def quiz_answer_handler(update: Update, context: CallbackContext):
    """Handler for quiz answer callbacks."""
    if update.callback_query and update.callback_query.data.startswith("quiz:"):
        await handle_quiz_answer(update, context)


async def private_message_handler(update: Update, context: CallbackContext):
    """Route private text messages to the appropriate handler."""
    await handle_reward_structure(update, context)


async def winners_handler(update: Update, context: CallbackContext):
    """Handler for /winners command to display quiz results."""
    await get_winners(update, context)


async def distribute_rewards_handler(update: Update, context: CallbackContext):
    """Handler for /distributerewards command to send NEAR rewards to winners."""
    await distribute_quiz_rewards(update, context)
