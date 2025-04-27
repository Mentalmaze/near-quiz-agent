import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    GOOGLE_API_KEY = os.getenv("GOOGLE_GEMINI_API_KEY")
    NEAR_RPC_ENDPOINT = os.getenv("NEAR_RPC_ENDPOINT", "https://nrpc.herewallet.app")
    NEAR_WALLET_PRIVATE_KEY = os.getenv("NEAR_WALLET_PRIVATE_KEY")
    NEAR_WALLET_ADDRESS = os.getenv("NEAR_WALLET_ADDRESS")
    # Database connection URL (default to SQLite local file)
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mental_maze.db")
