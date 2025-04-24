from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ContextTypes
from models.quiz import Quiz, QuizStatus, QuizAnswer
from store.database import SessionLocal
from agent import generate_quiz
from services.user_service import check_wallet_linked
import re
import uuid
import json
import asyncio


async def create_quiz(update: Update, context: CallbackContext):
    # Require a topic as argument
    if not context.args:
        await update.message.reply_text("Usage: /createquiz <topic>")
        return
    topic = " ".join(context.args)

    try:
        # Inform user
        await update.message.reply_text(f"Generating quiz for topic: {topic}")
        # Store group chat for later announcements
        group_chat_id = update.effective_chat.id

        # Generate questions via LLM
        questions_raw = await generate_quiz(topic)

        # Parse questions into structured format
        questions = parse_questions(questions_raw)

        # Persist quiz
        session = SessionLocal()
        quiz = Quiz(
            topic=topic,
            questions=questions,
            status=QuizStatus.ACTIVE,
            group_chat_id=group_chat_id,
        )
        session.add(quiz)
        session.commit()
        quiz_id = quiz.id
        session.close()

        # Notify group and DM creator for contract setup
        await update.message.reply_text(
            f"Quiz created with ID: {quiz_id}! Check your DMs to set up the reward contract."
        )

        # DM the creator for reward structure details
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="Please specify the reward structure in this private chat (e.g., '2 Near for 1st, 1 Near for 2nd').",
        )
    except asyncio.TimeoutError:
        await update.message.reply_text(
            "Sorry, quiz generation timed out. Please try again with a simpler topic."
        )
    except Exception as e:
        await update.message.reply_text(f"Error creating quiz: {str(e)}")


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
        await update.message.reply_text(
            "You need to link your wallet first! Use /linkwallet in a private chat with me."
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
            await update.message.reply_text("No active quizzes found! Try again later.")
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
        await update.message.reply_text(f"No quiz found with ID {quiz_id}")
        return

    # Tell user we'll DM them
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            f"@{update.effective_user.username}, I'll send you the quiz questions in a private message!"
        )

    # Create inline keyboard for answering
    question = quiz.questions.get("question", "Question not available")
    options = quiz.questions.get("options", {})

    keyboard = []
    for key, value in options.items():
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"{key}) {value}", callback_data=f"quiz:{quiz_id}:{key}"
                )
            ]
        )

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Send question with inline keyboard
    await context.bot.send_message(
        chat_id=update.effective_user.id,
        text=f"Quiz: {quiz.topic}\n\n{question}",
        reply_markup=reply_markup,
    )


async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Process quiz answers from inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()  # Acknowledge the button press

    # Parse callback data to get quiz ID and answer
    try:
        _, quiz_id, answer = query.data.split(":")
    except ValueError:
        await query.edit_message_text("Invalid answer format.")
        return

    # Get quiz from database
    session = SessionLocal()
    try:
        quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()

        if not quiz:
            await query.edit_message_text("Quiz not found.")
            return

        # Get correct answer
        correct_answer = quiz.questions.get("correct", "")
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
        await query.edit_message_text(
            f"{query.message.text}\n\n"
            f"Your answer: {answer}\n"
            f"{'✅ Correct!' if is_correct else f'❌ Wrong. The correct answer is {correct_answer}.'}",
            reply_markup=None,
        )
    except Exception as e:
        print(f"Error handling quiz answer: {e}")
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
        await update.message.reply_text(
            "Couldn't parse reward amounts. Please specify like '2 Near for 1st, 1 Near for 2nd'."
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
            await update.message.reply_text(
                "No active quiz found to attach rewards to."
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
        await update.message.reply_text(f"Error saving reward structure: {str(e)}")
        import traceback

        traceback.print_exc()
        return
    finally:
        session.close()

    # Inform creator privately
    await update.message.reply_text(
        f"Please deposit a total of {total} Near to this address to activate the quiz:\n{deposit_addr}"
    )

    # Announce in group chat
    try:
        if original_group_chat_id:
            # Use a longer timeout for the announcement
            async with asyncio.timeout(10):  # 10 second timeout
                await context.bot.send_message(
                    chat_id=original_group_chat_id,
                    text=(
                        f"Quiz '{quiz_topic}' is now funding.\n"
                        f"Creator must deposit {total} Near to activate it.\n"
                        f"Once active, type /playquiz to join!"
                    ),
                )
    except asyncio.TimeoutError:
        print(f"Failed to announce to group: Timeout error")
    except Exception as e:
        print(f"Failed to announce to group: {e}")
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
                await update.message.reply_text(f"No quiz found with ID {quiz_id}")
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
                await update.message.reply_text("No active or completed quizzes found.")
                return

        # Calculate winners for the quiz
        winners = QuizAnswer.compute_quiz_winners(session, quiz.id)

        if not winners:
            await update.message.reply_text(
                f"No participants have answered the '{quiz.topic}' quiz yet."
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

        await update.message.reply_text(message, parse_mode="Markdown")

    except Exception as e:
        await update.message.reply_text(f"Error retrieving winners: {str(e)}")
        import traceback

        traceback.print_exc()
    finally:
        session.close()
