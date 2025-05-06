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


# async def generate_quiz(topic, num_questions=1, context_text=None):
#     """
#     Generate a multiple choice quiz about a topic.

#     Args:
#         topic: The topic to generate questions about
#         num_questions: Number of questions to generate (default: 1)
#         context_text: Optional text to use as context for generating questions

#     Returns:
#         String containing formatted quiz questions
#     """
#     # Initialize the chat model
#     llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=GOOGLE_API_KEY)

#     # Check if this is a blockchain-related topic
#     blockchain_keywords = [
#         "blockchain",
#         "crypto",
#         "bitcoin",
#         "ethereum",
#         "solana",
#         "near",
#         "web3",
#         "defi",
#         "nft",
#         "token",
#     ]
#     is_blockchain_topic = any(
#         keyword in topic.lower() for keyword in blockchain_keywords
#     )

#     # Preprocess context text if provided
#     if context_text:
#         context_text = preprocess_text(context_text)

#     # Create a prompt template based on whether context text is provided
#     if context_text:
#         template = """Generate {num_questions} multiple choice quiz question(s) based on the following text about {topic}:

#         TEXT:
#         {context_text}

#         Please format each question as follows:
#         Question: [question]
#         A) [option]
#         B) [option]
#         C) [option]
#         D) [option]
#         Correct Answer: [letter]

#         Make sure to extract relevant information from the text to create challenging questions.
#         Number each question if generating multiple questions.
#         """
#     elif is_blockchain_topic:
#         # Special template for blockchain topics with fact-checking instructions
#         template = """Generate {num_questions} factually accurate multiple choice quiz question(s) about {topic}.

#         IMPORTANT GUIDELINES FOR BLOCKCHAIN TOPICS:
#         - Verify that all information is technically accurate and up-to-date
#         - For blockchain-specific questions, be precise about:
#           * Native tokens (e.g., Bitcoin for Bitcoin blockchain, ETH for Ethereum, SOL for Solana)
#           * Consensus mechanisms (e.g., Proof of Work, Proof of Stake, Proof of History)
#           * Technical capabilities and limitations
#         - Ensure the correct answer is actually correct and the other options are clearly incorrect
#         - When unsure about a specific technical detail, use more general questions about the topic

#         Please format each question as follows:
#         Question: [question]
#         A) [option]
#         B) [option]
#         C) [option]
#         D) [option]
#         Correct Answer: [letter]

#         Number each question if generating multiple questions.
#         """
#     else:
#         # Standard template for non-blockchain topics
#         template = """Generate {num_questions} multiple choice quiz question(s) about {topic}.

#         Please format each question as follows:
#         Question: [question]
#         A) [option]
#         B) [option]
#         C) [option]
#         D) [option]
#         Correct Answer: [letter]

#         Number each question if generating multiple questions.
#         """

#     prompt = ChatPromptTemplate.from_template(template)

#     # Generate the quiz with timeout and retry logic
#     messages = prompt.format_messages(
#         topic=topic,
#         num_questions=num_questions,
#         context_text=context_text if context_text else "",
#     )

#     max_attempts = 3
#     attempt = 0
#     last_exception = None

#     while attempt < max_attempts:
#         try:
#             # Increase timeout for multiple questions or long text
#             timeout = 15.0 * (
#                 1
#                 + (0.5 * min(int(num_questions), 10))
#                 + (0.01 * min(len(context_text or ""), 1000))
#             )

#             response = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout)

#             # For blockchain topics, do an additional verification step
#             if is_blockchain_topic:
#                 # Check generated content for common blockchain errors
#                 quiz_content = response.content.lower()
#                 has_errors = False

#                 # Check for common blockchain factual errors
#                 if (
#                     "solana" in topic.lower()
#                     and "ethereum" in quiz_content
#                     and "native token" in quiz_content
#                 ):
#                     has_errors = True
#                 elif (
#                     "near" in topic.lower()
#                     and "ethereum" in quiz_content
#                     and "native token" in quiz_content
#                 ):
#                     has_errors = True

#                 # If errors found, retry with more explicit correction instructions
#                 if has_errors and attempt < max_attempts - 1:
#                     attempt += 1
#                     correction_template = """CORRECTION NEEDED: The previous quiz questions contained factual errors about blockchain technologies.

#                     Please generate {num_questions} FACTUALLY ACCURATE multiple choice quiz question(s) about {topic}.

#                     CRITICAL FACT VERIFICATION:
#                     - Solana's native token is SOL (not Ethereum or ETH)
#                     - NEAR Protocol's native token is NEAR (not Ethereum or ETH)
#                     - Ethereum's native token is ETH
#                     - Bitcoin's native token is BTC
#                     - Each blockchain has its own unique consensus mechanism and features

#                     Please format each question correctly:
#                     Question: [clear, factually accurate question]
#                     A) [option]
#                     B) [option]
#                     C) [option]
#                     D) [option]
#                     Correct Answer: [letter]

#                     Number each question if generating multiple questions.
#                     """
#                     correction_prompt = ChatPromptTemplate.from_template(
#                         correction_template
#                     )
#                     correction_messages = correction_prompt.format_messages(
#                         topic=topic, num_questions=num_questions
#                     )
#                     response = await asyncio.wait_for(
#                         llm.ainvoke(correction_messages), timeout=timeout
#                     )

#             return response.content

#         except asyncio.TimeoutError:
#             attempt += 1
#             last_exception = "Timeout error"
#             print(f"Quiz generation timed out (attempt {attempt}/{max_attempts})")
#             # Wait before retry
#             await asyncio.sleep(1)
#         except Exception as e:
#             attempt += 1
#             last_exception = str(e)
#             print(f"Error generating quiz (attempt {attempt}/{max_attempts}): {e}")
#             await asyncio.sleep(1)

#     # If we've exhausted all attempts, return a fallback question
#     print(
#         f"Failed to generate quiz after {max_attempts} attempts. Last error: {last_exception}"
#     )
#     return generate_fallback_quiz(topic, num_questions)


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
"""

    TEMPLATE = """
{few_shot}

Now, generate {num_questions} new multiple-choice question(s) on **{topic}**.

Context: {context}

Requirements:
- Exactly four options per question, labeled A)–D).
- Only one correct answer; state “Correct Answer: [letter]” after each.
- Vary question types (definition, application, true/false style).
- Do not reuse wording from examples or between questions.
- If this is a blockchain topic (keywords: blockchain, crypto, bitcoin, ethereum, solana, near, web3, defi, nft, token), ensure accuracy:
  * Bitcoin → Proof of Work, BTC
  * Ethereum → Proof of Stake, ETH
  * Solana → Proof of History, SOL
  * NEAR → Nightshade, NEAR
- If unsure of a fact, generalize rather than fabricate.
- Number each question: 1., 2., …

Format exactly like the examples.
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
