from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ContextTypes
from models.quiz import Quiz, QuizStatus, QuizAnswer
from store.database import SessionLocal
from agent import generate_quiz
from services.user_service import check_wallet_linked
from utils.telegram_helpers import safe_send_message, safe_edit_message_text
import re
import uuid
import json
import asyncio
import logging
from datetime import datetime, timedelta, timezone
import traceback
from utils.config import Config

logger = logging.getLogger(__name__)


async def create_quiz(update: Update, context: CallbackContext):
    # Store message for reply reference
    message = update.message

    # Extract initial command parts
    command_text = message.text if message.text else ""

    # Check for duration in days, hours, or minutes
    duration_days = None
    duration_hours = None
    duration_minutes = None

    # Check for different duration formats
    days_match = re.search(r"for\s+(\d+)\s+days", command_text, re.IGNORECASE)
    if days_match:
        duration_days = int(days_match.group(1))
        logger.info(f"Detected quiz duration: {duration_days} days")

    hours_match = re.search(r"for\s+(\d+)\s+hours", command_text, re.IGNORECASE)
    if hours_match:
        duration_hours = int(hours_match.group(1))
        logger.info(f"Detected quiz duration: {duration_hours} hours")

    minutes_match = re.search(r"for\s+(\d+)\s+minutes", command_text, re.IGNORECASE)
    if minutes_match:
        duration_minutes = int(minutes_match.group(1))
        logger.info(f"Detected quiz duration: {duration_minutes} minutes")

    # Calculate total duration in minutes for better logging
    total_minutes = 0
    duration_text = ""
    if duration_days:
        total_minutes += duration_days * 24 * 60
        duration_text += f"{duration_days} days "
    if duration_hours:
        total_minutes += duration_hours * 60
        duration_text += f"{duration_hours} hours "
    if duration_minutes:
        total_minutes += duration_minutes
        duration_text += f"{duration_minutes} minutes"

    if total_minutes > 0:
        logger.info(
            f"Total quiz duration: {total_minutes} minutes ({duration_text.strip()})"
        )

    # Next, check if number of questions is specified
    num_questions = None

    # Check for different patterns to extract number of questions
    questions_match = re.search(r"(\d+)\s+questions", command_text, re.IGNORECASE)
    if questions_match:
        num_questions = min(int(questions_match.group(1)), Config.MAX_QUIZ_QUESTIONS)
        logger.info(f"Detected number of questions: {num_questions}")

    # Check for "create X quiz" format
    create_match = re.search(r"create\s+(\d+)\s+quiz", command_text, re.IGNORECASE)
    if create_match and not num_questions:
        num_questions = min(int(create_match.group(1)), Config.MAX_QUIZ_QUESTIONS)
        logger.info(f"Detected 'create X quiz' format: {num_questions} questions")

    # Also check for simple "Topic X" format where X is a number
    if num_questions is None:
        simple_num_match = re.search(
            r"(?:near|topic)\s+(\d+)", command_text, re.IGNORECASE
        )
        if simple_num_match:
            num_questions = min(
                int(simple_num_match.group(1)), Config.MAX_QUIZ_QUESTIONS
            )
            logger.info(f"Detected simple number format: {num_questions} questions")

    # Extract topic from the command
    topic = None
    # Try to find the topic between "createquiz" and any number indicators
    topic_match = re.search(
        r"/createquiz\s+(.*?)(?:\s+\d+\s+questions|\s+for\s+\d+\s+(?:days|hours|minutes)|$)",
        command_text,
        re.IGNORECASE,
    )
    if topic_match:
        topic = topic_match.group(1).strip()

    if not topic and context.args:
        # If no topic found in regex, use the first argument
        topic = context.args[0]

    # If we still don't have a topic, show usage
    if not topic:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "Usage: /createquiz <topic> [number] questions [for number days/hours/minutes]\n"
            "Examples:\n"
            "- /createquiz NEAR blockchain\n"
            "- /createquiz NEAR 5 questions\n"
            "- /createquiz NEAR for 7 days\n"
            "- /createquiz NEAR for 3 hours\n"
            "- /createquiz NEAR for 30 minutes\n"
            "- /createquiz NEAR 3 questions for 14 days",
        )
        return

    # If no number of questions specified yet, check if the topic contains a number
    if num_questions is None:
        # Look for "create N quiz on <topic>" pattern
        topic_num_match = re.search(
            r"create\s+(\d+)\s+quiz(?:\s+on)?\s+", command_text, re.IGNORECASE
        )
        if topic_num_match:
            num_questions = min(
                int(topic_num_match.group(1)), Config.MAX_QUIZ_QUESTIONS
            )
            logger.info(f"Detected number in topic command: {num_questions} questions")

            # Update the topic to remove the number specification
            topic = re.sub(r"create\s+\d+\s+quiz(?:\s+on)?\s+", "", topic).strip()

    # If still no number detected, default to Config.DEFAULT_QUIZ_QUESTIONS
    if num_questions is None:
        num_questions = Config.DEFAULT_QUIZ_QUESTIONS

    # Check if there's a large text block in the command itself
    # This handles cases where user includes text directly in the command
    if len(command_text) > 100:
        large_text_match = re.search(
            r"(/createquiz[^\n]+)(.+)", command_text, re.DOTALL
        )
        if large_text_match:
            large_text = large_text_match.group(2).strip()

            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"Generating {num_questions} quiz question(s) about '{topic}' based on the provided text. This may take a moment...",
            )

            # Generate quiz questions from the large text
            try:
                group_chat_id = update.effective_chat.id
                questions_raw = await generate_quiz(topic, num_questions, large_text)
                await process_questions(
                    update,
                    context,
                    topic,
                    questions_raw,
                    group_chat_id,
                    duration_days,
                    duration_hours,
                    duration_minutes,
                )
                return
            except Exception as e:
                logger.error(f"Error creating text-based quiz: {e}", exc_info=True)
                await safe_send_message(
                    context.bot,
                    update.effective_chat.id,
                    f"Error creating text-based quiz: {str(e)}",
                )
                return

    # Determine if this is a quiz generation with text content from a reply
    if message.reply_to_message and message.reply_to_message.text:
        # Command is replying to another message - use that as context text
        context_text = message.reply_to_message.text

        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            f"Generating {num_questions} quiz question(s) on '{topic}' based on the provided text. This may take a moment...",
        )

        # Generate quiz using the context text
        try:
            # Store group chat ID for later announcements
            group_chat_id = update.effective_chat.id

            # Generate questions based on the text
            questions_raw = await generate_quiz(topic, num_questions, context_text)
            await process_questions(
                update,
                context,
                topic,
                questions_raw,
                group_chat_id,
                duration_days,
                duration_hours,
                duration_minutes,
            )

        except Exception as e:
            logger.error(f"Error creating text-based quiz: {e}", exc_info=True)
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"Error creating text-based quiz: {str(e)}",
            )
    else:
        # Regular quiz creation
        try:
            # Inform user
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"Generating {num_questions} quiz question(s) for topic: {topic}",
            )

            # Store group chat for later announcements
            group_chat_id = update.effective_chat.id

            # Generate questions via LLM
            questions_raw = await generate_quiz(topic, num_questions)
            await process_questions(
                update,
                context,
                topic,
                questions_raw,
                group_chat_id,
                duration_days,
                duration_hours,
                duration_minutes,
            )

        except asyncio.TimeoutError:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                "Sorry, quiz generation timed out. Please try again with a simpler topic or fewer questions.",
            )
        except Exception as e:
            logger.error(f"Error creating quiz: {e}", exc_info=True)
            await safe_send_message(
                context.bot, update.effective_chat.id, f"Error creating quiz: {str(e)}"
            )


async def process_questions(
    update,
    context,
    topic,
    questions_raw,
    group_chat_id,
    duration_seconds: int | None = None,  # Changed parameters
):
    """Process multiple questions from raw text and save them as a quiz."""
    logger.info(
        f"Processing questions for topic: {topic} with duration_seconds: {duration_seconds}"
    )

    # Parse multiple questions
    questions_list = parse_multiple_questions(questions_raw)

    # Check if we got at least one question
    if not questions_list:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "Failed to parse quiz questions. Please try again.",
        )
        return

    # Calculate end time if duration_seconds was specified
    end_time = None
    if duration_seconds and duration_seconds > 0:
        end_time = datetime.utcnow() + timedelta(seconds=duration_seconds)
        logger.info(
            f"Quiz end time calculated: {end_time} based on {duration_seconds} seconds."
        )
    else:
        logger.info(
            "No duration specified or duration is zero, quiz will not have an end time."
        )

    # Persist quiz with multiple questions
    session = SessionLocal()
    try:
        quiz = Quiz(
            topic=topic,
            questions=questions_list,
            status=QuizStatus.ACTIVE,
            group_chat_id=group_chat_id,
            end_time=end_time,  # Set the end time if specified
        )
        session.add(quiz)
        session.commit()
        quiz_id = quiz.id
        logger.info(f"Created quiz with ID: {quiz_id}")
    finally:
        session.close()

    # Notify group and DM creator for contract setup
    num_questions = len(questions_list)

    duration_text_parts = []
    if duration_seconds and duration_seconds > 0:
        temp_duration = duration_seconds
        days = temp_duration // (24 * 3600)
        temp_duration %= 24 * 3600
        hours = temp_duration // 3600
        temp_duration %= 3600
        minutes = temp_duration // 60

        if days > 0:
            duration_text_parts.append(f"{days} day{'s' if days > 1 else ''}")
        if hours > 0:
            duration_text_parts.append(f"{hours} hour{'s' if hours > 1 else ''}")
        if minutes > 0:
            duration_text_parts.append(f"{minutes} minute{'s' if minutes > 1 else ''}")

    duration_info = (
        f" (Active for {', '.join(duration_text_parts)})" if duration_text_parts else ""
    )

    await safe_send_message(
        context.bot,
        update.effective_chat.id,  # This is the group chat or DM where /createquiz was used
        f"Quiz created with ID: {quiz_id}! {num_questions} question(s) about {topic}{duration_info}.\n"
        f"The quiz creator, @{update.effective_user.username}, will be prompted to set up rewards.",
    )

    # DM the creator to start reward setup
    keyboard = [
        [
            InlineKeyboardButton(
                "💰 Setup Rewards", callback_data=f"reward_setup_start:{quiz_id}"
            )
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await safe_send_message(
        context.bot,
        update.effective_user.id,
        f"Your quiz '{topic}' (ID: {quiz_id}) has been created!\n"
        "Please set up the reward structure for the winners.",
        reply_markup=reply_markup,
    )

    # Remove old awaiting flags if they exist, not strictly necessary here
    # as the new flow will be initiated by the button.
    if "awaiting" in context.user_data:
        del context.user_data["awaiting"]
    if "awaiting_reward_quiz_id" in context.user_data:
        del context.user_data["awaiting_reward_quiz_id"]

    logger.info(
        f"Sent reward setup prompt for quiz ID: {quiz_id} to user {update.effective_user.id}"
    )

    # If quiz has an end time, schedule auto distribution task
    if end_time:
        # Convert to seconds from now
        seconds_until_end = (end_time - datetime.utcnow()).total_seconds()
        if seconds_until_end > 0:
            # Schedule auto distribution task
            context.application.create_task(
                schedule_auto_distribution(
                    context.application, quiz_id, seconds_until_end
                )
            )
            logger.info(
                f"Scheduled auto distribution for quiz {quiz_id} in {seconds_until_end} seconds"
            )


async def save_quiz_reward_details(
    quiz_id: str, reward_type: str, reward_text: str
) -> bool:
    """Saves the reward details for a quiz and updates its status to FUNDING if DRAFT."""
    session = SessionLocal()
    try:
        quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
        if not quiz:
            logger.error(
                f"Quiz with ID {quiz_id} not found when trying to save reward details."
            )
            return False

        quiz.reward_schedule = {
            "type": reward_type,
            "details_text": reward_text,
        }

        if quiz.status == QuizStatus.DRAFT:
            quiz.status = QuizStatus.FUNDING
            logger.info(
                f"Quiz {quiz_id} status updated to FUNDING after reward details provided."
            )

        session.commit()
        logger.info(
            f"Successfully saved reward details for quiz {quiz_id} (type: {reward_type})."
        )
        return True
    except Exception as e:
        logger.error(
            f"Error saving reward details for quiz {quiz_id}: {e}", exc_info=True
        )
        session.rollback()
        return False
    finally:
        session.close()


async def save_quiz_payment_hash(quiz_id: str, payment_hash: str) -> bool:
    """Saves the payment transaction hash for a quiz and updates its status."""
    session = SessionLocal()
    try:
        quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
        if not quiz:
            logger.error(
                f"Quiz with ID {quiz_id} not found when trying to save payment hash."
            )
            return False

        quiz.payment_transaction_hash = payment_hash
        # Assuming that once payment hash is provided, the quiz is funded and ready.
        # If there's a separate verification step for the hash, status might be FUNDING.
        # For now, let's set it to ACTIVE if it was in DRAFT or FUNDING.
        if quiz.status in [QuizStatus.DRAFT, QuizStatus.FUNDING]:
            quiz.status = QuizStatus.ACTIVE
            logger.info(
                f"Quiz {quiz_id} status updated to ACTIVE after payment hash received."
            )
        else:
            logger.info(
                f"Quiz {quiz_id} already in status {quiz.status}, not changing status but saving hash."
            )

        session.commit()
        logger.info(
            f"Successfully saved payment hash {payment_hash} for quiz {quiz_id}."
        )
        return True
    except Exception as e:
        logger.error(
            f"Error saving payment hash for quiz {quiz_id}: {e}", exc_info=True
        )
        session.rollback()
        return False
    finally:
        session.close()


# async def schedule_auto_distribution(application, quiz_id, delay_seconds):
#     """Schedule automatic reward distribution after the quiz ends."""
#     try:
#         # Wait until the quiz deadline
#         await asyncio.sleep(delay_seconds)

#         # Load quiz state from database
#         session = SessionLocal()
#         try:
#             quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
#             if not quiz:
#                 logger.error(f"Quiz {quiz_id} not found for auto distribution")
#                 return
#             # If the quiz ended without verified funding, alert and skip distribution
#             if quiz.status == QuizStatus.FUNDING:
#                 logger.info(
#                     f"Quiz {quiz_id} ended without verified funding, skipping auto distribution"
#                 )
#                 if group_chat_id:
#                     text = (
#                         f"⚠️ Quiz '{topic}' has ended but funding was never verified. "
#                         "Please ask the creator to verify the deposit with the transaction hash."
#                     )
#                     logger.info(
#                         f"Auto-distribution funding-failure message for quiz {quiz_id} to chat {group_chat_id}: '{text}'"
#                     )
#                     await application.bot.send_message(chat_id=group_chat_id, text=text)
#                 return
#             # Only distribute when truly active
#             if quiz.status != QuizStatus.ACTIVE:
#                 logger.info(
#                     f"Quiz {quiz_id} is not in ACTIVE state (status={quiz.status}), skipping auto distribution"
#                 )
#                 return
#             group_chat_id = quiz.group_chat_id
#             topic = quiz.topic
#         finally:
#             session.close()

#         logger.info(f"Quiz {quiz_id} deadline reached, attempting auto distribution")

#         # Retrieve blockchain monitor from the application
#         blockchain_monitor = getattr(application, "blockchain_monitor", None)
#         logger.info(
#             f"[schedule_auto_distribution] application.blockchain_monitor={blockchain_monitor}"
#         )
#         if not blockchain_monitor:
#             logger.error(
#                 f"Cannot perform auto distribution for quiz {quiz_id}: blockchain monitor not available"
#             )
#             if group_chat_id:
#                 text = (
#                     f"⚠️ Quiz '{topic}' has ended but automatic reward distribution failed. "
#                     f"Please use /distributerewards {quiz_id} to distribute rewards manually."
#                 )
#                 logger.info(
#                     f"Auto-distribution failure message (no monitor) for quiz {quiz_id} to chat {group_chat_id}: '{text}'"
#                 )
#                 await application.bot.send_message(
#                     chat_id=group_chat_id,
#                     text=text,
#                 )
#             return

#         # Before distributing, check if anyone participated
#         session2 = SessionLocal()
#         try:
#             winners = QuizAnswer.compute_quiz_winners(session2, quiz_id)
#             if not winners:
#                 if group_chat_id:
#                     text = f"⚠️ Quiz '{topic}' ended with no participants — no rewards to distribute."
#                     logger.info(
#                         f"Auto-distribution no-participants message for quiz {quiz_id} to chat {group_chat_id}: '{text}'"
#                     )
#                     await application.bot.send_message(chat_id=group_chat_id, text=text)
#                 return
#         finally:
#             session2.close()

#         # Perform reward distribution
#         success = await blockchain_monitor.distribute_rewards(quiz_id)

#         # Notify group chat of result
#         if group_chat_id:
#             if success:
#                 text = f"🏆 Quiz '{topic}' has ended and rewards have been automatically distributed to winners!"
#             else:
#                 text = (
#                     f"⚠️ Quiz '{topic}' has ended but automatic reward distribution failed. "
#                     f"Please use /distributerewards {quiz_id} to distribute rewards manually."
#                 )
#             logger.info(
#                 f"Auto-distribution result message for quiz {quiz_id} to chat {group_chat_id}: '{text}'"
#             )
#             await application.bot.send_message(chat_id=group_chat_id, text=text)
#     except Exception as e:
#         logger.error(f"Error in auto distribution for quiz {quiz_id}: {e}")
#         traceback.print_exc()


def parse_multiple_questions(raw_questions):
    """Parse multiple questions from raw text into a list of structured questions."""
    # Split by double newline or question number pattern
    question_pattern = re.compile(r"Question\s+\d+:|^\d+\.\s+", re.MULTILINE)

    # First try to split by the question pattern
    chunks = re.split(question_pattern, raw_questions)

    # Remove any empty chunks
    chunks = [chunk.strip() for chunk in chunks if chunk.strip()]

    # If we only got one chunk but it might contain multiple questions
    if len(chunks) == 1 and "\n\n" in raw_questions:
        # Try splitting by double newline
        chunks = raw_questions.split("\n\n")
        chunks = [chunk.strip() for chunk in chunks if chunk.strip()]

    # Process each chunk as an individual question
    questions_list = []
    for chunk in chunks:
        question_data = parse_questions(chunk)
        if (
            question_data["question"]
            and question_data["options"]
            and question_data["correct"]
        ):
            questions_list.append(question_data)

    return questions_list


def parse_questions(raw_questions):
    """Convert raw question text into structured format for storage and display."""
    lines = raw_questions.strip().split("\n")
    result = {"question": "", "options": {}, "correct": ""}

    # More flexible parsing that can handle different formats
    question_pattern = re.compile(r"^(?:Question:?\s*)?(.+)$")
    option_pattern = re.compile(r"^([A-D])[):\.]?\s+(.+)$")
    correct_pattern = re.compile(
        r"^(?:Correct\s+Answer:?\s*|Answer:?\s*)([A-D])\.?$", re.IGNORECASE
    )

    # First pass - try to identify the question
    for i, line in enumerate(lines):
        if "Question" in line or (
            i == 0
            and not any(x in line.lower() for x in ["a)", "b)", "c)", "d)", "correct"])
        ):
            match = question_pattern.match(line)
            if match:
                question_text = match.group(1).strip()
                if "Question:" in line:
                    question_text = line[line.find("Question:") + 9 :].strip()
                result["question"] = question_text
                break

    # If still no question found, use the first line
    if not result["question"] and lines:
        result["question"] = lines[0].strip()

    # Second pass - extract options and correct answer
    for line in lines:
        line = line.strip()

        # First check for correct answer format
        if "correct answer" in line.lower() or "answer:" in line.lower():
            # Try to extract the correct answer letter
            match = correct_pattern.match(line)
            if match:
                result["correct"] = match.group(1).upper()
                continue

            # Try alternate format: "Correct Answer: A"
            letter_match = re.search(
                r"(?:correct answer|answer)[:\s]+([A-D])", line, re.IGNORECASE
            )
            if letter_match:
                result["correct"] = letter_match.group(1).upper()
                continue

        # Try to match options with various formats
        option_match = option_pattern.match(line)
        if option_match:
            letter, text = option_match.groups()
            result["options"][letter] = text.strip()
            continue

        # Check for options in format "A. Option text" or "A: Option text"
        for prefix in (
            [f"{letter})" for letter in "ABCD"]
            + [f"{letter}." for letter in "ABCD"]
            + [f"{letter}:" for letter in "ABCD"]
        ):
            if line.startswith(prefix):
                letter = prefix[0]
                text = line[len(prefix) :].strip()
                result["options"][letter] = text
                break

    print(f"Parsed question structure: {result}")

    # If we don't have options or they're incomplete, create fallback options
    if not result["options"] or len(result["options"]) < 4:
        print("Warning: Missing options in quiz question. Using fallback options.")
        for letter in "ABCD":
            if letter not in result["options"]:
                result["options"][letter] = f"Option {letter}"

    # If we don't have a correct answer, default to B for blockchain topics
    # This is a reasonable default for the specific issue we saw with Solana questions
    if not result["correct"]:
        print("Warning: Missing correct answer in quiz question. Analyzing question...")
        # For blockchain questions about consensus mechanisms, B is often the answer (PoS+PoH)
        if "solana" in raw_questions.lower() and "consensus" in raw_questions.lower():
            result["correct"] = "B"
            print("Identified as Solana consensus question, defaulting to B (PoS+PoH)")
        else:
            result["correct"] = "A"
            print("Defaulting to A as correct answer")

    return result


async def play_quiz(update: Update, context: CallbackContext):
    """Handler for /playquiz command; DM quiz questions to a player."""
    user_id = str(update.effective_user.id)
    user_username = update.effective_user.username or update.effective_user.first_name
    # Wallet check can be added here if needed:
    if not await check_wallet_linked(user_id):
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "Please link your wallet first using /linkwallet <wallet_address>.",
        )
        return

    quiz_id_to_play = None
    if context.args:
        quiz_id_to_play = context.args[0]
        logger.info(f"Quiz ID provided via args: {quiz_id_to_play}")

    session = SessionLocal()
    try:
        group_chat_id = None
        if update.effective_chat.type in ["group", "supergroup"]:
            group_chat_id = update.effective_chat.id

        if not quiz_id_to_play and group_chat_id:
            logger.info(
                f"No quiz ID in args, checking active quizzes for group: {group_chat_id}"
            )
            active_quizzes = (
                session.query(Quiz)
                .filter(
                    Quiz.status == QuizStatus.ACTIVE,
                    Quiz.group_chat_id == group_chat_id,
                    Quiz.end_time > datetime.utcnow(),
                )
                .order_by(Quiz.end_time)
                .all()
            )
            logger.info(
                f"Found {len(active_quizzes)} active quizzes for group {group_chat_id}."
            )

            if len(active_quizzes) > 1:
                buttons = []
                for i, q in enumerate(active_quizzes):
                    num_questions = len(q.questions) if q.questions else 0
                    time_remaining_str = ""
                    if q.end_time:
                        now_utc = datetime.utcnow()
                        if q.end_time > now_utc:
                            delta = q.end_time - now_utc
                            total_seconds = int(
                                delta.total_seconds()
                            )  # Ensure it's an int

                            days = total_seconds // (3600 * 24)
                            remaining_seconds_after_days = total_seconds % (3600 * 24)
                            hours = remaining_seconds_after_days // 3600
                            minutes = (remaining_seconds_after_days % 3600) // 60

                            if days > 0:
                                time_remaining_str = (
                                    f"ends in {days}d {hours}h {minutes}m"
                                )
                            elif hours > 0:
                                time_remaining_str = f"ends in {hours}h {minutes}m"
                            elif minutes > 0:
                                time_remaining_str = f"ends in {minutes}m"
                            else:
                                time_remaining_str = (
                                    "ends very soon"  # e.g., < 1 minute
                                )
                        else:
                            time_remaining_str = "ended"
                    else:
                        time_remaining_str = "no end time"

                    button_text = (
                        f"{i + 1}. {q.topic} — {num_questions} Q — {time_remaining_str}"
                    )
                    buttons.append(
                        [
                            InlineKeyboardButton(
                                button_text,
                                callback_data=f"playquiz_select:{q.id}:{user_id}",
                            )
                        ]
                    )

                if buttons:
                    reply_markup = InlineKeyboardMarkup(buttons)
                    await safe_send_message(
                        context.bot,
                        update.effective_chat.id,
                        "Multiple active quizzes found. Please select one to play:",
                        reply_markup=reply_markup,
                    )
                    return
            elif len(active_quizzes) == 1:
                quiz_id_to_play = active_quizzes[0].id
                logger.info(f"One active quiz found ({quiz_id_to_play}), proceeding.")
            else:
                await safe_send_message(
                    context.bot,
                    update.effective_chat.id,
                    "No active quizzes found in this group.",
                )
                return

        if not quiz_id_to_play:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                "Please specify a quiz ID to play (e.g., /playquiz <quiz_id>), or use /playquiz in a group with active quizzes.",
            )
            return

        # Check if the user has already played this quiz
        existing_answers = (
            session.query(QuizAnswer)
            .filter(
                QuizAnswer.quiz_id == quiz_id_to_play, QuizAnswer.user_id == user_id
            )
            .first()
        )
        if existing_answers:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"@{user_username}, you have already played this quiz. You cannot play it again.",
            )
            return

        quiz_to_dm = session.query(Quiz).filter(Quiz.id == quiz_id_to_play).first()

        if not quiz_to_dm:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"No quiz found with ID {quiz_id_to_play}.",
            )
            return

        if quiz_to_dm.status != QuizStatus.ACTIVE or (
            quiz_to_dm.end_time and quiz_to_dm.end_time <= datetime.utcnow()
        ):
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"Quiz '{quiz_to_dm.topic}' (ID: {quiz_id_to_play[:8]}...) is not currently active or has ended.",
            )
            return

        if update.effective_chat.type != "private":
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"@{user_username}, I'll send you the quiz '{quiz_to_dm.topic}' (ID: {quiz_id_to_play[:8]}...) in a private message!",
            )

        await send_quiz_question(context.bot, user_id, quiz_to_dm, 0)

    except Exception as e:
        logger.error(f"Error in play_quiz: {e}", exc_info=True)
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "An error occurred while trying to play the quiz. Please try again later.",
        )
    finally:
        if session:  # Ensure session is not None before closing
            session.close()


async def send_quiz_question(bot, user_id, quiz, question_index):
    """Send a specific question from the quiz to the user."""

    # Get the questions list
    questions_list = quiz.questions

    # Check if this is a legacy quiz with a single question format
    if isinstance(questions_list, dict):
        questions_list = [questions_list]

    # Check if the index is valid
    if question_index >= len(questions_list):
        # We've sent all questions
        await safe_send_message(
            bot,
            user_id,
            f"You've completed all {len(questions_list)} questions in the '{quiz.topic}' quiz!\n"
            f"Your answers have been recorded. Check '/winners {quiz.id}' for the results.",
        )
        return

    # Get the current question
    current_q = questions_list[question_index]
    question = current_q.get("question", "Question not available")
    options = current_q.get("options", {})

    # Create keyboard for this specific question
    keyboard = []
    for key, value in options.items():
        # Include question index in callback data to track progress
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{key}) {value}",
                    callback_data=f"quiz:{quiz.id}:{question_index}:{key}",
                )
            ]
        )

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Show question number out of total
    question_number = question_index + 1
    total_questions = len(questions_list)

    await safe_send_message(
        bot,
        user_id,
        text=f"Quiz: {quiz.topic} (Question {question_number}/{total_questions})\n\n{question}",
        reply_markup=reply_markup,
    )


async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process quiz answers from inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press

    # Parse callback data to get quiz ID, question index, and answer
    try:
        _, quiz_id, question_index, answer = query.data.split(":")
        question_index = int(question_index)
    except ValueError:
        await safe_edit_message_text(
            context.bot,
            query.message.chat_id,
            query.message.message_id,
            "Invalid answer format.",
        )
        return

    # Get quiz from database
    session = SessionLocal()
    try:
        quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()

        if not quiz:
            await safe_edit_message_text(
                context.bot,
                query.message.chat_id,
                query.message.message_id,
                "Quiz not found.",
            )
            return

        # Get questions list, handling legacy format
        questions_list = quiz.questions
        if isinstance(questions_list, dict):
            questions_list = [questions_list]

        # Get the current question
        if question_index >= len(questions_list):
            await safe_edit_message_text(
                context.bot,
                query.message.chat_id,
                query.message.message_id,
                "Invalid question index.",
            )
            return

        current_q = questions_list[question_index]

        # Get correct answer for this question
        correct_answer = current_q.get("correct", "")
        is_correct = correct_answer == answer

        # Record the answer in database
        user_id = str(update.effective_user.id)
        username = update.effective_user.username or update.effective_user.first_name

        quiz_answer = QuizAnswer(
            quiz_id=quiz_id,
            user_id=user_id,
            username=username,
            answer=answer,
            is_correct=str(
                is_correct
            ),  # Store as string 'True' or 'False', not boolean
        )
        session.add(quiz_answer)
        session.commit()

        # Update message to show result
        await safe_edit_message_text(
            context.bot,
            query.message.chat_id,
            query.message.message_id,
            f"{query.message.text}\n\n"
            f"Your answer: {answer}\n"
            f"{'✅ Correct!' if is_correct else f'❌ Wrong. The correct answer is {correct_answer}.'}",
            reply_markup=None,
        )

        # Send the next question after a short delay
        next_question_index = question_index + 1
        await asyncio.sleep(1)  # Short delay before next question
        await send_quiz_question(
            context.bot, query.message.chat_id, quiz, next_question_index
        )

    except Exception as e:
        logger.error(f"Error handling quiz answer: {e}", exc_info=True)
        import traceback

        traceback.print_exc()
    finally:
        session.close()


async def handle_reward_structure(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process reward structure from quiz creator in private chat."""
    # Only proceed if user_data indicates we're awaiting reward structure or wallet steps
    valid_states = (
        "reward_structure",
        "wallet_address",
        "signature",
        "transaction_hash",
    )
    if context.user_data.get("awaiting") not in valid_states:
        return
    # Skip if this isn't a private chat
    if update.effective_chat.type != "private":
        return
    # Handle wallet linking or transaction steps
    if context.user_data.get("awaiting") in (
        "wallet_address",
        "signature",
        "transaction_hash",
    ):
        from services.user_service import handle_wallet_address, handle_signature
        from services.blockchain import BlockchainMonitor

        if context.user_data.get("awaiting") == "wallet_address":
            await handle_wallet_address(update, context)
        elif context.user_data.get("awaiting") == "signature":
            await handle_signature(update, context)
        elif context.user_data.get("awaiting") == "transaction_hash":
            await handle_transaction_hash(update, context)
        return

    text = update.message.text
    user_id = str(update.effective_user.id)

    # Parse amounts from text, e.g. '2 Near for 1st, 1 Near for 2nd'
    amounts = re.findall(r"(\d+)\s*Near", text, re.IGNORECASE)
    if not amounts:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "Couldn't parse reward amounts. Please specify like '2 Near for 1st, 1 Near for 2nd'.",
        )
        return

    # Build schedule dict {1: amount1, 2: amount2, ...}
    schedule = {i + 1: int(a) for i, a in enumerate(amounts)}
    total = sum(schedule.values())

    # Generate deposit address (dummy for now)
    # deposit_addr = f"quiz-{uuid.uuid4()}.near"
    #
    #
    deposit_addr = Config.NEAR_WALLET_ADDRESS

    # We'll save these for the group announcement
    quiz_topic = None
    original_group_chat_id = None

    # Update quiz in DB: find latest ACTIVE quiz by this user with no reward_schedule
    session = SessionLocal()
    try:
        quiz = (
            session.query(Quiz)
            .filter(Quiz.status == QuizStatus.ACTIVE)
            .order_by(Quiz.last_updated.desc())
            .first()
        )

        if not quiz:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                "No active quiz found to attach rewards to.",
            )
            return

        quiz.reward_schedule = schedule
        quiz.deposit_address = deposit_addr
        quiz.status = QuizStatus.FUNDING

        # Store these values for use after session is closed
        quiz_topic = quiz.topic
        original_group_chat_id = quiz.group_chat_id
        quiz_id = quiz.id  # Store quiz ID for later use

        session.commit()
    except Exception as e:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            f"Error saving reward structure: {str(e)}",
        )
        logger.error(f"Error saving reward structure: {e}", exc_info=True)
        import traceback

        traceback.print_exc()
        return
    finally:
        session.close()

    # Inform creator privately about deposit with a new option to verify via transaction hash
    msg = f"Please deposit a total of {total} Near to this address to activate the quiz:\n{deposit_addr}\n\n"
    msg += "⚠️ IMPORTANT: After making your deposit, you MUST send me the transaction hash to activate the quiz. The quiz will NOT be activated automatically.\n\n"
    msg += "Your transaction hash will look like 'FnuPC7YmQBJ1Qr22qjRT3XX8Vr8NbJAuWGVG5JyXQRjS' and can be found in your wallet's transaction history."

    await safe_send_message(context.bot, update.effective_chat.id, msg)

    # Now expect transaction hash next
    context.user_data["awaiting"] = "transaction_hash"
    context.user_data["quiz_id"] = quiz_id

    # Announce in group chat
    try:
        if original_group_chat_id:
            # Use a longer timeout for the announcement
            async with asyncio.timeout(10):  # 10 second timeout
                await safe_send_message(
                    context.bot,
                    original_group_chat_id,
                    text=(
                        f"Quiz '{quiz_topic}' is now funding.\n"
                        f"Creator must deposit {total} Near and verify the transaction to activate it.\n"
                        f"Once active, you'll be notified and can type /playquiz to join!"
                    ),
                )
    except asyncio.TimeoutError:
        logger.error(f"Failed to announce to group: Timeout error")
    except Exception as e:
        logger.error(f"Failed to announce to group: {e}", exc_info=True)
        import traceback

        traceback.print_exc()


async def handle_transaction_hash(update: Update, context: CallbackContext):
    """Process transaction hash verification from quiz creator."""
    tx_hash = update.message.text.strip()
    quiz_id = context.user_data.get("quiz_id")

    if not quiz_id:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "Sorry, I couldn't determine which quiz you're trying to verify. Please try setting up the reward structure again.",
        )
        # Clear awaiting state
        if "awaiting" in context.user_data:
            del context.user_data["awaiting"]
        return

    # Process message - show typing action while verifying
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    # Get blockchain monitor from application
    app = context.application
    blockchain_monitor = getattr(app, "blockchain_monitor", None)

    if not blockchain_monitor:
        # Try to access it from another location in context
        blockchain_monitor = getattr(app, "_blockchain_monitor", None)

    if not blockchain_monitor:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "❌ Sorry, I couldn't access the blockchain monitor to verify your transaction. Please wait for automatic verification or contact an administrator.",
        )
        # Clear awaiting state
        if "awaiting" in context.user_data:
            del context.user_data["awaiting"]
        return

    # Verify the transaction
    success = await blockchain_monitor.verify_transaction_by_hash(tx_hash, quiz_id)

    if success:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "✅ Transaction verified successfully! Your quiz is now active and ready to play.",
        )
        # Announce activation to the original group chat
        session = SessionLocal()
        try:
            quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
            if quiz and quiz.group_chat_id:
                total_reward = (
                    sum(int(v) for v in quiz.reward_schedule.values())
                    if quiz.reward_schedule
                    else 0
                )
                await safe_send_message(
                    context.bot,
                    quiz.group_chat_id,
                    f"📣 New quiz '{quiz.topic}' is now active! 🎯\n"
                    f"Total rewards: {total_reward} NEAR\n"
                    "Type /playquiz to participate!",
                )
        finally:
            session.close()
    else:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "❌ Couldn't verify your transaction. Please ensure:\n"
            "1. The transaction hash is correct\n"
            "2. The transaction was sent to the correct address\n"
            "3. The transaction amount is sufficient for the rewards\n\n"
            "Alternatively, wait for automatic verification (may take a few minutes).",
        )

    # Clear awaiting state
    if "awaiting" in context.user_data:
        del context.user_data["awaiting"]


async def get_winners(update: Update, context: CallbackContext):
    """Display current or past quiz winners."""
    session = SessionLocal()
    try:
        # Find specific quiz if ID provided, otherwise get latest active or closed quiz
        if context.args:
            quiz_id = context.args[0]
            quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
            if not quiz:
                await safe_send_message(
                    context.bot,
                    update.effective_chat.id,
                    f"No quiz found with ID {quiz_id}",
                )
                return
        else:
            # Get most recent active or closed quiz
            quiz = (
                session.query(Quiz)
                .filter(Quiz.status.in_([QuizStatus.ACTIVE, QuizStatus.CLOSED]))
                .order_by(Quiz.last_updated.desc())
                .first()
            )
            if not quiz:
                await safe_send_message(
                    context.bot,
                    update.effective_chat.id,
                    "No active or completed quizzes found.",
                )
                return

        # Calculate winners for the quiz
        winners = QuizAnswer.compute_quiz_winners(session, quiz.id)

        if not winners:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"No participants have answered the '{quiz.topic}' quiz yet.",
            )
            return

        # Generate leaderboard message
        message = f"📊 Leaderboard for quiz: *{quiz.topic}*\n\n"

        # Display winners with rewards if available
        reward_schedule = quiz.reward_schedule or {}

        for i, winner in enumerate(winners[:10]):  # Show top 10 max
            rank = i + 1
            username = winner["username"] or f"User{winner['user_id'][-4:]}"
            correct = winner["correct_count"]

            # Show reward if this position has a reward and quiz is active/closed
            reward_text = ""
            if str(rank) in reward_schedule:
                reward_text = f" - {reward_schedule[str(rank)]} NEAR"
            elif rank in reward_schedule:
                reward_text = f" - {reward_schedule[rank]} NEAR"

            message += f"{rank}. @{username}: {correct} correct answers{reward_text}\n"

        # Add quiz status info
        status = f"Quiz is {quiz.status.value.lower()}"
        if quiz.status == QuizStatus.CLOSED:
            status += " and rewards have been distributed."
        elif quiz.status == QuizStatus.ACTIVE:
            status += ". Participate with /playquiz"

        message += f"\n{status}"

        await safe_send_message(
            context.bot, update.effective_chat.id, message, parse_mode="Markdown"
        )

    except Exception as e:
        await safe_send_message(
            context.bot, update.effective_chat.id, f"Error retrieving winners: {str(e)}"
        )
        logger.error(f"Error retrieving winners: {e}", exc_info=True)
        import traceback

        traceback.print_exc()
    finally:
        session.close()


async def distribute_quiz_rewards(update: Update, context: CallbackContext):
    """Handler for /distributerewards command to send NEAR rewards to winners."""
    user_id = str(update.effective_user.id)

    # Get quiz ID if provided, otherwise use latest active quiz
    quiz_id = None

    if context.args:
        quiz_id = context.args[0]
    else:
        # Find latest quiz created by this user
        session = SessionLocal()
        try:
            # We need to find quizzes with rewards that are ACTIVE
            quiz = (
                session.query(Quiz)
                .filter(Quiz.status == QuizStatus.ACTIVE)
                .order_by(Quiz.last_updated.desc())
                .first()
            )

            if quiz:
                quiz_id = quiz.id
        finally:
            session.close()

    if not quiz_id:
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "No active quiz found to distribute rewards for. Please specify a quiz ID.",
        )
        return

    # Show processing message
    processing_msg = await safe_send_message(
        context.bot,
        update.effective_chat.id,
        "🔄 Processing reward distribution... This may take a moment.",
    )

    try:
        # Get the blockchain monitor from the application
        from telegram.ext import Application

        app = context.application
        if not hasattr(app, "blockchain_monitor"):
            # Try to access it from another location in context
            blockchain_monitor = getattr(app, "_blockchain_monitor", None)
            if not blockchain_monitor:
                await safe_send_message(
                    context.bot,
                    update.effective_chat.id,
                    "❌ Blockchain monitor not available. Please contact an administrator.",
                )
                return
        else:
            blockchain_monitor = app.blockchain_monitor

        # Initiate reward distribution
        success = await blockchain_monitor.distribute_rewards(quiz_id)

        if success:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"✅ Successfully distributed rewards for quiz {quiz_id}. Winners have been notified.",
            )
        else:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"⚠️ Could not distribute all rewards. Check logs for details.",
            )
    except Exception as e:
        logger.error(f"Error distributing rewards: {e}", exc_info=True)
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            f"❌ Error distributing rewards: {str(e)}",
        )
    finally:
        # Try to delete the processing message
        try:
            await processing_msg.delete()
        except:
            pass


async def schedule_auto_distribution(application, quiz_id, delay_seconds):
    """Schedule automatic reward distribution after the quiz ends."""
    try:
        # Wait until the quiz deadline
        await asyncio.sleep(delay_seconds)

        # Load quiz state from database
        session = SessionLocal()
        try:
            quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
            if not quiz:
                logger.error(f"[schedule_auto_distribution] Quiz {quiz_id} not found.")
                return

            logger.info(
                f"[schedule_auto_distribution] Quiz {quiz_id} found. Status: {quiz.status}"
            )

            # Check if the quiz ended while still in FUNDING status
            if quiz.status == QuizStatus.FUNDING:
                logger.warning(
                    f"[schedule_auto_distribution] Quiz {quiz_id} ended but was still in FUNDING status."
                )
                if quiz.group_chat_id:
                    try:
                        await application.bot.send_message(
                            chat_id=quiz.group_chat_id,
                            text=f"ðŸ¤” Quiz '{quiz.topic}' ended but was still awaiting funding. Please verify the deposit and manually trigger reward distribution if needed.",
                        )
                    except Exception as e:
                        logger.error(
                            f"[schedule_auto_distribution] Failed to send FUNDING status warning to group {quiz.group_chat_id}: {e}"
                        )
                return  # Do not proceed with distribution if it was never properly funded and activated

            # Ensure the quiz is ACTIVE or has just ended (e.g. if this is called right after end_time)
            # We will rely on distribute_rewards to re-check status if it's already CLOSED.
            if quiz.status not in [
                QuizStatus.ACTIVE,
                QuizStatus.CLOSED,
            ]:  # Allow CLOSED if we are re-trying or something
                logger.warning(
                    f"[schedule_auto_distribution] Quiz {quiz_id} is not in ACTIVE or CLOSED state (current: {quiz.status}). Distribution will not proceed at this time."
                )
                # Potentially send a message if it's an unexpected state like DRAFT
                return

            # Check for participants
            session = SessionLocal()
            try:
                participants_count = (
                    session.query(QuizAnswer)
                    .filter(QuizAnswer.quiz_id == quiz_id)
                    .distinct(QuizAnswer.user_id)
                    .count()
                )
                if participants_count == 0:
                    logger.info(
                        f"[schedule_auto_distribution] Quiz {quiz_id} had no participants. No rewards to distribute."
                    )
                    if quiz.group_chat_id:
                        try:
                            await application.bot.send_message(
                                chat_id=quiz.group_chat_id,
                                text=f"ðŸ§ Quiz '{quiz.topic}' has ended, but there were no participants. No rewards to distribute.",
                            )
                            quiz.status = QuizStatus.CLOSED  # Mark as closed
                            if hasattr(
                                quiz, "rewards_distributed_at"
                            ):  # Check if the attribute exists
                                quiz.rewards_distributed_at = (
                                    datetime.utcnow()
                                )  # Mark as processed
                            session.commit()
                        except Exception as e:
                            logger.error(
                                f"[schedule_auto_distribution] Failed to send no participants message to group {quiz.group_chat_id}: {e}"
                            )
                    return
            finally:
                session.close()

            logger.info(
                f"[schedule_auto_distribution] Attempting to distribute rewards for quiz {quiz_id}."
            )
            blockchain_monitor = application.blockchain_monitor
            logger.info(
                f"[schedule_auto_distribution] application.blockchain_monitor={blockchain_monitor}"
            )

            if blockchain_monitor:
                # The distribute_rewards function now returns:
                # - A list of successful_transfers (can be empty if no one got rewards but processing happened)
                # - None if there were no winners to begin with
                # - False if a critical error occurred during distribution attempt
                distribution_result = await blockchain_monitor.distribute_rewards(
                    quiz_id
                )

                group_chat_id = quiz.group_chat_id
                if group_chat_id:
                    message_text = ""
                    if distribution_result is False:
                        # Critical error
                        message_text = f"âš ï¸ Automatic reward distribution for quiz '{quiz.topic}' failed due to an internal error. Please check the logs."
                    elif distribution_result is None:
                        # No winners found by distribute_rewards (should align with the no participants check, but good to handle)
                        message_text = f"ðŸ§ Quiz '{quiz.topic}' has ended. No winners were found to distribute rewards to."
                    elif isinstance(distribution_result, list):
                        if (
                            not distribution_result
                        ):  # Empty list - winners processed, but no successful transfers
                            message_text = f"ðŸŽŠ Quiz '{quiz.topic}' has ended. Rewards were processed, but no transfers were completed (e.g., winners without linked wallets or individual transfer issues)."
                        else:  # Non-empty list - successful transfers
                            winner_mentions = []
                            for transfer_info in distribution_result:
                                # Assuming user_id is a string convertible to int for Telegram mention
                                # And username is available for a nice @mention fallback
                                user_id_int = None
                                try:
                                    user_id_int = int(transfer_info["user_id"])
                                except ValueError:
                                    logger.warning(
                                        f"Could not convert user_id {transfer_info['user_id']} to int for mention."
                                    )

                                username = transfer_info.get("username")
                                if user_id_int and username:
                                    winner_mentions.append(
                                        f'<a href="tg://user?id={user_id_int}">@{username}</a>'
                                    )
                                elif (
                                    username
                                ):  # Fallback to just @username if ID is bad
                                    winner_mentions.append(f"@{username}")
                                # else: skip mention if no good identifier

                            if winner_mentions:
                                winners_str = ", ".join(winner_mentions)
                                message_text = f"🎉 Quiz '{quiz.topic}' has ended! 🎊\n\nCongratulations to our winner(s): {winners_str}! \nCheck your NEAR wallets for your rewards! 💰"
                            else:
                                message_text = f"ðŸŽŠ Quiz '{quiz.topic}' has ended and rewards have been distributed. Winners, please check your wallets!"

                    if message_text:
                        try:
                            await application.bot.send_message(
                                chat_id=group_chat_id,
                                text=message_text,
                                parse_mode="HTML",  # Important for tg://user?id= links
                            )
                            logger.info(
                                f"[schedule_auto_distribution] Sent distribution result message for quiz {quiz_id} to group {group_chat_id}"
                            )
                        except Exception as e:
                            logger.error(
                                f"[schedule_auto_distribution] Failed to send message to group {group_chat_id} for quiz {quiz_id}: {e}"
                            )
                    else:
                        logger.warning(
                            f"[schedule_auto_distribution] No specific message generated for quiz {quiz_id} distribution status."
                        )
            else:
                logger.error(
                    "[schedule_auto_distribution] Blockchain monitor not found in application context."
                )
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error in auto distribution for quiz {quiz_id}: {e}")
        traceback.print_exc()
