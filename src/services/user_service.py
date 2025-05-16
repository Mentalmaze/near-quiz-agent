import uuid
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from models.user import User
from store.database import SessionLocal
from utils.telegram_helpers import safe_send_message

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
    context.user_data["awaiting"] = "wallet_address"


async def handle_wallet_address(update: Update, context: CallbackContext):
    """Process wallet address from user in private chat."""
    wallet_address = update.message.text.strip()
    user_id = str(update.effective_user.id)

    try:
        # Basic validation
        if not wallet_address.endswith(".near") and not wallet_address.endswith(
            ".testnet"
        ):
            await safe_send_message(
                context.bot,
                update.effective_chat.id,
                "That doesn't look like a valid NEAR address. "
                "Please make sure it ends with '.near' or '.testnet'",
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
        if "awaiting" in context.user_data:
            del context.user_data["awaiting"]

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


async def handle_signature(update: Update, context: CallbackContext):
    """
    Legacy method maintained for backward compatibility.
    Signature verification is now skipped.
    """
    pass


async def check_wallet_linked(user_id: str) -> bool:
    """Check if a user has linked their NEAR wallet."""
    try:
        session = SessionLocal()
        try:
            user = session.query(User).filter(User.id == user_id).first()
            return user is not None and user.wallet_address is not None
        finally:
            session.close()
    except Exception as e:
        logger.error(f"Error checking wallet linkage: {e}", exc_info=True)
        return False  # Safer to return False in case of error


async def get_user_wallet(user_id: str) -> str | None:
    """Retrieve the wallet address for a given user_id."""
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.id == str(user_id)).first()
        if user and user.wallet_address:
            return user.wallet_address
        return None
    except Exception as e:
        logger.error(f"Error getting user wallet for {user_id}: {e}", exc_info=True)
        return None
    finally:
        session.close()


async def set_user_wallet(user_id: str, wallet_address: str) -> bool:
    """Set or update the wallet address for a given user_id."""
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.id == str(user_id)).first()
        if not user:
            user = User(id=str(user_id), wallet_address=wallet_address)
            session.add(user)
        else:
            user.wallet_address = wallet_address
        session.commit()
        return True
    except Exception as e:
        logger.error(f"Error setting user wallet for {user_id}: {e}", exc_info=True)
        session.rollback()
        return False
    finally:
        session.close()


async def remove_user_wallet(user_id: str) -> bool:
    """Remove the wallet address for a given user_id."""
    session = SessionLocal()
    try:
        user = session.query(User).filter(User.id == str(user_id)).first()
        if user and user.wallet_address:
            user.wallet_address = None
            session.commit()
            return True
        elif not user or not user.wallet_address:
            # If user doesn't exist or no wallet is linked, consider it a success (idempotency)
            return True
        return False  # Should not be reached if logic is correct
    except Exception as e:
        logger.error(f"Error removing user wallet for {user_id}: {e}", exc_info=True)
        session.rollback()
        return False
    finally:
        session.close()
