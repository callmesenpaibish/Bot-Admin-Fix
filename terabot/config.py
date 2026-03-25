import os
from dotenv import load_dotenv

load_dotenv()


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise ValueError(f"Missing required environment variable: {key}")
    return val


BOT_TOKEN: str = _require("BOT_TOKEN")
API_ID: int = int(_require("API_ID"))
API_HASH: str = _require("API_HASH")
MONGO_URI: str = _require("MONGO_URI")
XAPIVERSE_KEY: str = _require("XAPIVERSE_KEY")

_raw_admin_ids = _require("ADMIN_IDS")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _raw_admin_ids.split(",") if x.strip()]

SUPPORT_CHAT: str = os.environ.get("SUPPORT_CHAT", "https://t.me/secretsocietysupportbot")

CACHE_TTL_SECONDS: int = int(os.environ.get("CACHE_TTL_SECONDS", "3600"))
XAPIVERSE_URL: str = "https://xapiverse.com/api/terabox"

# Web App base URL — set this to your HTTPS domain (e.g. https://yourbot.replit.app)
_dev_domain = os.environ.get("REPLIT_DEV_DOMAIN", "")
WEB_BASE_URL: str = os.environ.get(
    "WEB_BASE_URL",
    f"https://{_dev_domain}" if _dev_domain else ""
)

# Player URL — use the GitHub Pages hosted player by default.
# Override PLAYER_BASE_URL env var to point at a custom player.
PLAYER_BASE_URL: str = os.environ.get(
    "PLAYER_BASE_URL",
    "https://callmesenpaibish.github.io/player/player.html",
)
