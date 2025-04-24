from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext, ContextTypes
from models.quiz import Quiz, QuizStatus
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

    for line in lines:
        if line.startswith("Question:"):
            result["question"] = line[len("Question:") :].strip()
        elif line.startswith("A)"):
            result["options"]["A"] = line[len("A)") :].strip()
        elif line.startswith("B)"):
            result["options"]["B"] = line[len("B)") :].strip()
        elif line.startswith("C)"):
            result["options"]["C"] = line[len("C)") :].strip()
        elif line.startswith("D)"):
            result["options"]["D"] = line[len("D)") :].strip()
        elif line.startswith("Correct Answer:"):
            result["correct"] = line[len("Correct Answer:") :].strip()

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
    quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()

    if not quiz:
        await query.edit_message_text("Quiz not found.")
        session.close()
        return

    # Get correct answer
    correct_answer = quiz.questions.get("correct", "")
    is_correct = correct_answer == answer

    # Update message to show result
    await query.edit_message_text(
        f"{query.message.text}\n\n"
        f"Your answer: {answer}\n"
        f"{'✅ Correct!' if is_correct else f'❌ Wrong. The correct answer is {correct_answer}.'}",
        reply_markup=None,
    )

    # Record the answer (in a real app, store this in the database)
    # Here we'd track scores and timing for later reward distribution
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

    # Update quiz in DB: find latest ACTIVE quiz by this user with no reward_schedule
    session = SessionLocal()
    quiz = (
        session.query(Quiz)
        .filter(Quiz.status == QuizStatus.ACTIVE)
        .order_by(Quiz.last_updated.desc())
        .first()
    )

    if not quiz:
        await update.message.reply_text("No active quiz found to attach rewards to.")
        session.close()
        return

    quiz.reward_schedule = schedule
    quiz.deposit_address = deposit_addr
    quiz.status = QuizStatus.FUNDING
    session.commit()
    session.close()

    # Inform creator privately
    await update.message.reply_text(
        f"Please deposit a total of {total} Near to this address to activate the quiz:\n{deposit_addr}"
    )

    # Announce in group chat
    try:
        if quiz.group_chat_id:
            await context.bot.send_message(
                chat_id=quiz.group_chat_id,
                text=(
                    f"Quiz '{quiz.topic}' is now funding.\n"
                    f"Creator must deposit {total} Near to activate it.\n"
                    f"Once active, type /playquiz to join!"
                ),
            )
    except Exception as e:
        print(f"Failed to announce to group: {e}")
