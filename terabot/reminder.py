import asyncio
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from pyrogram import Client

import config
from database.admin_db import get_settings
from database.users_db import get_all_user_ids, get_user

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

# In-memory “already reminded” trackers so users do not get spammed every loop
_last_free_reset_reminder: dict[int, str] = {}
_last_premium_expiry_reminder: dict[int, str] = {}

_reminder_task: asyncio.Task | None = None


def _now_ist() -> datetime:
    return datetime.now(IST)


def _fmt_dt(ts: float | int | None) -> str:
    if not ts:
        return "Unknown"
    return datetime.fromtimestamp(float(ts), IST).strftime("%d %b %Y at %I:%M %p")


def _date_key(dt: datetime) -> str:
    return dt.astimezone(IST).date().isoformat()


def _time_left_str(expiry_ts: float | int | None) -> str:
    if not expiry_ts:
        return "Unknown"

    remaining = int(float(expiry_ts) - time.time())
    if remaining <= 0:
        return "Expired"

    days = remaining // 86400
    hours = (remaining % 86400) // 3600
    minutes = (remaining % 3600) // 60

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "< 1m"


async def _safe_send(app: Client, user_id: int, text: str) -> None:
    try:
        await app.send_message(user_id, text)
    except Exception as e:
        logger.debug(f"Could not send reminder to {user_id}: {e}")


async def _handle_free_users(app: Client, user_ids: list[int], limit_use: int) -> None:
    now = _now_ist()
    now_ts = time.time()

    for user_id in user_ids:
        user = await get_user(user_id)
        if not user:
            continue

        # Skip premium users
        if user.get("is_premium"):
            continue

        last_reset_ts = float(user.get("last_reset", 0) or 0)
        daily_count = int(user.get("daily_count", 0) or 0)

        if last_reset_ts <= 0:
            continue

        next_reset_ts = last_reset_ts + 86400
        if now_ts < next_reset_ts:
            continue

        # Use the date of the reset window so we only notify once per cycle
        reset_key = datetime.fromtimestamp(next_reset_ts, IST).date().isoformat()
        if _last_free_reset_reminder.get(user_id) == reset_key:
            continue

        # Only remind if the user actually used the bot
        if daily_count <= 0:
            _last_free_reset_reminder[user_id] = reset_key
            continue

        remaining = max(0, limit_use - daily_count)

        text = (
            "🔄 **Your free limit has refreshed!**\n\n"
            f"📥 Daily Limit: **{limit_use}**\n"
            f"📊 Used Yesterday: **{daily_count}**\n"
            f"🟢 Available Again: **Yes**\n\n"
            "You can start downloading again now."
        )

        await _safe_send(app, user_id, text)
        _last_free_reset_reminder[user_id] = reset_key


async def _handle_premium_users(app: Client, user_ids: list[int]) -> None:
    now = _now_ist()
    today_key = now.date().isoformat()
    now_ts = time.time()

    for user_id in user_ids:
        user = await get_user(user_id)
        if not user:
            continue

        if not user.get("is_premium"):
            continue

        expiry_ts = user.get("premium_expiry")
        if not expiry_ts:
            continue

        expiry_ts = float(expiry_ts)
        expiry_dt = datetime.fromtimestamp(expiry_ts, IST)
        expiry_date_key = expiry_dt.date().isoformat()

        # Send reminder when the plan ends today, or if it already expired
        expired_or_today = expiry_dt.date() == now.date() or expiry_ts <= now_ts
        if not expired_or_today:
            continue

        # Prevent repeat notifications for the same expiry date
        if _last_premium_expiry_reminder.get(user_id) == expiry_date_key:
            continue

        # If it expires today and still active, remind politely.
        # If already expired, use a stronger message.
        if expiry_ts > now_ts:
            text = (
                "⏳ **Your premium plan ends today**\n\n"
                f"📦 **Plan:** Regular Premium\n"
                f"🕒 **Time Left:** {_time_left_str(expiry_ts)}\n"
                f"📅 **Expires On:** {_fmt_dt(expiry_ts)}\n\n"
                "Renew it to keep unlimited downloads without interruption."
            )
        else:
            text = (
                "⚠️ **Your premium plan has ended**\n\n"
                f"📦 **Plan:** Regular Premium\n"
                f"📅 **Expired On:** {_fmt_dt(expiry_ts)}\n\n"
                "Renew it to continue unlimited downloads."
            )

        await _safe_send(app, user_id, text)
        _last_premium_expiry_reminder[user_id] = expiry_date_key


async def reminder_loop(app: Client, interval_seconds: int = 1800) -> None:
    """
    Background reminder loop.

    Checks:
    - free users whose daily limit has refreshed
    - premium users whose plan ends today / has expired

    interval_seconds defaults to 30 minutes.
    """
    logger.info("🕒 Reminder loop started")
    while True:
        try:
            settings = await get_settings()
            limit_use = int(settings.get("limit_use", 5) or 5)

            user_ids = await get_all_user_ids()
            if user_ids:
                await _handle_free_users(app, user_ids, limit_use)
                await _handle_premium_users(app, user_ids)

        except Exception as e:
            logger.exception(f"Reminder loop error: {e}")

        await asyncio.sleep(interval_seconds)


def start_reminders(app: Client, interval_seconds: int = 1800) -> asyncio.Task:
    """
    Start the reminder loop as a background task.
    Call this once after the bot client has started.
    """
    global _reminder_task

    if _reminder_task and not _reminder_task.done():
        return _reminder_task

    _reminder_task = asyncio.create_task(reminder_loop(app, interval_seconds))
    return _reminder_task
