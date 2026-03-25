import asyncio
import logging
import config
from pyrogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from database.admin_db import get_extra_admins

logger = logging.getLogger(__name__)


def format_size(size_bytes: int) -> str:
    if size_bytes <= 0:
        return "Unknown"
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.2f} TB"


def format_duration(seconds: int) -> str:
    if seconds <= 0:
        return "Unlimited"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "< 1m"


def format_timestamp(ts: float | None) -> str:
    if not ts:
        return "Never"
    import datetime
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%d %b %Y, %I:%M %p")


def build_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔽 Download video")],
            [KeyboardButton("💎 Premium Plans"), KeyboardButton("📞 Contact us")],
        ],
        resize_keyboard=True,
    )


def build_inline_keyboard(buttons: list[list[tuple]]) -> InlineKeyboardMarkup:
    rows = []
    for row in buttons:
        row_btns = []
        for text, data in row:
            if isinstance(data, str) and data.startswith("http"):
                row_btns.append(InlineKeyboardButton(text, url=data))
            else:
                row_btns.append(InlineKeyboardButton(text, callback_data=str(data)))
        rows.append(row_btns)
    return InlineKeyboardMarkup(rows)


async def is_admin(user_id: int) -> bool:
    if user_id in config.ADMIN_IDS:
        return True
    extra = await get_extra_admins()
    return user_id in extra


async def auto_delete(message, delay: int) -> None:
    if delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        pass
