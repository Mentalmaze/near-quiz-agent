import uuid
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from models.user import User
from store.database import SessionLocal
from utils.telegram_helpers import safe_send_message
from utils.redis_client import RedisClient
from typing import Optional

logger = logging.getLogger(__name__)


async def link_wallet(update: Update, context: CallbackContext):
    """Handler for /linkwallet command - instructs user to link wallet via private message."""
    # If this is a group chat, direct user to DM
    if update.effective_chat.type != "private":
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            f"@{update.effective_user.username}, please start a private chat with me to link your NEAR wallet securely.",
        )
        return

    # This is already a private chat, prompt for wallet address
    await safe_send_message(
        context.bot,
        update.effective_chat.id,
        "Please send me your NEAR wallet address (e.g., 'yourname.near').",
    )
    # Set user state to wait for wallet address
    redis_client = RedisClient()
    await redis_client.set_user_data_key(str(update.effective_user.id), "awaiting", "wallet_address")
    await redis_client.close()


async def handle_wallet_address(update: Update, context: CallbackContext):
    """Process wallet address from user in private chat."""
    wallet_address = update.message.text.strip()
    user_id = str(update.effective_user.id)
    redis_client = RedisClient()

    try:
        # Only allow mainnet .near addresses
        if not wallet_address.endswith(".near") or wallet_address.endswith(".testnet"):
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                "❌ Only mainnet NEAR wallets are allowed. Please provide a wallet address ending with '.near' (not '.testnet').",
            )
            return

        # Skip the challenge/signature part and directly save the wallet address
        session = SessionLocal()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            if not user:
                user = User(id=user_id, wallet_address=wallet_address)
                session.add(user)
            else:
                user.wallet_address = wallet_address
            session.commit()
        finally:
            session.close()

        # Clear awaiting state
        await redis_client.delete_user_data_key(user_id, "awaiting")
        # Invalidate user cache
        await redis_client.delete_cached_object(f"user_profile:{user_id}")

        # Confirm wallet link to the user
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            f"Wallet {wallet_address} linked successfully! You're ready to play quizzes.",
        )

    except Exception as e:
        logger.error(f"Error handling wallet address: {e}", exc_info=True)
        await safe_send_message(
            context.bot,
            update.effective_chat.id,
            f"An error occurred while processing your wallet address. Please try again later.",
        )
    finally:
        await redis_client.close()


async def handle_signature(update: Update, context: CallbackContext):
    """
    Legacy method maintained for backward compatibility.
    Signature verification is now skipped.
    """
    pass


async def check_wallet_linked(user_id: str) -> bool:
    """Check if a user has linked their NEAR wallet."""
    user_profile = await get_user_profile(user_id)
    return user_profile is not None and user_profile.get("wallet_address") is not None


async def get_user_wallet(user_id: str) -> str | None:
    """Retrieve the wallet address for a given user_id."""
    user_profile = await get_user_profile(user_id)
    return user_profile.get("wallet_address") if user_profile else None


async def get_user_profile(user_id: str) -> Optional[dict]:
    """Retrieve user profile, from cache if available, otherwise from DB."""
    redis_client = RedisClient()
    cache_key = f"user_profile:{user_id}"
    
    cached_user = await redis_client.get_cached_object(cache_key)
    if cached_user:
        logger.info(f"User profile for {user_id} found in cache.")
        await redis_client.close()
        return cached_user

    logger.info(f"User profile for {user_id} not in cache. Fetching from DB.")
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.id == str(user_id)).first()
        if user:
            user_data = {
                "id": user.id,
                "wallet_address": user.wallet_address,
                "linked_at": user.linked_at.isoformat() if user.linked_at else None,
            }
            await redis_client.set_cached_object(cache_key, user_data)
            await redis_client.close()
            return user_data
        await redis_client.close()
        return None
    except Exception as e:
        logger.error(f"Error getting user profile for {user_id}: {e}", exc_info=True)
        await redis_client.close()
        return None
    finally:
        session.close()


async def set_user_wallet(user_id: str, wallet_address: str) -> bool:
    """Set or update the wallet address for a given user_id."""
    session = SessionLocal()
    redis_client = RedisClient()
    try:
        user = session.query(User).filter(User.id == str(user_id)).first()
        if not user:
            user = User(id=str(user_id), wallet_address=wallet_address)
            session.add(user)
        else:
            user.wallet_address = wallet_address
        session.commit()
        # Invalidate cache
        await redis_client.delete_cached_object(f"user_profile:{user_id}")
        await redis_client.close()
        return True
    except Exception as e:
        logger.error(f"Error setting user wallet for {user_id}: {e}", exc_info=True)
        session.rollback()
        await redis_client.close()
        return False
    finally:
        session.close()


async def remove_user_wallet(user_id: str) -> bool:
    """Remove the wallet address for a given user_id."""
    session = SessionLocal()
    redis_client = RedisClient()
    try:
        user = session.query(User).filter(User.id == str(user_id)).first()
        if user and user.wallet_address:
            user.wallet_address = None
            session.commit()
            # Invalidate cache
            await redis_client.delete_cached_object(f"user_profile:{user_id}")
            await redis_client.close()
            return True
        elif not user or not user.wallet_address:
            # If user doesn't exist or no wallet is linked, consider it a success (idempotency)
            await redis_client.close()
            return True
        await redis_client.close() # Should not be reached if logic is correct
        return False
    except Exception as e:
        logger.error(f"Error removing user wallet for {user_id}: {e}", exc_info=True)
        session.rollback()
        await redis_client.close()
        return False
    finally:
        session.close()

async def close_redis_client_after_request(redis_client: RedisClient):
    if redis_client:
        await redis_client.close()
