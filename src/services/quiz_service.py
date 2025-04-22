from telegram import Update
from telegram.ext import CallbackContext
from models.quiz import Quiz, QuizStatus
from store.database import SessionLocal
from agent import generate_quiz


async def create_quiz(update: Update, context: CallbackContext):
    # Require a topic as argument
    if not context.args:
        await update.message.reply_text("Usage: /createquiz <topic>")
        return
    topic = " ".join(context.args)
    # Inform user
    await update.message.reply_text(f"Generating quiz for topic: {topic}")
    # Generate questions via LLM
    questions_raw = await generate_quiz(topic)
    # Persist quiz
    session = SessionLocal()
    quiz = Quiz(topic=topic, questions=questions_raw, status=QuizStatus.ACTIVE)
    session.add(quiz)
    session.commit()
    quiz_id = quiz.id
    session.close()
    # Reply with quiz ID and questions
    await update.message.reply_text(f"Quiz created with ID: {quiz_id}\n{questions_raw}")


async def play_quiz(update: Update, context: CallbackContext):
    # Require quiz ID as argument
    if not context.args:
        await update.message.reply_text("Usage: /playquiz <quiz_id>")
        return
    quiz_id = context.args[0]
    # Fetch quiz
    session = SessionLocal()
    quiz = session.query(Quiz).filter(Quiz.id == quiz_id).first()
    session.close()
    if not quiz:
        await update.message.reply_text(f"No quiz found with ID {quiz_id}")
        return
    # Send quiz questions
    await update.message.reply_text(f"Quiz {quiz.id}:\n{quiz.questions}")
