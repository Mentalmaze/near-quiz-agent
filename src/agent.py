import os
import asyncio
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from dotenv import find_dotenv, load_dotenv
import getpass

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

    # Generate the quiz with timeout
    messages = prompt.format_messages(topic=topic)

    try:
        # Add a timeout to prevent hanging
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=8.0)
        return response.content
    except asyncio.TimeoutError:
        return "Sorry, quiz generation took too long. Please try a simpler topic."
    except Exception as e:
        return f"An error occurred: {str(e)}"


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
