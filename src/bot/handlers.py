from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    CallbackContext,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from services.quiz_service import (
    create_quiz,
    play_quiz,
    handle_quiz_answer,
    handle_reward_structure,
    get_winners,
    distribute_quiz_rewards,
    process_questions,
    schedule_auto_distribution,
)
from services.user_service import link_wallet
from agent import generate_quiz
import logging

# Configure logger
logger = logging.getLogger(__name__)

# Define conversation states
TOPIC, SIZE, CONTEXT_CHOICE, CONTEXT_INPUT, DURATION_CHOICE, DURATION_INPUT, CONFIRM = (
    range(7)
)


async def group_start(update, context):
    """Handle /createquiz in group chat by telling user to DM the bot."""
    user = update.effective_user
    await update.message.reply_text(
        f"@{user.username}, to set up a quiz, please DM me and send /createquiz."
    )
    # no conversation state here


async def start_createquiz_group(update, context):
    """Entry point for the quiz creation conversation"""
    # Check if we're in a group or private chat
    if update.effective_chat.type != "private":
        user = update.effective_user
        logger.info(f"User {user.id} started quiz creation from group chat")
        await update.message.reply_text(
            f"@{user.username}, let's create a quiz! I'll message you privately to set it up."
        )
        # Send a message to the user privately
        await context.bot.send_message(
            chat_id=user.id,
            text="Great—what topic would you like your quiz to cover?"
        )
        # Store the original group chat ID for later announcements
        context.user_data["group_chat_id"] = update.effective_chat.id
        return TOPIC
    else:
        # Already in a private chat
        logger.info(f"User {update.effective_user.id} started quiz creation from private chat")
        await update.message.reply_text(
            "Great—what topic would you like your quiz to cover?"
        )
        return TOPIC


async def topic_received(update, context):
    logger.info(f"Received topic: {update.message.text} from user {update.effective_user.id}")
    context.user_data["topic"] = update.message.text.strip()
    await update.message.reply_text("How many questions? (send a number)")
    return SIZE


async def size_received(update, context):
    logger.info(f"Received size: {update.message.text} from user {update.effective_user.id}")
    try:
        n = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please send a valid number of questions.")
        return SIZE
    context.user_data["num_questions"] = n
    # ask for optional long text
    buttons = [
        [InlineKeyboardButton("Paste text", callback_data="paste")],
        [InlineKeyboardButton("Skip", callback_data="skip_context")],
    ]
    await update.message.reply_text(
        "If you have a passage or notes, paste them now; otherwise skip.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return CONTEXT_CHOICE


async def context_choice(update, context):
    choice = update.callback_query.data
    await update.callback_query.answer()
    if choice == "paste":
        await update.callback_query.message.reply_text(
            "Please send the text to base your quiz on."
        )
        return CONTEXT_INPUT
    # skip
    context.user_data["context_text"] = None
    # move to duration
    buttons = [
        [InlineKeyboardButton("Specify duration", callback_data="set_duration")],
        [InlineKeyboardButton("Skip", callback_data="skip_duration")],
    ]
    await update.callback_query.message.reply_text(
        "How long should the quiz be open? e.g. '5 minutes', or skip.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return DURATION_CHOICE


async def context_input(update, context):
    context.user_data["context_text"] = update.message.text
    # ask duration
    buttons = [
        [InlineKeyboardButton("Specify duration", callback_data="set_duration")],
        [InlineKeyboardButton("Skip", callback_data="skip_duration")],
    ]
    await update.message.reply_text(
        "How long should the quiz be open? e.g. '5 minutes', or skip.",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return DURATION_CHOICE


async def duration_choice(update, context):
    choice = update.callback_query.data
    await update.callback_query.answer()
    if choice == "set_duration":
        await update.callback_query.message.reply_text(
            "Send duration, e.g. '5 minutes' or '2 hours'."
        )
        return DURATION_INPUT
    # skip
    context.user_data["duration_seconds"] = None
    # preview
    return await confirm_prompt(update, context)


async def duration_input(update, context):
    txt = update.message.text.strip().lower()
    # simple parse
    import re, datetime

    m = re.match(r"(\d+)\s*(minute|hour)s?", txt)
    if m:
        val, unit = int(m.group(1)), m.group(2)
        secs = val * (3600 if unit.startswith("hour") else 60)
        context.user_data["duration_seconds"] = secs
    else:
        context.user_data["duration_seconds"] = None
    return await confirm_prompt(update, context)


async def confirm_prompt(update, context):
    topic = context.user_data["topic"]
    n = context.user_data["num_questions"]
    has_ctx = bool(context.user_data.get("context_text"))
    dur = context.user_data.get("duration_seconds")
    text = f"Ready to generate a {n}-question quiz on '{topic}'"
    text += " based on your text" if has_ctx else ""
    text += f", open for {dur//60} minutes" if dur else ""
    text += ". Generate now?"
    buttons = [
        [InlineKeyboardButton("Yes", callback_data="yes")],
        [InlineKeyboardButton("No", callback_data="no")],
    ]
    if update.callback_query:
        msg = update.callback_query.message
    else:
        msg = update.message
    await msg.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    return CONFIRM


async def confirm_choice(update, context):
    choice = update.callback_query.data
    await update.callback_query.answer()
    if choice == "no":
        await update.callback_query.message.reply_text("Quiz creation canceled.")
        return ConversationHandler.END
    # yes: generate and post
    await update.callback_query.message.reply_text("🛠 Generating your quiz—one moment…")
    data = context.user_data
    quiz_text = await generate_quiz(
        data["topic"], data["num_questions"], data.get("context_text")
    )
    # post to group
    group_id = data.get("group_chat_id")
    # process questions from raw text
    from services.quiz_service import process_questions

    # Call process_questions to store in DB and announce
    await process_questions(
        update, 
        context, 
        data["topic"], 
        quiz_text, 
        group_id if group_id else update.effective_chat.id,
        None
    )
    # schedule auto distribution
    if data.get("duration_seconds"):
        from services.quiz_service import schedule_auto_distribution

        context.application.create_task(
            schedule_auto_distribution(
                context.application, 
                data.get("quiz_id", None), 
                data["duration_seconds"]
            )
        )
    return ConversationHandler.END


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
    # Log the private message for debugging
    logger.info(f"Received private message: '{update.message.text}' from user {update.effective_user.id}")
    
    # Check if we have an awaiting state in context.user_data
    if "awaiting" in context.user_data:
        logger.info(f"Found awaiting state: {context.user_data['awaiting']}")
        await handle_reward_structure(update, context)
        return
    
    # No awaiting state, this might be a conversation message
    # The ConversationHandler will catch it if applicable
    logger.info("No awaiting state found, might be handled by ConversationHandler")


async def winners_handler(update: Update, context: CallbackContext):
    """Handler for /winners command to display quiz results."""
    await get_winners(update, context)


async def distribute_rewards_handler(update: Update, context: CallbackContext):
    """Handler for /distributerewards command to send NEAR rewards to winners."""
    await distribute_quiz_rewards(update, context)
