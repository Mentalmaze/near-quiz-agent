import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Define environment modes
ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()


class Config:
    # Telegram Bot Configuration
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

    # Gemini API for quiz generation
    GOOGLE_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY")

    # NEAR Blockchain Configuration
    NEAR_RPC_ENDPOINT = os.getenv(
        "NEAR_RPC_ENDPOINT", "https://rpc.testnet.fastnear.com"
    )
    NEAR_WALLET_PRIVATE_KEY = os.getenv("NEAR_WALLET_PRIVATE_KEY")
    NEAR_WALLET_ADDRESS = os.getenv("NEAR_WALLET_ADDRESS")
    NEAR_RPC_ENDPOINT_TRANS = os.getenv(
        "NEAR_RPC_ENDPOINT", "https://allthatnode.com/protocol/near.dsrv"
    )
    # Database Configuration
    # In production, use PostgreSQL; in development, fallback to SQLite
    DATABASE_URL = os.getenv(
        "DATABASE_URL",
        (
            "sqlite:///./mental_maze.db"
            if ENVIRONMENT == "development"
            else "postgresql://mental_maze_user:change_this_password@localhost:5432/mental_maze"
        ),
    )

    # Quiz Configuration
    DEFAULT_QUIZ_QUESTIONS = 1
    MAX_QUIZ_QUESTIONS = 5

    # Production check helper
    @classmethod
    def is_production(cls):
        return ENVIRONMENT == "production"

    @classmethod
    def is_development(cls):
        return ENVIRONMENT == "development"
