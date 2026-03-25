import time
import logging
import base64
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

import config
from database.users_db import upsert_user, get_user
from database.admin_db import get_settings
from utils.helpers import build_main_keyboard, format_timestamp
from plugins.payment_flow import show_plans_message  # ✅ ADD THIS

logger = logging.getLogger(__name__)

def register(app: Client):

    @app.on_message(filters.command("start"))
    async def start_cmd(client: Client, message: Message):
        user = message.from_user
        await upsert_user(user.id, user.first_name or "", user.username or "")

        # --- DEEP LINK DECODING LOGIC ---
        if len(message.command) > 1:
            encoded_payload = message.command[1]
            try:
                padding = '=' * (4 - (len(encoded_payload) % 4))
                decoded_bytes = base64.urlsafe_b64decode(encoded_payload + padding)
                terabox_link = decoded_bytes.decode('utf-8')
                
                from plugins.terabox import handle_terabox
                message.text = terabox_link 
                await handle_terabox(client, message)
                return
                
            except Exception as e:
                logger.error(f"Failed to decode deep link: {e}")
                await message.reply_text("❌ Oops! That hidden link looks broken or invalid.")
        # --------------------------------

        text = (
        f"👋 **Welcome to TeraBot, {user.first_name}.**\n\n"
        "The fastest and most reliable way to process your Terabox links directly inside Telegram.\n\n"
        "Simply send me any valid Terabox URL, and I will instantly generate:\n"
        "━━━━━━━━━━━━━━━\n"
        "▶️ **Direct Streaming** — Watch instantly without leaving the app.\n"
        "📥 **Secure Downloads** — Get the direct file link to save to your device.\n"
        "━━━━━━━━━━━━━━━\n\n"
        "👇 Send a link to begin, or use the menu below."
        )
        await message.reply_text(text, reply_markup=build_main_keyboard())

    @app.on_message(filters.text & filters.regex(r"^🔽 Download video$"))
    async def download_prompt(client: Client, message: Message):
        await message.reply_text(
            "📥 **Send me your Terabox link and I'll download it instantly!**\n\n"
            "Just paste any Terabox URL and I'll handle the rest. 🚀"
        )

    # ✅ FIX: Premium Plans handler (THIS WAS MISSING)
    @app.on_message(filters.text & filters.regex(r"^💎 Premium Plans$"))
    async def premium_plans(client: Client, message: Message):
        await show_plans_message(client, message)

    @app.on_message(filters.text & filters.regex(r"^📞 Contact us$"))
    async def contact_us(client: Client, message: Message):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💬 Support Chat", url=config.SUPPORT_CHAT)
        ]])
        await message.reply_text(
            "📞 **Contact & Support**\n\n"
            "Need help? Our support team is ready to assist you!\n"
            "Click the button below to open the support chat. 👇",
            reply_markup=kb,
        )

    @app.on_callback_query(filters.regex("^fsub_check$"))
    async def fsub_recheck(client: Client, callback: CallbackQuery):
        from plugins.fsub_handler import check_force_sub
        passed = await check_force_sub(client, callback.message)
        if passed:
            await callback.answer("✅ Access granted! You can now use the bot.", show_alert=True)
            await callback.message.delete()
        else:
            await callback.answer("❌ You haven't joined all required channels yet!", show_alert=True)
