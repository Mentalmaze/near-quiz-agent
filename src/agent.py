import os
import asyncio
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from dotenv import find_dotenv, load_dotenv
import getpass
import time

# Load environment variables from .env file
load_dotenv(find_dotenv())

# Get API key from environment variable or prompt user
GOOGLE_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY")
if not GOOGLE_API_KEY:
    GOOGLE_API_KEY = getpass.getpass("Enter your Google API key: ")


async def generate_quiz(topic):
    # Initialize the chat model
    llm = ChatGoogleGenerativeAI(model="gemini-2.0-flash", api_key=GOOGLE_API_KEY)

    # Create a prompt template for quiz generation
    template = """Generate a multiple choice quiz question about {topic}.
    Please format it as follows:
    Question: [question]
    A) [option]
    B) [option]
    C) [option]
    D) [option]
    Correct Answer: [letter]"""

    prompt = ChatPromptTemplate.from_template(template)

    # Generate the quiz with timeout and retry logic
    messages = prompt.format_messages(topic=topic)

    max_attempts = 3
    attempt = 0
    last_exception = None

    while attempt < max_attempts:
        try:
            # Increase timeout to handle slow connections
            response = await asyncio.wait_for(llm.ainvoke(messages), timeout=15.0)
            return response.content
        except asyncio.TimeoutError:
            attempt += 1
            last_exception = "Timeout error"
            print(f"Quiz generation timed out (attempt {attempt}/{max_attempts})")
            # Wait before retry
            await asyncio.sleep(1)
        except Exception as e:
            attempt += 1
            last_exception = str(e)
            print(f"Error generating quiz (attempt {attempt}/{max_attempts}): {e}")
            await asyncio.sleep(1)

    # If we've exhausted all attempts, return a fallback question
    print(
        f"Failed to generate quiz after {max_attempts} attempts. Last error: {last_exception}"
    )
    return generate_fallback_quiz(topic)


def generate_fallback_quiz(topic):
    """Generate a simple fallback quiz when the API fails"""
    return f"""Question: Which of the following is most associated with {topic}?
A) First option
B) Second option
C) Third option
D) Fourth option
Correct Answer: A"""


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


# Example usage
if __name__ == "__main__":
    topic = input("Enter a topic for the quiz: ")
    quiz = asyncio.run(generate_quiz(topic))
    print("\nGenerated Quiz:")
    print(quiz)
