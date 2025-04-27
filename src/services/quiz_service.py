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

logger = logging.getLogger(__name__)


async def create_quiz(update: Update, context: CallbackContext):
    # Store message for reply reference
    message = update.message

    # Extract initial command parts
    command_text = message.text if message.text else ""

    # Check if there's a large text block in the command itself
    # This handles cases where user includes text directly in the command
    if "/createquiz" in command_text and len(command_text) > 100:
        # Extract the command part and the content part
        parts = command_text.split(None, 1)
        if len(parts) > 1:
            large_text = parts[1]

            # Check if the text has parameters at the beginning (topic and question count)
            topic_pattern = re.compile(r"^([^0-9\n]{3,50}?)(?:\s+(\d+))?\s+", re.DOTALL)
            topic_match = topic_pattern.match(large_text)

            topic = "Content Analysis"
            num_questions = 3  # Default to 3 questions for large text

            if topic_match:
                topic = topic_match.group(1).strip()
                if topic_match.group(2):
                    num_questions = min(
                        int(topic_match.group(2)), 10
                    )  # Limit to 10 questions
                # Remove the matched part from the text
                large_text = large_text[topic_match.end() :].strip()

            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                f"Generating {num_questions} quiz questions about '{topic}' based on the provided text. This may take a moment...",
            )

            # Generate quiz questions from the large text
            try:
                group_chat_id = update.effective_chat.id
                questions_raw = await generate_quiz(topic, num_questions, large_text)
                await process_questions(
                    update, context, topic, questions_raw, group_chat_id
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

        # Extract parameters from the command
        args = context.args

        # Default topic and num_questions
        topic = "General Knowledge"
        num_questions = 1

        if args:
            # First argument is the topic
            topic = args[0]

            # Check if second argument is the number of questions
            if len(args) > 1 and args[1].isdigit():
                num_questions = min(int(args[1]), 10)  # Limit to 10 questions max

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
                update, context, topic, questions_raw, group_chat_id
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
        # If no arguments provided, show usage message
        if not context.args:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                "Usage: /createquiz <topic> [number_of_questions]\n"
                "Or reply to a text message with: /createquiz <topic> [number_of_questions]",
            )
            return

        # Extract topic and optional number of questions
        args = context.args
        topic = args[0]

        # Check if second argument is number of questions
        num_questions = 1
        if len(args) > 1 and args[1].isdigit():
            num_questions = min(int(args[1]), 10)  # Limit to 10 questions max

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
                update, context, topic, questions_raw, group_chat_id
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


async def process_questions(update, context, topic, questions_raw, group_chat_id):
    """Process multiple questions from raw text and save them as a quiz."""

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

    # Persist quiz with multiple questions
    session = SessionLocal()
    try:
        quiz = Quiz(
            topic=topic,
            questions=questions_list,
            status=QuizStatus.ACTIVE,
            group_chat_id=group_chat_id,
        )
        session.add(quiz)
        session.commit()
        quiz_id = quiz.id
    finally:
        session.close()

    # Notify group and DM creator for contract setup
    num_questions = len(questions_list)
    await safe_send_message(
        context.bot,
        update.effective_chat.id,
        f"Quiz created with ID: {quiz_id}! {num_questions} question(s) about {topic}.\n"
        f"Check your DMs to set up the reward contract.",
    )

    # DM the creator for reward structure details
    await safe_send_message(
        context.bot,
        update.effective_user.id,
        "Please specify the reward structure in this private chat (e.g., '2 Near for 1st, 1 Near for 2nd').",
    )


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

        # Check for correct answer in various formats
        correct_match = correct_pattern.match(line)
        if correct_match or "Correct Answer" in line or "Answer:" in line:
            if correct_match:
                result["correct"] = correct_match.group(1).strip()
            else:
                # Extract just the letter from lines like "Correct Answer: A"
                answer_parts = line.split(":")
                if len(answer_parts) > 1:
                    possible_letter = answer_parts[-1].strip()
                    if possible_letter in "ABCD":
                        result["correct"] = possible_letter

    print(f"Parsed question structure: {result}")

    # If we don't have options or they're incomplete, create fallback options
    if not result["options"] or len(result["options"]) < 4:
        print("Warning: Missing options in quiz question. Using fallback options.")
        for letter in "ABCD":
            if letter not in result["options"]:
                result["options"][letter] = f"Option {letter}"

    # If we don't have a correct answer, default to A
    if not result["correct"]:
        print("Warning: Missing correct answer in quiz question. Defaulting to A.")
        result["correct"] = "A"

    return result


async def play_quiz(update: Update, context: CallbackContext):
    user_id = str(update.effective_user.id)

    # Check if user has linked wallet
    if not await check_wallet_linked(user_id):
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            "You need to link your wallet first! Use /linkwallet in a private chat with me.",
        )
        return

    # Require quiz ID as argument
    if not context.args:
        # If no specific quiz ID, find the latest active quiz
        session = SessionLocal()
        latest_quiz = (
            session.query(Quiz)
            .filter(Quiz.status == QuizStatus.ACTIVE)
            .order_by(Quiz.last_updated.desc())
            .first()
        )

        if not latest_quiz:
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                "No active quizzes found! Try again later.",
            )
            session.close()
            return

        quiz_id = latest_quiz.id
        session.close()
    else:
        quiz_id = context.args[0]

    # Fetch quiz
    session = SessionLocal()
    quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
    session.close()

    if not quiz:
        await safe_send_message(
            context.bot, update.effective_chat.id, f"No quiz found with ID {quiz_id}"
        )
        return

    # Tell user we'll DM them
    if update.effective_chat.type != "private":
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            f"@{update.effective_user.username}, I'll send you the quiz questions in a private message!",
        )

    # Start with the first question
    await send_quiz_question(context.bot, update.effective_user.id, quiz, 0)


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
            is_correct=is_correct,
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
    # Skip if this isn't a private chat
    if update.effective_chat.type != "private":
        return

    # Skip if we're not awaiting a reward structure
    if context.user_data.get("awaiting") in ("wallet_address", "signature"):
        # This is for wallet linking flow, not reward structure
        from services.user_service import handle_wallet_address, handle_signature

        if context.user_data.get("awaiting") == "wallet_address":
            await handle_wallet_address(update, context)
        elif context.user_data.get("awaiting") == "signature":
            await handle_signature(update, context)
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
    deposit_addr = f"quiz-{uuid.uuid4()}.near"

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

    # Inform creator privately
    await safe_send_message(
        context.bot,
        update.effective_chat.id,
        f"Please deposit a total of {total} Near to this address to activate the quiz:\n{deposit_addr}",
    )

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
                        f"Creator must deposit {total} Near to activate it.\n"
                        f"Once active, type /playquiz to join!"
                    ),
                )
    except asyncio.TimeoutError:
        logger.error(f"Failed to announce to group: Timeout error")
    except Exception as e:
        logger.error(f"Failed to announce to group: {e}", exc_info=True)
        import traceback

        traceback.print_exc()


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
