import logging
from pyrogram import Client
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.fsc_db import get_fsc_channels

logger = logging.getLogger(__name__)


async def check_force_sub(client: Client, message: Message) -> bool:
    """
    Returns True if user passes all force-sub checks.
    Returns False and sends a join prompt if user fails.
    """
    channels = await get_fsc_channels()
    if not channels:
        return True

    failed_channels = []
    for ch in channels:
        chat_id = ch["_id"]
        mode = ch.get("mode", "joined")
        try:
            member = await client.get_chat_member(chat_id, message.from_user.id)
            status = member.status.value if hasattr(member.status, "value") else str(member.status)
            if mode == "joined":
                if status not in ("member", "administrator", "creator", "owner"):
                    failed_channels.append((chat_id, mode))
            elif mode == "requested":
                if status not in ("member", "administrator", "creator", "owner", "restricted"):
                    failed_channels.append((chat_id, mode))
        except Exception:
            failed_channels.append((chat_id, mode))

    if not failed_channels:
        return True

    buttons = []
    for chat_id, mode in failed_channels:
        try:
            chat = await client.get_chat(chat_id)
            invite = chat.invite_link or (f"https://t.me/{chat.username}" if chat.username else "#")
            label = "📢 Join Channel" if mode == "joined" else "📩 Request to Join"
            buttons.append([InlineKeyboardButton(label, url=invite)])
        except Exception:
            pass

    buttons.append([InlineKeyboardButton("✅ I've Joined!", callback_data="fsub_check")])

    await message.reply_text(
        "🔒 **Access Restricted**\n\n"
        "You must join our channel(s) to use this bot.\n"
        "Click the button(s) below, then tap **I've Joined!**",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return False
