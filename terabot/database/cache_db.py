import time
from motor.motor_asyncio import AsyncIOMotorCollection
import config

_col: AsyncIOMotorCollection = None


def init_cache_col(col: AsyncIOMotorCollection):
    global _col
    _col = col


async def cache_get(terabox_url: str) -> dict | None:
    doc = await _col.find_one({"terabox_url": terabox_url})
    if not doc:
        return None
    age = time.time() - doc["cached_at"]
    if age > config.CACHE_TTL_SECONDS:
        await cache_delete(terabox_url)
        return None
    return {
        "download_link": doc["download_link"],
        "file_name": doc["file_name"],
        "file_size": doc["file_size"],
        "thumbnail": doc.get("thumbnail"),
        "title": doc.get("title"),
    }


async def cache_set(
    terabox_url: str,
    download_link: str,
    file_name: str,
    file_size: int,
    thumbnail: str | None = None,
    title: str | None = None,
) -> None:
    await _col.update_one(
        {"terabox_url": terabox_url},
        {
            "$set": {
                "terabox_url": terabox_url,
                "download_link": download_link,
                "file_name": file_name,
                "file_size": file_size,
                "thumbnail": thumbnail,
                "title": title,
                "cached_at": time.time(),
            }
        },
        upsert=True,
    )


async def cache_delete(terabox_url: str) -> None:
    await _col.delete_one({"terabox_url": terabox_url})


async def cache_stats() -> dict:
    total = await _col.count_documents({})
    fresh = await _col.count_documents(
        {"cached_at": {"$gt": time.time() - config.CACHE_TTL_SECONDS}}
    )
    return {"fresh": fresh, "expired": total - fresh, "total": total}
