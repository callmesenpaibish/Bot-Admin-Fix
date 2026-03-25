import logging
import time
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

import config
from database.plans_db import get_plans, get_plan_by_id
from database.admin_db import get_settings, get_extra_admins
from database.users_db import set_premium, get_user

logger = logging.getLogger(__name__)

# In-memory state: user_id -> plan dict
pending_payments: dict[int, dict] = {}


async def _all_admin_ids() -> list[int]:
    extra = await get_extra_admins()
    return list(set(config.ADMIN_IDS + extra))


def _format_dt(ts: float | int | None) -> str:
    if not ts:
        return "Unknown"
    return datetime.fromtimestamp(float(ts)).strftime("%d %b %Y at %I:%M %p")


def _format_time_left(expiry_ts: float | int | None) -> str:
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


def _plans_keyboard(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for plan in plans:
        label = f"💎 {plan['name']} — ₹{plan['price']} / {plan['duration_days']} days"
        rows.append([InlineKeyboardButton(label, callback_data=f"buy:{plan['_id']}")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="pay:cancel")])
    return InlineKeyboardMarkup(rows)


def _account_overview_text(user: dict | None, settings: dict) -> str:
    now = time.time()
    is_active_premium = bool(
        user
        and user.get("is_premium")
        and user.get("premium_expiry")
        and float(user["premium_expiry"]) > now
    )

    if is_active_premium:
        purchased_on = user.get("premium_started_at") or user.get("premium_activated_at")
        total_downloads = user.get("total_downloads")

        text = (
            "🧾 **Account Overview**\n\n"
            "✨ **Membership:** Premium Active\n"
            "📦 **Plan Type:** Regular\n"
            "♾️ **Downloads:** Unlimited\n"
            f"⏳ **Time Left:** {_format_time_left(user.get('premium_expiry'))}\n"
        )

        if purchased_on:
            text += f"🕒 **Activated On:** {_format_dt(purchased_on)}\n"

        if total_downloads is not None:
            text += f"📁 **Total Downloads:** {total_downloads}\n"

        text += "\nEnjoy fast, unlimited access with priority processing."
        return text

    limit = int(settings.get("limit_use", 5))
    used_today = int(user.get("daily_count", 0)) if user else 0
    remaining = max(0, limit - used_today)

    if user and user.get("is_premium") and user.get("premium_expiry") and float(user["premium_expiry"]) <= now:
        status_line = "⚠️ **Membership:** Premium Expired"
        plan_line = "📦 **Plan Type:** Regular"
    else:
        status_line = "👤 **Membership:** Free Access"
        plan_line = "📦 **Plan Type:** Basic"

    return (
        "🧾 **Account Overview**\n\n"
        f"{status_line}\n"
        f"{plan_line}\n"
        f"📥 **Daily Limit:** {limit}\n"
        f"📊 **Used Today:** {used_today}\n"
        f"🟢 **Remaining Today:** {remaining}\n\n"
        "Your usage refreshes automatically every 24 hours."
    )


async def show_plans_message(client: Client, message: Message):
    """Called from user_panel when user taps 💎 Premium Plans."""
    user = await get_user(message.from_user.id)
    settings = await get_settings()
    plans = await get_plans()

    text = _account_overview_text(user, settings)

    buttons = []
    if plans:
        buttons.append([InlineKeyboardButton("💎 View Plans", callback_data="show_plans")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="pay:cancel")])

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


def register(app: Client):

    @app.on_callback_query(filters.regex("^show_plans$"))
    async def show_plans_cb(client: Client, callback: CallbackQuery):
        plans = await get_plans()
        if not plans:
            await callback.answer("No plans available yet!", show_alert=True)
            return

        await callback.answer()
        await callback.message.edit_text(
            "💎 **Premium Subscription Plans**\n\n"
            "Upgrade for unlimited downloads, no daily limits, and priority processing.\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Choose a plan to proceed 👇",
            reply_markup=_plans_keyboard(plans),
        )

    @app.on_callback_query(filters.regex(r"^buy:"))
    async def buy_plan_cb(client: Client, callback: CallbackQuery):
        plan_id = callback.data.split(":", 1)[1]
        plan = await get_plan_by_id(plan_id)
        if not plan:
            await callback.answer("⚠️ Plan not found!", show_alert=True)
            return

        settings = await get_settings()
        qr_file_id = settings.get("qr_file_id")

        await callback.answer()

        caption = (
            f"💳 **Payment Instructions**\n\n"
            f"📦 Plan: **{plan['name']}**\n"
            f"💰 Amount: **₹{plan['price']}**\n"
            f"⏳ Duration: **{plan['duration_days']} days**\n\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"Please pay **₹{plan['price']}** and send a screenshot of the payment here. 👇\n\n"
            f"⚠️ Your plan will be activated after admin verification."
        )

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ Cancel", callback_data="pay:cancel")
        ]])

        try:
            await callback.message.delete()
        except Exception:
            pass

        if qr_file_id:
            await client.send_photo(
                callback.from_user.id,
                photo=qr_file_id,
                caption=caption,
                reply_markup=kb,
            )
        else:
            await client.send_message(
                callback.from_user.id,
                caption,
                reply_markup=kb,
            )

        pending_payments[callback.from_user.id] = plan

    @app.on_callback_query(filters.regex("^pay:cancel$"))
    async def cancel_payment(client: Client, callback: CallbackQuery):
        pending_payments.pop(callback.from_user.id, None)
        await callback.answer("Cancelled.", show_alert=False)
        try:
            await callback.message.delete()
        except Exception:
            pass

    @app.on_message(filters.photo & filters.private)
    async def photo_handler(client: Client, message: Message):
        user_id = message.from_user.id
        plan = pending_payments.get(user_id)
        if not plan:
            return

        await message.reply_text(
            "✅ **Screenshot received!**\n\n"
            "Status: **Pending Approval ⏳**\n\n"
            "You'll be notified as soon as an admin verifies your payment. 🙏"
        )

        del pending_payments[user_id]

        user = message.from_user
        admin_caption = (
            f"💳 **New Payment Request**\n\n"
            f"👤 User: [{user.first_name}](tg://user?id={user.id})\n"
            f"🆔 ID: `{user.id}`\n"
            f"📦 Plan: **{plan['name']}** ({plan['duration_days']} days)\n"
            f"💰 Amount: ₹{plan['price']}"
        )
        approval_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "✅ Approve",
                callback_data=f"approve:{user.id}:{plan['duration_days']}"
            ),
            InlineKeyboardButton(
                "❌ Reject",
                callback_data=f"reject:{user.id}"
            ),
        ]])

        for admin_id in await _all_admin_ids():
            try:
                await client.send_photo(
                    admin_id,
                    photo=message.photo.file_id,
                    caption=admin_caption,
                    reply_markup=approval_kb,
                )
            except Exception as e:
                logger.warning(f"Could not notify admin {admin_id}: {e}")

    @app.on_callback_query(filters.regex(r"^approve:\d+:\d+$"))
    async def approve_cb(client: Client, callback: CallbackQuery):
        from utils.helpers import is_admin
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ Admins only!", show_alert=True)
            return

        _, user_id_str, days_str = callback.data.split(":")
        user_id, days = int(user_id_str), int(days_str)

        await set_premium(user_id, days)
        await callback.answer("✅ Premium activated!", show_alert=True)

        try:
            await callback.message.edit_caption(
                callback.message.caption + "\n\n✅ **APPROVED**",
                reply_markup=None,
            )
        except Exception:
            pass

        try:
            await client.send_message(
                user_id,
                f"🎉 **Premium Activated!**\n\n"
                f"Your payment has been verified. ✅\n"
                f"You now have **{days} days** of Premium access!\n\n"
                f"Enjoy unlimited downloads! 🚀"
            )
        except Exception as e:
            logger.warning(f"Could not notify user {user_id}: {e}")

    @app.on_callback_query(filters.regex(r"^reject:\d+$"))
    async def reject_cb(client: Client, callback: CallbackQuery):
        from utils.helpers import is_admin
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ Admins only!", show_alert=True)
            return

        user_id = int(callback.data.split(":")[1])
        await callback.answer("❌ Rejected.", show_alert=True)

        try:
            await callback.message.edit_caption(
                callback.message.caption + "\n\n❌ **REJECTED**",
                reply_markup=None,
            )
        except Exception:
            pass

        try:
            await client.send_message(
                user_id,
                "❌ **Payment Rejected**\n\n"
                "Your screenshot could not be verified.\n"
                "Please contact support if you believe this is a mistake. 📞"
            )
        except Exception as e:
            logger.warning(f"Could not notify user {user_id}: {e}")
