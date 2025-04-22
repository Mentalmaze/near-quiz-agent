from telegram import Update
from telegram.ext import CallbackContext
from services.quiz_service import create_quiz, play_quiz
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
