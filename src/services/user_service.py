import uuid
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import CallbackContext
from models.user import User
from store.database import SessionLocal


async def link_wallet(update: Update, context: CallbackContext):
    """Handler for /linkwallet command - instructs user to link wallet via private message."""
    # If this is a group chat, direct user to DM
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            f"@{update.effective_user.username}, please start a private chat with me to link your NEAR wallet securely."
        )
        return

    # This is already a private chat, prompt for wallet address
    await update.message.reply_text(
        "Please send me your NEAR wallet address (e.g., 'yourname.near')."
    )
    # Set user state to wait for wallet address
    context.user_data["awaiting"] = "wallet_address"


async def handle_wallet_address(update: Update, context: CallbackContext):
    """Process wallet address from user in private chat."""
    wallet_address = update.message.text.strip()
    user_id = str(update.effective_user.id)

    # Basic validation
    if not wallet_address.endswith(".near"):
        await update.message.reply_text(
            "That doesn't look like a valid NEAR address. "
            "Please make sure it ends with '.near'"
        )
        return

    # Generate verification challenge
    challenge = str(uuid.uuid4())
    context.user_data["challenge"] = challenge
    context.user_data["wallet_address"] = wallet_address
    context.user_data["awaiting"] = "signature"

    # In a real implementation, we'd have the user sign this message
    # Here we'll simulate by just asking them to confirm
    await update.message.reply_text(
        f"Please sign this message with your wallet: '{challenge}'\n\n"
        f"For this demo version, just reply with 'SIGNED' to simulate verification."
    )


async def handle_signature(update: Update, context: CallbackContext):
    """Process the signed message (simulated in this demo)."""
    signature = update.message.text.strip()
    if signature.upper() != "SIGNED":  # Simple simulation
        await update.message.reply_text("Invalid signature. Please try again.")
        return

    # Get data from context
    user_id = str(update.effective_user.id)
    wallet_address = context.user_data.get("wallet_address")

    # Create or update user in database
    session = SessionLocal()
    user = session.query(User).filter(User.id == user_id).first()
    if not user:
        user = User(id=user_id, wallet_address=wallet_address)
        session.add(user)
    else:
        user.wallet_address = wallet_address
    session.commit()
    session.close()

    # Clear awaiting state
    if "awaiting" in context.user_data:
        del context.user_data["awaiting"]
    if "challenge" in context.user_data:
        del context.user_data["challenge"]
    if "wallet_address" in context.user_data:
        del context.user_data["wallet_address"]

    await update.message.reply_text(
        f"Wallet {wallet_address} linked successfully! You're ready to play quizzes."
    )


async def check_wallet_linked(user_id: str) -> bool:
    """Check if a user has linked their NEAR wallet."""
    session = SessionLocal()
    user = session.query(User).filter(User.id == user_id).first()
    session.close()
    return user is not None and user.wallet_address is not None
