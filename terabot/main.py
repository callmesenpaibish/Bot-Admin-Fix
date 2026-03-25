import asyncio
import logging
import os
import sys
from pathlib import Path
from aiohttp import web, ClientSession, ClientTimeout, ClientResponseError
from pyrogram import Client
import motor.motor_asyncio

import config
# Assuming these are imported from your project files
# from plugins.database import init_plans_col, init_fsc_col, init_cache_col, init_database

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / "web"

PROXY_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.terabox.com/",
    "Origin": "https://www.terabox.com",
}

CHUNK_SIZE = 512 * 1024  # 512 KB streaming chunks

# --- PROXY LOGIC ---
async def video_proxy(request: web.Request) -> web.StreamResponse:
    url = request.rel_url.query.get("url", "").strip()
    if not url:
        return web.Response(status=400, text="Missing ?url= parameter")

    from urllib.parse import urlparse
    host = urlparse(url).netloc.lower()
    allowed = ("terabox.com", "1024terabox.com", "teraboxapp.com", "4funbox.com", "mirrobox.com", "workers.dev")
    
    if not any(host.endswith(a) for a in allowed):
        return web.Response(status=403, text="Only Terabox URLs are allowed")

    range_header = request.headers.get("Range")
    upstream_headers = dict(PROXY_HEADERS)
    if range_header:
        upstream_headers["Range"] = range_header

    try:
        async with ClientSession(timeout=ClientTimeout(total=None, connect=15)) as session:
            async with session.get(url, headers=upstream_headers, allow_redirects=True) as resp:
                if resp.status not in (200, 206):
                    return web.Response(status=resp.status, text=f"Upstream returned {resp.status}")

                response_headers = {
                    "Content-Type": resp.headers.get("Content-Type", "video/mp4"),
                    "Accept-Ranges": resp.headers.get("Accept-Ranges", "bytes"),
                    "Access-Control-Allow-Origin": "*",
                }
                if resp.headers.get("Content-Length"):
                    response_headers["Content-Length"] = resp.headers.get("Content-Length")
                if resp.headers.get("Content-Range"):
                    response_headers["Content-Range"] = resp.headers.get("Content-Range")

                stream_resp = web.StreamResponse(status=resp.status, headers=response_headers)
                await stream_resp.prepare(request)

                async for chunk in resp.content.iter_chunked(CHUNK_SIZE):
                    await stream_resp.write(chunk)

                await stream_resp.write_eof()
                return stream_resp

    except Exception as e:
        logger.error(f"Proxy error: {e}")
        return web.Response(status=500, text="Proxy error")

# --- BOT & WEB SETUP ---

def create_client() -> Client:
    return Client(
        "terabot_session",
        bot_token=config.BOT_TOKEN,
        api_id=config.API_ID,
        api_hash=config.API_HASH,
    )


def register_plugins(app: Client):
    from plugins import admin_panel, user_panel, terabox, payment_flow
    admin_panel.register(app)
    user_panel.register(app)
    terabox.register(app)
    payment_flow.register(app)
    logger.info("✅ All plugins registered")

async def health_check(request):
    return web.Response(text="✅ TeraBot is running!")

async def start_web_server():
    web_app = web.Application(client_max_size=0)
    web_app.router.add_get("/", health_check)
    web_app.router.add_get("/proxy", video_proxy)
    
    if WEB_DIR.exists():
        web_app.router.add_static("/web", WEB_DIR, show_index=True)
        logger.info(f"📁 Serving static files from {WEB_DIR}")

    runner = web.AppRunner(web_app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000)) # Render uses 'PORT' environment variable
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 Web server started on port {port}")

async def main():
    logger.info("🚀 Starting TeraBot Deployment...")

    # 1. FIX: Wait for Render to kill old instances to avoid AuthKeyDuplicated error
    logger.info("⏳ Waiting 15s for old sessions to clear...")
    await asyncio.sleep(15)

    # 2. Initialize MongoDB
    try:
        from database.users_db import init_users_col
        from database.admin_db import init_admin_col
        from database.cache_db import init_cache_col
        from database.plans_db import init_plans_col
        from database.fsc_db import init_fsc_col

        mongo_client = motor.motor_asyncio.AsyncIOMotorClient(config.MONGO_URI)
        db = mongo_client["terabot_db"]

        init_users_col(db["users"])
        init_admin_col(db["settings"])
        init_cache_col(db["link_cache"])
        init_plans_col(db["plans"])
        init_fsc_col(db["fsc_channels"])

        logger.info("✅ Database connected and collections initialized")
    except Exception as e:
        logger.error(f"❌ MongoDB Connection Failed: {e}")
        return

    # 3. Start Web Server
    await start_web_server()

    # 4. Start Telegram Client
    app = create_client()
    register_plugins(app)
    await app.start()
    
    me = await app.get_me()
    logger.info(f"🤖 Bot started as @{me.username}")
    
    # Keep the bot running
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
