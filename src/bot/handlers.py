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
from services.user_service import (
    get_user_wallet,
    set_user_wallet,
    remove_user_wallet,
)  # Updated imports
from agent import generate_quiz
import logging
import re  # Import re for duration_input and potentially wallet validation

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
    user = update.effective_user
    chat_type = update.effective_chat.type
    logger.info(
        f"User {user.id} initiating /createquiz from {chat_type} chat {update.effective_chat.id}."
    )
    logger.info(f"Initial context.user_data for user {user.id}: {context.user_data}")

    if chat_type != "private":
        logger.info(
            f"User {user.id} started quiz creation from group chat {update.effective_chat.id}. Will DM."
        )
        await update.message.reply_text(
            f"@{user.username}, let's create a quiz! I'll message you privately to set it up."
        )
        await context.bot.send_message(
            chat_id=user.id, text="Great—what topic would you like your quiz to cover?"
        )
        context.user_data["group_chat_id"] = update.effective_chat.id
        logger.info(
            f"Stored group_chat_id {update.effective_chat.id} for user {user.id}. user_data: {context.user_data}"
        )
        return TOPIC
    else:
        logger.info(f"User {user.id} started quiz creation directly in private chat.")
        await update.message.reply_text(
            "Great—what topic would you like your quiz to cover?"
        )
        # Clear any potential leftover group_chat_id if starting fresh in DM
        if "group_chat_id" in context.user_data:
            del context.user_data["group_chat_id"]
        logger.info(f"User {user.id} in private chat. user_data: {context.user_data}")
        return TOPIC


async def topic_received(update, context):
    logger.info(
        f"Received topic: {update.message.text} from user {update.effective_user.id}"
    )
    context.user_data["topic"] = update.message.text.strip()
    await update.message.reply_text("How many questions? (send a number)")
    return SIZE


async def size_received(update, context):
    logger.info(
        f"Received size: {update.message.text} from user {update.effective_user.id}"
    )
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
    # Set the expectation that if user doesn't click a button, they might type a duration
    context.user_data["awaiting_duration_input"] = True
    logger.info(
        f"Showing duration options to user {update.effective_user.id} after context_choice, set awaiting_duration_input=True"
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
    # Set the expectation that if user doesn't click a button, they might type a duration
    context.user_data["awaiting_duration_input"] = True
    logger.info(
        f"Showing duration options to user {update.effective_user.id} after context_input, set awaiting_duration_input=True"
    )
    return DURATION_CHOICE


async def duration_choice(update, context):
    choice = update.callback_query.data
    await update.callback_query.answer()
    logger.info(f"duration_choice: User {update.effective_user.id} selected {choice}")

    if choice == "set_duration":
        # Set a special flag to identify duration input messages
        context.user_data["awaiting_duration_input"] = True
        logger.info(
            f"Setting awaiting_duration_input flag for user {update.effective_user.id}"
        )

        await update.callback_query.message.reply_text(
            "Send duration, e.g. '5 minutes' or '2 hours'."
        )
        logger.info(
            f"duration_choice: Returning DURATION_INPUT state for user {update.effective_user.id}"
        )
        return DURATION_INPUT
    # skip
    context.user_data["duration_seconds"] = None
    logger.info(
        f"duration_choice: User {update.effective_user.id} skipped duration, going to confirm_prompt"
    )
    # preview
    return await confirm_prompt(update, context)


async def duration_input(update, context):
    user_id = update.effective_user.id
    message_text = update.message.text
    logger.info(
        f"Attempting to process DURATION_INPUT: '{message_text}' from user {user_id}"
    )
    logger.debug(f"User data for {user_id} at duration_input: {context.user_data}")
    txt = message_text.strip().lower()
    # simple parse
    m = re.match(r"(\d+)\s*(minute|hour|min)s?", txt)
    if m:
        val = int(m.group(1))
        unit = m.group(2)
        secs = val * (3600 if unit.startswith("hour") else 60)
        context.user_data["duration_seconds"] = secs
        logger.info(
            f"Successfully parsed duration for user {user_id}: {secs} seconds from '{message_text}'"
        )
    else:
        # Try a more flexible regex
        m = re.search(r"(\d+)", txt)
        if m and ("minute" in txt.lower() or "min" in txt.lower()):
            val = int(m.group(1))
            secs = val * 60
            context.user_data["duration_seconds"] = secs
            logger.info(
                f"Flexibly parsed duration: {secs} seconds from '{message_text}'"
            )
        elif m and "hour" in txt.lower():
            val = int(m.group(1))
            secs = val * 3600
            context.user_data["duration_seconds"] = secs
            logger.info(
                f"Flexibly parsed duration: {secs} seconds from '{message_text}'"
            )
        else:
            context.user_data["duration_seconds"] = 300  # Default to 5 minutes
            logger.info(
                f"Could not parse duration from '{message_text}'. Using default: 300 seconds"
            )
            await update.message.reply_text(
                "I couldn't understand that format. Using 5 minutes by default."
            )
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
        None,
    )
    # schedule auto distribution
    if data.get("duration_seconds"):
        from services.quiz_service import schedule_auto_distribution

        context.application.create_task(
            schedule_auto_distribution(
                context.application, data.get("quiz_id", None), data["duration_seconds"]
            )
        )
    return ConversationHandler.END


async def create_quiz_handler(update: Update, context: CallbackContext):
    """Handler for /createquiz command."""
    await create_quiz(update, context)


async def link_wallet_handler(update: Update, context: CallbackContext):
    """Handler for /linkwallet command."""
    user = update.effective_user
    if not user:
        await update.message.reply_text("Could not identify user.")
        return

    user_id = user.id

    # Check if wallet is already linked
    # This assumes get_user_wallet returns the wallet address if linked, or None otherwise
    existing_wallet = await get_user_wallet(user_id)
    if existing_wallet:
        await update.message.reply_text(
            f"You have already linked the wallet: `{existing_wallet}`.\n"
            "If you want to link a new wallet, please use /unlinkwallet first."
        )
        return

    if not context.args:
        await update.message.reply_text(
            "Please provide your wallet address after the command.\n"
            "Example: `/linkwallet yourwallet.near`"
        )
        return

    wallet_address = context.args[0].strip()

    # Basic validation (you might want to make this more robust)
    if not (wallet_address.endswith(".near") or wallet_address.endswith(".testnet")):
        await update.message.reply_text(
            "Invalid wallet address format. Please provide a valid .near or .testnet address."
        )
        return

    # This assumes set_user_wallet returns True on success, False on failure
    if await set_user_wallet(user_id, wallet_address):
        await update.message.reply_text(
            f"✅ Wallet `{wallet_address}` linked successfully!"
        )
    else:
        await update.message.reply_text(
            "⚠️ Failed to link your wallet. Please try again or contact support."
        )


async def unlink_wallet_handler(update: Update, context: CallbackContext):
    """Handler for /unlinkwallet command."""
    user = update.effective_user
    if not user:
        await update.message.reply_text("Could not identify user.")
        return

    user_id = user.id

    existing_wallet = await get_user_wallet(user_id)
    if not existing_wallet:
        await update.message.reply_text("You do not have any wallet linked.")
        return

    # This assumes remove_user_wallet returns True on success, False on failure
    if await remove_user_wallet(user_id):
        await update.message.reply_text(
            f"✅ Your wallet `{existing_wallet}` has been unlinked successfully."
        )
    else:
        await update.message.reply_text(
            "⚠️ Failed to unlink your wallet. Please try again or contact support."
        )


async def play_quiz_handler(update: Update, context: CallbackContext):
    """Handler for /playquiz command."""
    await play_quiz(update, context)


async def quiz_answer_handler(update: Update, context: CallbackContext):
    """Handler for quiz answer callbacks."""
    if update.callback_query and update.callback_query.data.startswith("quiz:"):
        await handle_quiz_answer(update, context)


async def private_message_handler(update: Update, context: CallbackContext):
    """Route private text messages to the appropriate handler."""
    user_id = update.effective_user.id
    message_text = update.message.text
    logger.info(
        f"PRIVATE_MESSAGE_HANDLER received: '{message_text}' from user {user_id}"
    )
    # Log the entire user_data to see if 'awaiting_reward_quiz_id' is present
    logger.info(
        f"User_data for {user_id} in private_message_handler: {context.user_data}"
    )

    # Check for reward structure handling
    if context.user_data.get("awaiting") == "reward_structure" or context.user_data.get(
        "awaiting_reward_quiz_id"
    ):
        logger.info(
            f"User {user_id} is awaiting reward structure input. Passing to handle_reward_structure."
        )
        await handle_reward_structure(update, context)
        return

    # Check for duration input flag
    if context.user_data.get("awaiting_duration_input"):
        logger.info(
            f"User {user_id} is awaiting duration input. Processing duration: '{message_text}'"
        )
        # Clear the flag
        context.user_data["awaiting_duration_input"] = False

        # Parse duration input
        txt = message_text.strip().lower()
        m = re.match(r"(\d+)\s*(minute|hour|min)s?", txt)
        if m:
            val = int(m.group(1))
            unit = m.group(2)
            secs = val * (3600 if unit.startswith("hour") else 60)
            context.user_data["duration_seconds"] = secs
            logger.info(f"Parsed duration: {secs} seconds from '{message_text}'")
        else:
            # Try a more flexible regex
            m = re.search(r"(\d+)", txt)
            if m:
                # Default to minutes if no unit specified
                val = int(m.group(1))
                secs = val * 60
                context.user_data["duration_seconds"] = secs
                logger.info(
                    f"Parsed basic duration: {secs} seconds from '{message_text}'"
                )
            else:
                # Use default duration
                context.user_data["duration_seconds"] = 300  # 5 minutes
                logger.info(
                    f"Using default duration of 300 seconds for '{message_text}'"
                )

        # Show confirmation prompt
        topic = context.user_data["topic"]
        n = context.user_data["num_questions"]
        has_ctx = bool(context.user_data.get("context_text"))
        dur = context.user_data["duration_seconds"]
        text = f"Ready to generate a {n}-question quiz on '{topic}'"
        text += " based on your text" if has_ctx else ""
        text += f", open for {dur//60} minutes"
        text += ". Generate now?"
        buttons = [
            [InlineKeyboardButton("Yes", callback_data="yes")],
            [InlineKeyboardButton("No", callback_data="no")],
        ]
        await update.message.reply_text(
            text, reply_markup=InlineKeyboardMarkup(buttons)
        )
        return

    logger.info(
        f"Message from user {user_id} ('{message_text}') is NOT for reward structure or duration input. Checking ConversationHandler."
    )


async def winners_handler(update: Update, context: CallbackContext):
    """Handler for /winners command to display quiz results."""
    await get_winners(update, context)


async def distribute_rewards_handler(update: Update, context: CallbackContext):
    """Handler for /distributerewards command to send NEAR rewards to winners."""
    await distribute_quiz_rewards(update, context)
