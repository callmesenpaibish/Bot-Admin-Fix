import re
import logging
import asyncio
import aiohttp
from urllib.parse import quote
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import config
from database import cache_get, cache_set
from database.admin_db import get_settings
from database.users_db import increment_daily, get_user
from plugins.fsub_handler import check_force_sub
from utils.helpers import format_size, auto_delete

logger = logging.getLogger(__name__)

TERABOX_PATTERN = re.compile(r"(https?://[^\s]*tera[^\s]*)", re.IGNORECASE)


def build_result_keyboard(download_link: str, file_name: str) -> InlineKeyboardMarkup:
    encoded_url = quote(download_link, safe="")
    encoded_name = quote(file_name, safe="")
    player_url = f"{config.PLAYER_BASE_URL}?url={encoded_url}&name={encoded_name}"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("▶️ Watch Online", url=player_url)],
        [InlineKeyboardButton("📥 Direct Download Link", url=download_link)],
    ])


async def resolve_terabox_link(url: str) -> list | None:
    headers = {
        "Content-Type": "application/json",
        "xAPIverse-Key": config.XAPIVERSE_KEY,
    }
    payload = {"url": url}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.XAPIVERSE_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        if data.get("status") != "success" or not data.get("list"):
            logger.warning(f"API returned non-success: {data.get('status')}, url={url}")
            return None

        results = []
        for file_info in data["list"]:
            download_link = (
                file_info.get("dlink")
                or file_info.get("link")
                or file_info.get("download_link")
            )
            if not download_link:
                continue

            file_name = file_info.get("name", "terabox_file")
            file_size = int(file_info.get("size", 0))
            thumbnail = (
                file_info.get("thumb")
                or file_info.get("thumbnail")
                or file_info.get("image")
            )

            # Scrape og:image only for single-file links
            if not thumbnail and len(data["list"]) == 1:
                try:
                    async with aiohttp.ClientSession() as html_session:
                        async with html_session.get(
                            url, timeout=aiohttp.ClientTimeout(total=10)
                        ) as html_resp:
                            html_text = await html_resp.text()
                            og_match = re.search(
                                r'<meta property="og:image" content="([^"]+)"',
                                html_text,
                            )
                            if og_match:
                                thumbnail = og_match.group(1)
                except Exception as e:
                    logger.error(f"Scraper failed to find og:image: {e}")

            # Ultimate fallback thumbnail
            if not thumbnail:
                thumbnail = "https://i.ibb.co/wphN25P/terabox-default.jpg"

            title = file_info.get("title") or file_info.get("name") or file_name

            # Try to get file size via HEAD request if missing
            if file_size == 0:
                try:
                    async with aiohttp.ClientSession() as s:
                        async with s.head(
                            download_link,
                            allow_redirects=True,
                            timeout=aiohttp.ClientTimeout(total=10),
                        ) as hr:
                            file_size = int(hr.headers.get("Content-Length", 0))
                except Exception:
                    pass

            results.append({
                "download_link": download_link,
                "file_name": file_name,
                "file_size": file_size,
                "thumbnail": thumbnail,
                "title": title,
            })

        return results if results else None

    except aiohttp.ClientResponseError as e:
        logger.error(f"API HTTP Error {e.status}: {e.message}")
        return None
    except Exception as e:
        logger.error(f"Unexpected resolve error: {e}", exc_info=True)
        return None


async def send_file_result(message: Message, result: dict, settings: dict):
    """Send a single file result with thumbnail + buttons."""
    keyboard = build_result_keyboard(result["download_link"], result["file_name"])
    size_str = format_size(result["file_size"])
    caption = (
        f"🎬 **{result['title']}**\n\n"
        f"📦 Size: `{size_str}`"
    )

    protect = not settings.get("forwarding", True)

    if result.get("thumbnail"):
        try:
            sent = await message.reply_photo(
                photo=result["thumbnail"],
                caption=caption,
                reply_markup=keyboard,
            )
            return sent
        except Exception as e:
            logger.error(f"Thumbnail send failed: {e}")

    # Fallback to text if thumbnail fails
    sent = await message.reply_text(caption, reply_markup=keyboard, protect_content=protect)
    return sent


async def handle_terabox(client: Client, message: Message):
    user_id = message.from_user.id

    if not await check_force_sub(client, message):
        return

    settings = await get_settings()

    user = await get_user(user_id)
    is_premium = user and user.get("is_premium", False)

    if not is_premium:
        limit = settings.get("limit_use", 5)
        daily_count = await increment_daily(user_id)
        if daily_count > limit:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✨ Get Premium", callback_data="show_plans")
            ]])
            msg = await message.reply_text(
                f"⚠️ **Daily Limit Reached**\n\n"
                f"Free users can download **{limit} files** per day.\n"
                f"Upgrade to Premium for unlimited access! 🚀",
                reply_markup=kb,
            )
            deltime = settings.get("deltime", 0)
            if deltime > 0:
                asyncio.create_task(auto_delete(msg, deltime))
            return

    # Support both plain text AND forwarded messages (which use caption, not text)
    message_text = message.text or message.caption or ""
    url_match = TERABOX_PATTERN.search(message_text)
    if not url_match:
        return
    extracted_url = url_match.group(1)

    status_msg = await message.reply_text("🔄 **Processing your Terabox link...**")

    # Try cache first
    cached = await cache_get(extracted_url)
    if cached:
        results = [cached]
        source_label = "⚡ Served from cache"
    else:
        await status_msg.edit_text("🌐 **Fetching fresh link from API...**")
        results = await resolve_terabox_link(extracted_url)
        if not results:
            await status_msg.edit_text(
                "❌ **Failed to resolve this link.**\n\n"
                "Make sure the Terabox link is public and try again."
            )
            return
        # Cache only the first file result
        r = results[0]
        await cache_set(
            extracted_url,
            r["download_link"],
            r["file_name"],
            r["file_size"],
            r["thumbnail"],
            r["title"],
        )
        source_label = "🔗 Resolved via API"

    await status_msg.delete()

    # If folder with multiple files, send a header message
    if len(results) > 1:
        await message.reply_text(
            f"📂 **Found {len(results)} files in this link!**\n"
            f"Sending them one by one... 👇"
        )

    deltime = settings.get("deltime", 0)
    sent = None
    for result in results:
        sent = await send_file_result(message, result, settings)
        if deltime > 0 and sent:
            asyncio.create_task(auto_delete(sent, deltime))
        if len(results) > 1:
            await asyncio.sleep(0.5)


def register(app: Client):
    @app.on_message(
        (filters.text | filters.caption)
        & ~filters.command(
            [
                "start", "admin", "stats", "broadcast", "addadmin", "admins",
                "addfsc", "delfsc", "forwarding", "deltime", "limituse",
                "addplan", "delplan", "plans", "setqr", "approve", "reject",
                "myplan", "contact",
            ]
        )
    )
    async def _handler(client: Client, message: Message):
        message_text = message.text or message.caption or ""
        if TERABOX_PATTERN.search(message_text):
            await handle_terabox(client, message)
