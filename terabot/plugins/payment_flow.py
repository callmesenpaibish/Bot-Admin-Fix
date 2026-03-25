import logging
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

import config
from database.plans_db import get_plans, get_plan_by_id
from database.admin_db import get_settings, get_extra_admins
from database.users_db import set_premium

logger = logging.getLogger(__name__)

# In-memory state: user_id -> plan dict
pending_payments: dict[int, dict] = {}


async def _all_admin_ids() -> list[int]:
    extra = await get_extra_admins()
    return list(set(config.ADMIN_IDS + extra))


def _plans_keyboard(plans: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for plan in plans:
        label = f"💎 {plan['name']} — ₹{plan['price']} / {plan['duration_days']} days"
        rows.append([InlineKeyboardButton(label, callback_data=f"buy:{plan['_id']}")])
    rows.append([InlineKeyboardButton("❌ Cancel", callback_data="pay:cancel")])
    return InlineKeyboardMarkup(rows)


async def show_plans_message(client: Client, message: Message):
    """Called from user_panel when user taps 💎 Premium Plans."""
    plans = await get_plans()
    if not plans:
        await message.reply_text(
            "🚀 **Premium Plans — Coming Soon!**\n\n"
            "No plans are available yet. Check back later!"
        )
        return
    await message.reply_text(
        "💎 **Premium Subscription Plans**\n\n"
        "Upgrade for unlimited downloads, no daily limits, and priority processing.\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Choose a plan to proceed 👇",
        reply_markup=_plans_keyboard(plans),
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

        # Store pending state
        pending_payments[callback.from_user.id] = plan

    @app.on_callback_query(filters.regex("^pay:cancel$"))
    async def cancel_payment(client: Client, callback: CallbackQuery):
        pending_payments.pop(callback.from_user.id, None)
        await callback.answer("Cancelled.", show_alert=False)
        try:
            await callback.message.delete()
        except Exception:
            pass

    # ── Screenshot handler ────────────────────────────────────────────────────

    @app.on_message(filters.photo & filters.private)
    async def photo_handler(client: Client, message: Message):
        user_id = message.from_user.id
        plan = pending_payments.get(user_id)
        if not plan:
            return  # Not in payment flow — ignore

        # Confirm to user
        await message.reply_text(
            "✅ **Screenshot received!**\n\n"
            "Status: **Pending Approval ⏳**\n\n"
            "You'll be notified as soon as an admin verifies your payment. 🙏"
        )

        # Remove from pending state
        del pending_payments[user_id]

        # Forward to all admins with approve/reject buttons
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

    # ── Admin approval / rejection ────────────────────────────────────────────

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
