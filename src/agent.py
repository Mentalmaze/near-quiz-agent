import os
import asyncio
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from dotenv import find_dotenv, load_dotenv
import getpass
import time
import re

# Load environment variables from .env file
load_dotenv(find_dotenv())

# Get API key from environment variable or prompt user
GOOGLE_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY")
if not GOOGLE_API_KEY:
    GOOGLE_API_KEY = getpass.getpass("Enter your Google API key: ")


async def generate_quiz(
    topic: str, num_questions: int = 1, context_text: str = None
) -> str:
    """
    Generate a multiple-choice quiz about a topic.
    """
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=GOOGLE_API_KEY)

    # Preprocess context
    if context_text:
        context_text = preprocess_text(context_text)

    # Unified, meta-prompt with few-shot and robust instructions
    BASIC_SYSTEM = """
You are QuizMasterGPT, an expert educator and fact-checker.\nAlways produce unique, non-repetitive, evidence-based multiple-choice questions.\n"""

    FEW_SHOT = """
Example 1:
Question: What is the primary consensus mechanism used by the Bitcoin network?
A) Proof of Stake
B) Proof of Work
C) Delegated Proof of Stake
D) Proof of Authority
Correct Answer: B

Example 2:
Question: In object-oriented programming, which keyword in JavaScript defines a class?
A) class
B) constructor
C) func
D) type
Correct Answer: A

Example 3:
Question: What is the native token of the Solana blockchain?
A) SOL
B) SLP
C) SOLA
D) SNL
Correct Answer: A
"""

    TEMPLATE = """
{few_shot}

Now, generate {num_questions} multiple-choice question(s) exclusively about **{topic}**.

Context: {context}

Strict requirements:
 1. Focus solely on the user-provided topic; do NOT include content outside the scope of {topic}.
 2. EXACTLY four options per question, labeled A)–D). Only one correct answer; state “Correct Answer: [letter]” after each.
 3. No repetition: each question must cover a distinct subtopic (e.g., tokenomics, consensus mechanism, network performance, smart contracts, ecosystem governance).
 4. Avoid any hallucinations: only use verifiable facts. If uncertain, choose a general concept rather than invent details.
 5. Vary question types: definition, application, true/false style, edge-case analysis.
 6. Use concise, precise language suitable for advanced learners.
 7. If the topic is blockchain-related, ensure all blockchain-specific facts are accurate.
 8. Do NOT include any additional commentary or instructions; output only the formatted questions.
 9. Number each question: 1., 2., …

Format exactly like the examples above.
"""

    prompt = ChatPromptTemplate.from_template(
        BASIC_SYSTEM + "\n" + FEW_SHOT + "\n" + TEMPLATE
    )

    messages = prompt.format_messages(
        few_shot=FEW_SHOT,
        topic=topic,
        num_questions=num_questions,
        context=context_text or "No additional context provided.",
    )

    # Remaining generation & retry logic unchanged...
    max_attempts = 3
    attempt = 0
    last_exception = None

    while attempt < max_attempts:
        try:
            timeout = 15.0 * (
                1
                + 0.5 * min(num_questions, 10)
                + 0.01 * min(len(context_text or ""), 1000)
            )
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)
            return response.content

        except Exception:
            attempt += 1
            await asyncio.sleep(1)

    return generate_fallback_quiz(topic, num_questions)


def generate_fallback_quiz(topic, num_questions=1):
    """Generate a simple fallback quiz when the API fails"""
    questions = []
    for i in range(1, int(num_questions) + 1):
        questions.append(
            f"""Question {i}: Which of the following is most associated with {topic}?
A) First option
B) Second option
C) Third option
D) Fourth option
Correct Answer: A"""
        )

    return "\n\n".join(questions)


async def generate_tweet(topic):
    """
    Generate a concise, engaging tweet about the given topic (max 280 characters).
    """
    # Initialize the chat model
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=GOOGLE_API_KEY)

    # Prompt template for a tweet
    tweet_template = (
        "Write a concise, engaging tweet about {topic}. "
        "Keep it under 280 characters and include a friendly tone."
    )
    prompt = ChatPromptTemplate.from_template(tweet_template)

    # Generate the tweet with timeout
    messages = prompt.format_messages(topic=topic)

    try:
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=5.0)
        return response.content
    except asyncio.TimeoutError:
        return "Sorry, tweet generation took too long. Please try a simpler topic."
    except Exception as e:
        return f"An error occurred: {str(e)}"


def preprocess_text(text):
    """Clean and prepare text for quiz generation by removing links, markdown, and other noise."""
    # Remove links in markdown format [text](url)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)

    # Remove standalone URLs
    text = re.sub(r"https?://\S+", "", text)

    # Remove multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Remove markdown headers
    text = re.sub(r"#{1,6}\s+", "", text)

    # Replace bullet points with clean format
    text = re.sub(r"^\s*[\*\-•]\s*", "- ", text, flags=re.MULTILINE)

    # Clean up any trailing/leading whitespace
    text = text.strip()

    return text


# Example usage
if __name__ == "__main__":
    topic = input("Enter a topic for the quiz: ")
    quiz = asyncio.run(generate_quiz(topic))
    print("\nGenerated Quiz:")
    print(quiz)
