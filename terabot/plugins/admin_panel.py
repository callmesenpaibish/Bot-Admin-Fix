import asyncio
import json
import logging
from pyrogram import Client, filters
from pyrogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
)

# Custom filter: messages that carry Telegram WebApp data
_web_app_data_filter = filters.create(
    lambda _, __, m: bool(m.web_app_data),
    name="web_app_data",
)

import config
from database.users_db import get_stats, get_all_user_ids
from database.admin_db import (
    get_settings, set_setting, add_extra_admin, remove_extra_admin, get_extra_admins,
)
from database.plans_db import get_plans, add_plan, delete_plan
from database.fsc_db import get_fsc_channels, add_fsc_channel, remove_fsc_channel
from database.cache_db import cache_stats
from utils.helpers import is_admin

logger = logging.getLogger(__name__)


# ── Helper ────────────────────────────────────────────────────────────────────

def _admin_filter(func):
    async def wrapper(client: Client, message: Message):
        if not await is_admin(message.from_user.id):
            await message.reply_text("⛔ **Access Denied.** Admin only.")
            return
        await func(client, message)
    return wrapper


def _admin_panel_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📊 Stats",       callback_data="adm:stats"),
            InlineKeyboardButton("📣 Broadcast",   callback_data="adm:broadcast"),
        ],
        [
            InlineKeyboardButton("👤 Add Admin",   callback_data="adm:addadmin"),
            InlineKeyboardButton("🗑 Del Admin",   callback_data="adm:deladmin"),
        ],
        [
            InlineKeyboardButton("📋 List Admins", callback_data="adm:listadmins"),
            InlineKeyboardButton("🔒 Force Sub",   callback_data="adm:addfsc"),
        ],
        [
            InlineKeyboardButton("🔓 Del FSub",    callback_data="adm:delfsc"),
            InlineKeyboardButton("🔄 Forwarding",  callback_data="adm:forwarding"),
        ],
        [
            InlineKeyboardButton("⏱ Del Timer",   callback_data="adm:deltime"),
            InlineKeyboardButton("🔢 User Limit",  callback_data="adm:limituse"),
        ],
        [
            InlineKeyboardButton("📋 List Plans",  callback_data="adm:plans"),
            InlineKeyboardButton("🗑 Del Plan",    callback_data="adm:delplan"),
        ],
        [
            InlineKeyboardButton("🖼 Set QR Code", callback_data="adm:setqr"),
        ],
    ]
    # Add GUI button only if web URL is configured
    if config.WEB_BASE_URL:
        rows.append([
            InlineKeyboardButton(
                "⚙️ Manage Plans (GUI)",
                web_app=WebAppInfo(url=f"{config.WEB_BASE_URL}/web/admin_dashboard.html")
            )
        ])
    return InlineKeyboardMarkup(rows)


_HELP = {
    "stats":      "📊 **Stats**\n\nCommand: `/stats`\n\nShows total users, daily active, premium count and cache stats.",
    "broadcast":  "📣 **Broadcast**\n\nCommand: `/broadcast`\n\nReply to **any message** with `/broadcast` to send it to all users in the database.\n\n⚠️ Large user bases may take time.",
    "addadmin":   "👤 **Add Admin**\n\nCommand: `/addadmin <user_id>`\n\nExample: `/addadmin 123456789`\n\nGrants admin access to a user.",
    "deladmin":   "🗑 **Remove Admin**\n\nCommand: `/deladmin <user_id>`\n\nExample: `/deladmin 123456789`\n\nRevokes admin access.",
    "listadmins": "📋 **List Admins**\n\nCommand: `/admins`\n\nShows all owners (from config) and extra admins.",
    "addfsc":     "🔒 **Add Force Sub**\n\nCommand: `/addfsc <chat_id> [$joined | $requested]`\n\nExample: `/addfsc -1001234567890 $joined`\n\n• `$joined` — user must be a member\n• `$requested` — pending request also accepted",
    "delfsc":     "🔓 **Remove Force Sub**\n\nCommand: `/delfsc <chat_id>`\n\nExample: `/delfsc -1001234567890`",
    "forwarding": "🔄 **Forwarding**\n\nCommand: `/forwarding True` or `/forwarding False`\n\nControls whether users can forward downloaded files.",
    "deltime":    "⏱ **Auto-Delete Timer**\n\nCommand: `/deltime <seconds>`\n\nExample: `/deltime 60` — deletes bot messages after 60 seconds.\nUse `0` to disable.",
    "limituse":   "🔢 **Daily Download Limit**\n\nCommand: `/limituse <number>`\n\nExample: `/limituse 5` — free users can download 5 files per day.",
    "plans":      "📋 **List Plans**\n\nCommand: `/plans`\n\nShows all active premium subscription plans with IDs.",
    "delplan":    "🗑 **Delete Plan**\n\nCommand: `/delplan <plan_id>`\n\nExample: `/delplan 64abc...`\n\nGet the ID from `/plans`.",
    "setqr":      "🖼 **Set QR Code**\n\nCommand: `/setqr`\n\nReply to a **photo** with `/setqr` to set the payment QR code shown to users.",
}

_BACK_KB = InlineKeyboardMarkup([[
    InlineKeyboardButton("⬅️ Back to Admin Panel", callback_data="adm:back")
]])


# ── Handlers ──────────────────────────────────────────────────────────────────

def register(app: Client):

    # /admin — open the inline admin panel
    @app.on_message(filters.command("admin"))
    @_admin_filter
    async def admin_cmd(client: Client, message: Message):
        await message.reply_text(
            "🛠 **Admin Panel**\n\n"
            "Select an action below:",
            reply_markup=_admin_panel_keyboard(),
        )

    # Inline button help texts
    @app.on_callback_query(filters.regex(r"^adm:(?!back$)"))
    async def admin_help_cb(client: Client, callback: CallbackQuery):
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ Access Denied.", show_alert=True)
            return

        action = callback.data.split(":", 1)[1]

        if action == "stats":
            # Show live stats directly instead of just instructions
            user_stats = await get_stats()
            cache = await cache_stats()
            settings = await get_settings()
            text = (
                "📊 **Bot Statistics**\n\n"
                f"👥 Total Users: `{user_stats['total']}`\n"
                f"📅 Daily Active: `{user_stats['daily_active']}`\n"
                f"✨ Premium Users: `{user_stats['premium']}`\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"🗄️ **Cache**\n"
                f"✅ Fresh: `{cache['fresh']}` | ⏰ Expired: `{cache['expired']}`\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                f"⚙️ **Settings**\n"
                f"🔄 Forwarding: `{settings.get('forwarding', True)}`\n"
                f"⏱️ Delete Timer: `{settings.get('deltime', 0)}s`\n"
                f"🔢 Daily Limit: `{settings.get('limit_use', 5)}`"
            )
        elif action == "plans":
            plans = await get_plans()
            if not plans:
                text = "📋 **Plans**\n\nNo plans configured yet.\nUse the **⚙️ Manage Plans (GUI)** button or `/addplan` to add one."
            else:
                lines = ["📋 **Active Plans:**\n"]
                for p in plans:
                    lines.append(f"• **{p['name']}** — `₹{p['price']}` / `{p['duration_days']}d`\n  🆔 `{p['_id']}`")
                text = "\n".join(lines)
        else:
            text = _HELP.get(action, "ℹ️ No help available for this action.")

        await callback.answer()
        await callback.message.edit_text(text, reply_markup=_BACK_KB)

    # Back button
    @app.on_callback_query(filters.regex(r"^adm:back$"))
    async def admin_back_cb(client: Client, callback: CallbackQuery):
        if not await is_admin(callback.from_user.id):
            await callback.answer("⛔ Access Denied.", show_alert=True)
            return
        await callback.answer()
        await callback.message.edit_text(
            "🛠 **Admin Panel**\n\nSelect an action below:",
            reply_markup=_admin_panel_keyboard(),
        )

    # WebApp data handler — receives plan + QR data from admin_dashboard.html
    @app.on_message(_web_app_data_filter)
    async def webapp_data_handler(client: Client, message: Message):
        if not await is_admin(message.from_user.id):
            return
        try:
            payload = json.loads(message.web_app_data.data)
        except Exception:
            await message.reply_text("❌ Invalid data received from Web App.")
            return

        action = payload.get("action")

        if action == "save_plan":
            name = payload.get("name", "").strip()
            price = payload.get("price")
            days = payload.get("days")

            if not name or price is None or days is None:
                await message.reply_text("❌ Missing fields: name, price, or days.")
                return

            plan_id = await add_plan(name, float(price), int(days))

            # If a QR file_id was sent separately and stored, link it to the plan
            qr_file_id = payload.get("qr_file_id")
            if qr_file_id:
                await set_setting("qr_file_id", qr_file_id)

            await message.reply_text(
                f"✅ **Plan Saved!**\n\n"
                f"📦 Name: `{name}`\n"
                f"💰 Price: `₹{price}`\n"
                f"⏳ Duration: `{days} days`\n"
                f"🆔 ID: `{plan_id}`"
            )

        elif action == "save_settings":
            for key in ("forwarding", "deltime", "limit_use"):
                if key in payload:
                    await set_setting(key, payload[key])
            await message.reply_text("✅ **Settings updated via Web App.**")

        else:
            await message.reply_text(f"⚠️ Unknown action: `{action}`")

    # ── Text commands (still work alongside the inline panel) ─────────────────

    @app.on_message(filters.command("stats"))
    @_admin_filter
    async def stats_cmd(client: Client, message: Message):
        user_stats = await get_stats()
        cache = await cache_stats()
        settings = await get_settings()
        await message.reply_text(
            "📊 **Bot Statistics**\n\n"
            f"👥 Total Users: `{user_stats['total']}`\n"
            f"📅 Daily Active: `{user_stats['daily_active']}`\n"
            f"✨ Premium Users: `{user_stats['premium']}`\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🗄️ **Cache Stats**\n"
            f"✅ Fresh: `{cache['fresh']}`\n"
            f"⏰ Expired: `{cache['expired']}`\n"
            f"📦 Total: `{cache['total']}`\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"⚙️ **Settings**\n"
            f"🔄 Forwarding: `{settings.get('forwarding', True)}`\n"
            f"⏱️ Delete Timer: `{settings.get('deltime', 0)}s`\n"
            f"🔢 Daily Limit: `{settings.get('limit_use', 5)}`"
        )

    @app.on_message(filters.command("broadcast"))
    @_admin_filter
    async def broadcast_cmd(client: Client, message: Message):
        if not message.reply_to_message:
            await message.reply_text("ℹ️ Reply to a message with `/broadcast` to send it to all users.")
            return
        user_ids = await get_all_user_ids()
        total = len(user_ids)
        success = failed = 0
        status = await message.reply_text(f"📣 **Broadcasting to {total} users...**")
        for i, uid in enumerate(user_ids):
            try:
                await message.reply_to_message.copy(uid)
                success += 1
            except Exception:
                failed += 1
            if (i + 1) % 50 == 0:
                try:
                    await status.edit_text(
                        f"📣 **Broadcasting...**\n\n"
                        f"✅ Sent: `{success}` | ❌ Failed: `{failed}`\n"
                        f"📊 Progress: `{i+1}/{total}`"
                    )
                except Exception:
                    pass
            await asyncio.sleep(0.05)
        await status.edit_text(
            f"✅ **Broadcast Complete!**\n\n"
            f"👥 Total: `{total}`\n"
            f"✅ Delivered: `{success}`\n"
            f"❌ Failed: `{failed}`"
        )

    @app.on_message(filters.command("addadmin"))
    @_admin_filter
    async def add_admin_cmd(client: Client, message: Message):
        args = message.command[1:]
        if not args:
            await message.reply_text("ℹ️ Usage: `/addadmin <user_id>`")
            return
        try:
            uid = int(args[0])
        except ValueError:
            await message.reply_text("❌ Invalid user ID.")
            return
        await add_extra_admin(uid)
        await message.reply_text(f"✅ User `{uid}` added as admin.")

    @app.on_message(filters.command("admins"))
    @_admin_filter
    async def list_admins_cmd(client: Client, message: Message):
        extra = await get_extra_admins()
        owner_list = "\n".join(f"• `{a}`" for a in config.ADMIN_IDS)
        extra_list = "\n".join(f"• `{a}`" for a in extra) if extra else "_None_"
        await message.reply_text(
            f"👑 **Owners**\n{owner_list}\n\n"
            f"🛡️ **Extra Admins**\n{extra_list}"
        )

    @app.on_message(filters.command("deladmin"))
    @_admin_filter
    async def del_admin_cmd(client: Client, message: Message):
        args = message.command[1:]
        if not args:
            await message.reply_text("ℹ️ Usage: `/deladmin <user_id>`")
            return
        try:
            uid = int(args[0])
        except ValueError:
            await message.reply_text("❌ Invalid user ID.")
            return
        await remove_extra_admin(uid)
        await message.reply_text(f"✅ User `{uid}` removed from admins.")

    @app.on_message(filters.command("addfsc"))
    @_admin_filter
    async def add_fsc_cmd(client: Client, message: Message):
        args = message.command[1:]
        if not args:
            await message.reply_text("ℹ️ Usage: `/addfsc <chat_id> [$joined | $requested]`")
            return
        try:
            chat_id = int(args[0])
        except ValueError:
            await message.reply_text("❌ Invalid chat ID.")
            return
        mode = "requested" if len(args) > 1 and args[1] == "$requested" else "joined"
        await add_fsc_channel(chat_id, mode)
        await message.reply_text(f"✅ Force-sub channel `{chat_id}` added. Mode: `{mode}`")

    @app.on_message(filters.command("delfsc"))
    @_admin_filter
    async def del_fsc_cmd(client: Client, message: Message):
        args = message.command[1:]
        if not args:
            await message.reply_text("ℹ️ Usage: `/delfsc <chat_id>`")
            return
        try:
            chat_id = int(args[0])
        except ValueError:
            await message.reply_text("❌ Invalid chat ID.")
            return
        await remove_fsc_channel(chat_id)
        await message.reply_text(f"✅ Channel `{chat_id}` removed from force-sub list.")

    @app.on_message(filters.command("forwarding"))
    @_admin_filter
    async def forwarding_cmd(client: Client, message: Message):
        args = message.command[1:]
        if not args or args[0].lower() not in ("true", "false"):
            await message.reply_text("ℹ️ Usage: `/forwarding True` or `/forwarding False`")
            return
        value = args[0].lower() == "true"
        await set_setting("forwarding", value)
        await message.reply_text(f"🔄 Forwarding: {'✅ Enabled' if value else '🚫 Disabled'}")

    @app.on_message(filters.command("deltime"))
    @_admin_filter
    async def deltime_cmd(client: Client, message: Message):
        args = message.command[1:]
        if not args:
            await message.reply_text("ℹ️ Usage: `/deltime <seconds>` (0 to disable)")
            return
        try:
            seconds = int(args[0])
        except ValueError:
            await message.reply_text("❌ Invalid number.")
            return
        await set_setting("deltime", seconds)
        await message.reply_text(
            "⏱️ Auto-delete: **Disabled**" if seconds == 0
            else f"⏱️ Auto-delete set to `{seconds}` seconds."
        )

    @app.on_message(filters.command("limituse"))
    @_admin_filter
    async def limit_cmd(client: Client, message: Message):
        args = message.command[1:]
        if not args:
            await message.reply_text("ℹ️ Usage: `/limituse <number>`")
            return
        try:
            limit = int(args[0])
        except ValueError:
            await message.reply_text("❌ Invalid number.")
            return
        await set_setting("limit_use", limit)
        await message.reply_text(f"🔢 Daily limit set to `{limit}` for free users.")

    @app.on_message(filters.command("addplan"))
    @_admin_filter
    async def add_plan_cmd(client: Client, message: Message):
        args = message.command[1:]
        if len(args) < 3:
            await message.reply_text("ℹ️ Usage: `/addplan <name> <price> <days>`\nExample: `/addplan Monthly 4.99 30`")
            return
        name = args[0]
        try:
            price = float(args[1])
            days = int(args[2])
        except ValueError:
            await message.reply_text("❌ Invalid price or days.")
            return
        plan_id = await add_plan(name, price, days)
        await message.reply_text(
            f"✅ **Plan Added!**\n\n📦 `{name}` — `₹{price}` / `{days}d`\n🆔 `{plan_id}`"
        )

    @app.on_message(filters.command("delplan"))
    @_admin_filter
    async def del_plan_cmd(client: Client, message: Message):
        args = message.command[1:]
        if not args:
            await message.reply_text("ℹ️ Usage: `/delplan <plan_id>`")
            return
        await delete_plan(args[0])
        await message.reply_text(f"✅ Plan `{args[0]}` deleted.")

    @app.on_message(filters.command("plans"))
    @_admin_filter
    async def list_plans_cmd(client: Client, message: Message):
        plans = await get_plans()
        if not plans:
            await message.reply_text("📋 No plans yet. Use `/addplan` or the GUI.")
            return
        lines = ["📋 **Active Plans:**\n"]
        for p in plans:
            lines.append(f"• **{p['name']}** — `₹{p['price']}` / `{p['duration_days']}d`\n  🆔 `{p['_id']}`")
        await message.reply_text("\n".join(lines))

    @app.on_message(filters.command("setqr"))
    @_admin_filter
    async def set_qr_cmd(client: Client, message: Message):
        if not message.reply_to_message or not message.reply_to_message.photo:
            await message.reply_text("ℹ️ Reply to a **photo** with `/setqr` to set the payment QR code.")
            return
        file_id = message.reply_to_message.photo.file_id
        await set_setting("qr_file_id", file_id)
        await message.reply_text("✅ Payment QR Code updated!")
