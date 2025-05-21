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
    get_winners,
    distribute_quiz_rewards,
    process_questions,
    schedule_auto_distribution,
    save_quiz_payment_hash,  # Added import
    save_quiz_reward_details,  # Added import
)
from services.user_service import (
    get_user_wallet,
    set_user_wallet,
    remove_user_wallet,
)  # Updated imports
from agent import generate_quiz
import logging
import re  # Import re for duration_input and potentially wallet validation
import asyncio  # Add asyncio import
from typing import Optional  # Added for type hinting
from utils.config import Config  # Added to access DEPOSIT_ADDRESS
from store.database import SessionLocal
from models.quiz import Quiz

# Configure logger
logger = logging.getLogger(__name__)


# Helper function to escape specific MarkdownV2 characters
def _escape_markdown_v2_specials(text: str) -> str:
    # Targeted escape for characters known to cause issues in simple text strings
    # when parse_mode='MarkdownV2' is used.
    # Note: This is not a comprehensive MarkdownV2 escaper.
    # For a full solution, a library function or more extensive regex would be needed.
    # This targets the most common issues like '.', '!', '-'.
    if not text:  # Ensure text is not None
        return ""
    text = str(text)  # Ensure text is a string
    text = text.replace(".", "\.")
    text = text.replace("!", "\!")
    text = text.replace("-", "\-")
    text = text.replace("(", "\(")
    text = text.replace(")", "\)")
    text = text.replace("+", "\+")
    text = text.replace("=", "\=")
    # Add other characters if they become problematic and are not part of intended Markdown like backticks or links.
    return text


# Define conversation states
TOPIC, SIZE, CONTEXT_CHOICE, CONTEXT_INPUT, DURATION_CHOICE, DURATION_INPUT, CONFIRM = (
    range(7)
)

# States for reward configuration
(
    REWARD_METHOD_CHOICE,
    REWARD_WTA_INPUT,
    REWARD_TOP3_INPUT,
    REWARD_CUSTOM_INPUT,
    REWARD_MANUAL_INPUT,
) = range(7, 12)


# Helper function to parse reward details
def _parse_reward_details_for_total(
    reward_text: str, reward_type: str
) -> tuple[Optional[float], Optional[str]]:
    total_amount = 0.0
    currency = None

    try:
        if reward_type == "wta_amount":
            # e.g., "5 NEAR", "10.5 USDT" (currency must be 3+ letters to avoid ordinal suffixes)
            match = re.search(r"(\d+\.?\d*)\s*([A-Za-z]{3,})\b", reward_text)
            if match:
                total_amount = float(match.group(1))
                currency = match.group(2).upper()
                return total_amount, currency
            return None, None

        elif reward_type == "top3_details":
            # e.g., "3 NEAR for 1st, 2 NEAR for 2nd, 1 NEAR for 3rd" (ignore ordinal suffixes)
            matches = re.findall(r"(\d+\.?\d*)\s*([A-Za-z]{3,})\b", reward_text)
            if not matches:
                return None, None

            parsed_currency = matches[0][1].upper()
            for amount_str, curr_str in matches:
                if curr_str.upper() != parsed_currency:
                    logger.warning(
                        f"Mismatched currencies in top3_details: expected {parsed_currency}, got {curr_str.upper()}"
                    )
                    return None, None  # Mismatch in currencies
                total_amount += float(amount_str)
            currency = parsed_currency
            return total_amount, currency

        elif reward_type == "custom_details":
            # Basic sum for custom_details, sums all "X CURRENCY" found if currency is consistent (ignore ordinals)
            matches = re.findall(r"(\d+\.?\d*)\s*([A-Za-z]{3,})\b", reward_text)
            if not matches:
                return None, None

            parsed_currency = matches[0][1].upper()
            for amount_str, curr_str in matches:
                if curr_str.upper() != parsed_currency:
                    logger.warning(
                        f"Mismatched currencies in custom_details: expected {parsed_currency}, got {curr_str.upper()}"
                    )
                    return None, None  # Mismatched currencies
                total_amount += float(amount_str)
            currency = parsed_currency
            return total_amount, currency
    except ValueError as e:
        logger.error(
            f"ValueError during parsing reward details for {reward_type}: {reward_text} - {e}"
        )
        return None, None
    except Exception as e:
        logger.error(
            f"Unexpected error during parsing reward details for {reward_type}: {reward_text} - {e}"
        )
        return None, None

    return None, None


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
    logger.info(
        f"User_data BEFORE cleaning at quiz creation start for user {user.id}: {context.user_data}"
    )

    # Clear potentially stale user_data from previous incomplete flows
    # (especially reward setup and its own duration flags) before starting a new quiz creation.
    context.user_data.pop("awaiting_reward_input_type", None)
    context.user_data.pop("current_quiz_id_for_reward_setup", None)
    context.user_data.pop("awaiting", None)  # Legacy reward structure flag
    context.user_data.pop("awaiting_reward_quiz_id", None)  # Legacy reward quiz ID flag
    # Also clear awaiting_duration_input as a safeguard, as it's part of this quiz creation flow
    # and should be reset if the flow is restarted.
    context.user_data.pop("awaiting_duration_input", None)

    logger.info(
        f"User_data AFTER cleaning for user {user.id} at quiz creation start: {context.user_data}"
    )

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

    # Ensure group_chat_id is correctly sourced
    group_chat_id_to_use = data.get(
        "group_chat_id", update.effective_chat.id
    )  # Fallback to current chat if group_chat_id not in user_data

    # Call process_questions to store in DB and announce
    await process_questions(
        update,  # Pass the update object
        context,
        data["topic"],
        quiz_text,
        group_chat_id_to_use,  # Use the resolved group_chat_id
        data.get("duration_seconds"),  # Pass duration if set
    )
    # schedule auto distribution
    if data.get("duration_seconds"):
        # ... (ensure schedule_auto_distribution is called correctly if needed) ...
        pass  # Placeholder for actual scheduling logic if different from process_questions

    # Clear conversation data for quiz creation
    context.user_data.clear()
    return ConversationHandler.END


async def start_reward_setup_callback(update: Update, context: CallbackContext):
    """Handles the 'Setup Rewards' button press and presents reward configuration options."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press

    try:
        action, quiz_id = query.data.split(":")
        if action != "reward_setup_start":
            logger.warning(
                f"Unexpected action in start_reward_setup_callback: {action}"
            )
            await query.edit_message_text(
                "Sorry, there was an error. Please try creating the quiz again."
            )
            return
    except ValueError:
        logger.error(f"Could not parse quiz_id from callback_data: {query.data}")
        await query.edit_message_text(
            "Error: Could not identify the quiz. Please try again."
        )
        return

    context.user_data["current_quiz_id_for_reward_setup"] = quiz_id

    logger.info(
        f"User {update.effective_user.id} starting reward setup for quiz {quiz_id}"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🏆 Winner Takes All", callback_data=f"reward_method:wta:{quiz_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🥇🥈🥉 Reward Top 3", callback_data=f"reward_method:top3:{quiz_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "✨ Custom Setup (Guided)",
                callback_data=f"reward_method:custom:{quiz_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "✍️ Type Manually", callback_data=f"reward_method:manual:{quiz_id}"
            )
        ],
        [
            InlineKeyboardButton(
                "🔙 Cancel", callback_data=f"reward_method:cancel_setup:{quiz_id}"
            )
        ],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        text=f"Let's set up rewards for your quiz (ID: {quiz_id}). How would you like to do it?",
        reply_markup=reply_markup,
    )
    return  # Or a new state for a ConversationHandler


async def handle_reward_method_choice(update: Update, context: CallbackContext):
    """Handles the choice of reward method (WTA, Top3, Custom, Manual)."""
    query = update.callback_query
    await query.answer()

    try:
        _, method, quiz_id = query.data.split(":")
    except ValueError:
        logger.error(
            f"Could not parse reward method/quiz_id from callback_data: {query.data}"
        )
        await query.edit_message_text("Error: Invalid selection. Please try again.")
        return

    context.user_data["current_quiz_id_for_reward_setup"] = quiz_id  # Ensure it's set

    if method == "wta":
        context.user_data["awaiting_reward_input_type"] = "wta_amount"
        await query.edit_message_text(
            f"🏆 Winner Takes All selected for Quiz {quiz_id}.\nPlease enter the total prize amount (e.g., '5 NEAR', '10 USDT')."
        )
    elif method == "top3":
        context.user_data["awaiting_reward_input_type"] = "top3_details"
        await query.edit_message_text(
            f"🥇🥈🥉 Reward Top 3 selected for Quiz {quiz_id}.\nPlease describe the rewards for 1st, 2nd, and 3rd place (e.g., '3 NEAR for 1st, 2 NEAR for 2nd, 1 NEAR for 3rd')."
        )
    elif method == "custom":
        context.user_data["awaiting_reward_input_type"] = "custom_details"
        await query.edit_message_text(
            f"✨ Custom Setup for Quiz {quiz_id}.\nFor now, please describe the reward structure manually (e.g., '1st: 5N, 2nd-5th: 1N each')."
        )
    elif method == "manual":
        context.user_data["awaiting_reward_input_type"] = "manual_free_text"
        await query.edit_message_text(
            f"✍️ Manual Input selected for Quiz {quiz_id}.\nPlease type the reward structure (e.g., '2 Near for 1st, 1 Near for 2nd')."
        )
    elif method == "cancel_setup":
        await query.edit_message_text(f"Reward setup for Quiz {quiz_id} cancelled.")
        context.user_data.pop("current_quiz_id_for_reward_setup", None)
        context.user_data.pop("awaiting_reward_input_type", None)
        return ConversationHandler.END  # Or just return if not in a conv
    else:
        await query.edit_message_text("Invalid choice. Please try again.")
        return

    logger.info(
        f"User {update.effective_user.id} selected reward method {method} for quiz {quiz_id}. User_data: {context.user_data}"
    )
    # Subsequent input will be handled by private_message_handler
    # based on 'awaiting_reward_input_type'.


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
    logger.info(
        f"User_data for {user_id} in private_message_handler: {context.user_data}"
    )

    # Check if awaiting payment hash
    quiz_id_awaiting_hash = context.user_data.get("awaiting_payment_hash_for_quiz_id")
    if quiz_id_awaiting_hash:
        payment_hash = message_text.strip()
        logger.info(
            f"Handling payment hash input '{payment_hash}' for quiz {quiz_id_awaiting_hash} from user {user_id}"
        )

        save_success = await save_quiz_payment_hash(quiz_id_awaiting_hash, payment_hash)

        if save_success:
            await update.message.reply_text(
                f"✅ Transaction hash '{payment_hash}' received and linked to Quiz ID {quiz_id_awaiting_hash}.\n"
                "The quiz setup is now complete and funded!"
            )
            # Announce quiz activation in the original group chat
            session = SessionLocal()
            try:
                quiz = (
                    session.query(Quiz).filter(Quiz.id == quiz_id_awaiting_hash).first()
                )
                if quiz and quiz.group_chat_id:
                    # Tag everyone and announce quiz activation
                    announce_text = "@all \n"
                    announce_text += f"📣 New quiz '{quiz.topic}' is now active! 🎯\n"

                    # Include reward structure if available
                    schedule = quiz.reward_schedule or {}
                    if schedule:
                        reward_parts = []
                        for rank_str, amt in schedule.items():
                            try:
                                rank = int(rank_str)
                            except (ValueError, TypeError):
                                rank = rank_str
                            # simple ordinal
                            suffix = {1: "st", 2: "nd", 3: "rd"}.get(rank, "th")
                            reward_parts.append(f"{rank}{suffix}: {amt} NEAR")
                        announce_text += "Rewards: " + ", ".join(reward_parts) + "\n"

                    # Include end time if set
                    if getattr(quiz, "end_time", None):
                        # Format UTC end_time
                        end_str = quiz.end_time.strftime("%Y-%m-%d %H:%M UTC")
                        announce_text += f"Ends at: {end_str}\n"

                    announce_text += "Type /playquiz to participate!"

                    await context.bot.send_message(
                        chat_id=quiz.group_chat_id,
                        text=announce_text,
                    )

            finally:
                session.close()

        else:
            await update.message.reply_text(
                f"⚠️ There was an issue saving your transaction hash for Quiz ID {quiz_id_awaiting_hash}. "
                "Please try sending the hash again or contact support."
            )

        context.user_data.pop("awaiting_payment_hash_for_quiz_id", None)
        logger.info(
            f"Cleared 'awaiting_payment_hash_for_quiz_id' for user {user_id}. Current user_data: {context.user_data}"
        )
        return

    # Check for reward input (WTA, Top3, Custom, Manual)
    awaiting_reward_type = context.user_data.get("awaiting_reward_input_type")
    quiz_id_for_setup = context.user_data.get("current_quiz_id_for_reward_setup")

    if awaiting_reward_type and quiz_id_for_setup:
        logger.info(
            f"Handling reward input type: {awaiting_reward_type} for quiz {quiz_id_for_setup} from user {user_id}. Message: '{message_text}'"
        )

        # Save reward details to DB
        save_reward_success = await save_quiz_reward_details(
            quiz_id_for_setup, awaiting_reward_type, message_text
        )

        if save_reward_success:
            friendly_method_name = "your reward details"  # Default
            if awaiting_reward_type == "wta_amount":
                friendly_method_name = "Winner Takes All amount"
            elif awaiting_reward_type == "top3_details":
                friendly_method_name = "Top 3 reward details"
            elif awaiting_reward_type == "custom_details":
                friendly_method_name = "custom reward details"
            elif awaiting_reward_type == "manual_free_text":
                friendly_method_name = "manually entered reward text"

            reward_confirmation_content = (
                f"✅ Got it! I've noted down {friendly_method_name} as: '{_escape_markdown_v2_specials(message_text)}' for Quiz ID {quiz_id_for_setup}.\n"
                f"The rewards for this quiz are now set up."
            )
            logger.info(
                f"Reward confirmation content prepared: {reward_confirmation_content}"
            )

            # Attempt to parse for total amount and currency
            total_amount, currency = _parse_reward_details_for_total(
                message_text, awaiting_reward_type
            )
            logger.info(f"Parsed reward: Amount={total_amount}, Currency={currency}")

            if total_amount is not None and currency:
                deposit_instructions = (
                    f"💰 Please deposit *{total_amount} {currency}* "
                    f"to the following address to fund the quiz: `{Config.DEPOSIT_ADDRESS}`\n\n"
                    f"Once sent, please reply with the *transaction hash*."
                )
            else:
                deposit_instructions = (
                    f"⚠️ I couldn't automatically determine the total amount/currency from your input. "
                    f"Please ensure you deposit the correct total amount to fund the quiz to `{Config.DEPOSIT_ADDRESS}`.\n\n"
                    f"Once sent, please reply with the *transaction hash*."
                )
            logger.info(f"Deposit instructions prepared: {deposit_instructions}")

            prompt_for_hash_message = "I'm now awaiting the transaction hash."

            try:
                logger.info(
                    f"Attempting to send reward confirmation for {awaiting_reward_type} to user {user_id}."
                )
                await asyncio.wait_for(
                    update.message.reply_text(text=reward_confirmation_content),
                    timeout=30.0,  # Increased timeout
                )
                logger.info(
                    f"Reward confirmation sent. Attempting to send deposit instructions for {awaiting_reward_type} to user {user_id}."
                )
                await asyncio.wait_for(
                    update.message.reply_text(
                        text=deposit_instructions, parse_mode="Markdown"
                    ),
                    timeout=30.0,  # Increased timeout
                )
                logger.info(
                    f"Deposit instructions sent. Attempting to send prompt for hash for {awaiting_reward_type} to user {user_id}."
                )
                await asyncio.wait_for(
                    update.message.reply_text(text=prompt_for_hash_message),
                    timeout=30.0,  # Increased timeout
                )
                logger.info(
                    f"All reward setup messages sent successfully for {awaiting_reward_type} to user {user_id}."
                )

                # Transition to awaiting payment hash state
                context.user_data["awaiting_payment_hash_for_quiz_id"] = (
                    quiz_id_for_setup
                )
                logger.info(
                    f"Set 'awaiting_payment_hash_for_quiz_id' to {quiz_id_for_setup} for user {user_id}. Current user_data: {context.user_data}"
                )

            except asyncio.TimeoutError:
                logger.error(
                    f"Timeout occurred during reward setup/payment prompt for {awaiting_reward_type} to user {user_id}"
                )
                await update.message.reply_text(
                    "⚠️ I tried to send the next steps, but it took too long. "
                    "If you've already provided the reward details, please send the transaction hash for your deposit. "
                    f"If not, you might need to restart the reward setup for Quiz ID {quiz_id_for_setup}."
                )
            except Exception as e:
                logger.error(
                    f"Error sending reward setup/payment prompt for {awaiting_reward_type} to user {user_id}: {e}",
                    exc_info=True,
                )
                await update.message.reply_text(
                    "⚠️ An error occurred while sending the next steps. "
                    f"Please check the logs or contact support. You might need to restart reward setup for Quiz ID {quiz_id_for_setup}."
                )
        else:
            await update.message.reply_text(
                "⚠️ There was an issue saving your reward details. Please try sending them again."
            )
            # Do not clear state, allow user to retry sending the details.

        logger.info(
            f"Returning from private_message_handler after processing reward input for {awaiting_reward_type} for user {user_id}."
        )
        return

    # Check for duration input flag
    if context.user_data.get("awaiting_duration_input"):
        logger.info(
            f"User {user_id} is awaiting duration input. Processing duration: '{message_text}' in private_message_handler"
        )
        # Clear the flag
        context.user_data.pop("awaiting_duration_input", None)  # Changed to pop

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
            if m and (
                "minute" in txt.lower() or "min" in txt.lower()
            ):  # Added more specific check
                val = int(m.group(1))
                secs = val * 60
                context.user_data["duration_seconds"] = secs
                logger.info(
                    f"Flexibly parsed duration: {secs} seconds from '{message_text}'"
                )
            elif m and "hour" in txt.lower():  # Added more specific check
                val = int(m.group(1))
                secs = val * 3600
                context.user_data["duration_seconds"] = secs
                logger.info(
                    f"Flexibly parsed duration: {secs} seconds from '{message_text}'"
                )
            else:
                # Use default duration
                context.user_data["duration_seconds"] = 300  # 5 minutes
                logger.info(
                    f"Using default duration of 300 seconds for '{message_text}'"
                )
                await update.message.reply_text(  # Notify user of default
                    "I couldn't understand that duration format. Using 5 minutes by default."
                )

        # Call confirm_prompt and return its state to correctly transition the ConversationHandler
        return await confirm_prompt(update, context)

    logger.info(
        f"Message from user {user_id} ('{message_text}') is NOT for reward structure or duration input. Checking ConversationHandler."
    )


async def winners_handler(update: Update, context: CallbackContext):
    """Handler for /winners command to display quiz results."""
    await get_winners(update, context)


async def distribute_rewards_handler(update: Update, context: CallbackContext):
    """Handler for /distributerewards command to send NEAR rewards to winners."""
    await distribute_quiz_rewards(update, context)
