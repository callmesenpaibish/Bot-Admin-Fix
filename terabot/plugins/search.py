import logging
import aiohttp
from urllib.parse import quote
from pyrogram import Client, filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)

import config
from plugins.fsub_handler import check_force_sub
from utils.helpers import format_size

logger = logging.getLogger(__name__)

SEARCH_URL = "https://xapiverse.com/api/terabox/search"
RESULTS_PER_PAGE = 5

# ── in-memory search session store: user_id -> {query, results, page} ─────────
_sessions: dict[int, dict] = {}


# ── API call ───────────────────────────────────────────────────────────────────

async def search_terabox(query: str, page: int = 1) -> list | None:
    headers = {"xAPIverse-Key": config.XAPIVERSE_KEY}
    params = {"q": query, "page": page}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                SEARCH_URL,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()

        if data.get("status") != "success":
            logger.warning(f"Search API non-success: {data}")
            return None

        items = data.get("results") or data.get("list") or data.get("data") or []
        if not isinstance(items, list):
            return None
        return items

    except Exception as e:
        logger.error(f"Search API error: {e}")
        return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_result_card(item: dict) -> str:
    title = item.get("title") or item.get("name") or "Untitled"
    size = item.get("size") or 0
    quality = item.get("quality") or item.get("resolution") or ""
    date = item.get("date") or item.get("created_at") or ""
    size_str = format_size(int(size)) if size else "Unknown"

    lines = [f"🎬 **{title}**"]
    if quality:
        lines.append(f"📺 Quality: `{quality}`")
    lines.append(f"📦 Size: `{size_str}`")
    if date:
        lines.append(f"📅 {date}")
    return "\n".join(lines)


def _build_item_keyboard(item: dict) -> InlineKeyboardMarkup:
    rows = []

    terabox_url = (
        item.get("url") or item.get("link") or item.get("terabox_url") or ""
    )
    download_link = (
        item.get("dlink") or item.get("download_link") or item.get("direct_link") or ""
    )

    if download_link:
        encoded_url = quote(download_link, safe="")
        file_name = item.get("name") or item.get("title") or "file"
        encoded_name = quote(file_name, safe="")
        player_url = f"{config.PLAYER_BASE_URL}?url={encoded_url}&name={encoded_name}"
        rows.append([InlineKeyboardButton("▶️ Watch Online", web_app=WebAppInfo(url=player_url))])
        rows.append([InlineKeyboardButton("📥 Download", url=download_link)])
    elif terabox_url:
        rows.append([InlineKeyboardButton("🔗 Open on Terabox", url=terabox_url)])

    return InlineKeyboardMarkup(rows) if rows else None


def _build_page_keyboard(user_id: int, page: int, has_next: bool) -> InlineKeyboardMarkup:
    rows = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"srch:prev:{user_id}"))
    if has_next:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"srch:next:{user_id}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton("🔎 New Search", callback_data="srch:new")])
    return InlineKeyboardMarkup(rows)


async def _send_results_page(message_or_cb, user_id: int, edit: bool = False):
    session = _sessions.get(user_id)
    if not session:
        text = "❌ Search session expired. Please /search again."
        if edit:
            await message_or_cb.edit_text(text)
        else:
            await message_or_cb.reply_text(text)
        return

    query = session["query"]
    page = session["page"]

    status_text = f"🔍 Searching for **{query}** (page {page})..."
    if edit:
        await message_or_cb.edit_text(status_text)
    else:
        status = await message_or_cb.reply_text(status_text)

    results = await search_terabox(query, page)

    if not results:
        no_result_text = (
            f"😕 **No results found for:** `{query}`\n\n"
            "Try a different search term."
        )
        if edit:
            await message_or_cb.edit_text(no_result_text)
        else:
            await status.edit_text(no_result_text)
        return

    # Store results and figure out pagination
    session["results"] = results
    has_next = len(results) >= RESULTS_PER_PAGE

    if not edit:
        await status.delete()

    # Send header
    header = (
        f"🔍 **Results for:** `{query}` — Page {page}\n"
        f"Found **{len(results)}** item(s) on this page\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    if edit:
        await message_or_cb.reply_text(header)
    else:
        await message_or_cb.reply_text(header)

    # Send each result card
    for item in results[:RESULTS_PER_PAGE]:
        card_text = _build_result_card(item)
        keyboard = _build_item_keyboard(item)

        thumbnail = (
            item.get("thumbnail") or item.get("thumb") or item.get("image") or ""
        )

        try:
            if thumbnail:
                await message_or_cb.reply_photo(
                    photo=thumbnail,
                    caption=card_text,
                    reply_markup=keyboard,
                )
            else:
                await message_or_cb.reply_text(card_text, reply_markup=keyboard)
        except Exception:
            await message_or_cb.reply_text(card_text, reply_markup=keyboard)

    # Send navigation keyboard
    nav_kb = _build_page_keyboard(user_id, page, has_next)
    await message_or_cb.reply_text(
        f"📄 Page **{page}** | Use the buttons below to navigate.",
        reply_markup=nav_kb,
    )


# ── Command & Button Handlers ──────────────────────────────────────────────────

def register(app: Client):

    @app.on_message(filters.command("search"))
    async def search_cmd(client: Client, message: Message):
        if not await check_force_sub(client, message):
            return

        args = message.command[1:]
        if not args:
            await message.reply_text(
                "🔍 **How to Search Terabox Content**\n\n"
                "Use the command like this:\n"
                "`/search movie name`\n\n"
                "**Examples:**\n"
                "• `/search Avengers`\n"
                "• `/search Tamil movies 2024`\n"
                "• `/search web series Hindi`\n\n"
                "You can also tap the **🔍 Search** button in the menu below."
            )
            return

        query = " ".join(args).strip()
        user_id = message.from_user.id

        _sessions[user_id] = {"query": query, "page": 1, "results": []}
        await _send_results_page(message, user_id, edit=False)

    @app.on_message(filters.text & filters.regex(r"^🔍 Search$"))
    async def search_button(client: Client, message: Message):
        if not await check_force_sub(client, message):
            return
        await message.reply_text(
            "🔍 **Search Terabox Content**\n\n"
            "Send me what you want to find:\n"
            "`/search movie name`\n\n"
            "**Examples:**\n"
            "• `/search Avengers`\n"
            "• `/search Tamil movies 2024`\n"
            "• `/search web series Hindi`"
        )

    @app.on_callback_query(filters.regex(r"^srch:"))
    async def search_nav_cb(client: Client, callback: CallbackQuery):
        await callback.answer()
        parts = callback.data.split(":")
        action = parts[1]

        if action == "new":
            await callback.message.reply_text(
                "🔍 Send your search query:\n`/search movie name`"
            )
            return

        user_id = int(parts[2]) if len(parts) > 2 else callback.from_user.id

        if callback.from_user.id != user_id:
            await callback.answer("⛔ This isn't your search session.", show_alert=True)
            return

        session = _sessions.get(user_id)
        if not session:
            await callback.message.reply_text("❌ Session expired. Please /search again.")
            return

        if action == "next":
            session["page"] += 1
        elif action == "prev" and session["page"] > 1:
            session["page"] -= 1

        await _send_results_page(callback.message, user_id, edit=False)
