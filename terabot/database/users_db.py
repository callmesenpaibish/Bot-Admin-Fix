import time
import logging
from motor.motor_asyncio import AsyncIOMotorCollection

logger = logging.getLogger(__name__)

_col: AsyncIOMotorCollection = None


def _get_col() -> AsyncIOMotorCollection:
    return _col


def init_users_col(col: AsyncIOMotorCollection):
    global _col
    _col = col


async def migrate_users_col() -> None:
    """Drop any stale legacy indexes that conflict with the current schema."""
    col = _get_col()
    try:
        indexes = await col.index_information()
        # Drop the old 'user_id_1' index if it exists — we use '_id' as the user key
        if "user_id_1" in indexes:
            await col.drop_index("user_id_1")
            logger.info("🗑️ Dropped stale index 'user_id_1' from users collection")
    except Exception as e:
        logger.warning(f"Index migration warning: {e}")


async def upsert_user(user_id: int, first_name: str = "", username: str = "") -> None:
    col = _get_col()
    try:
        await col.update_one(
            {"_id": user_id},
            {
                "$setOnInsert": {
                    "_id": user_id,
                    "first_name": first_name,
                    "username": username,
                    "joined_at": time.time(),
                    "is_premium": False,
                    "premium_expiry": None,
                    "daily_count": 0,
                    "last_reset": time.time(),
                }
            },
            upsert=True,
        )
        await col.update_one(
            {"_id": user_id},
            {"$set": {"first_name": first_name, "username": username}},
        )
    except Exception as e:
        logger.error(f"upsert_user({user_id}) failed: {e}")


async def get_user(user_id: int) -> dict | None:
    return await _get_col().find_one({"_id": user_id})


async def set_premium(user_id: int, days: int) -> None:
    expiry = time.time() + days * 86400
    await _get_col().update_one(
        {"_id": user_id},
        {"$set": {"is_premium": True, "premium_expiry": expiry}},
        upsert=True,
    )


async def revoke_premium(user_id: int) -> None:
    await _get_col().update_one(
        {"_id": user_id},
        {"$set": {"is_premium": False, "premium_expiry": None}},
    )


async def increment_daily(user_id: int) -> int:
    now = time.time()
    user = await get_user(user_id)
    if user and (now - user.get("last_reset", 0)) > 86400:
        await _get_col().update_one(
            {"_id": user_id},
            {"$set": {"daily_count": 0, "last_reset": now}},
        )
    result = await _get_col().find_one_and_update(
        {"_id": user_id},
        {"$inc": {"daily_count": 1}},
        return_document=True,
    )
    return result["daily_count"] if result else 1


async def get_all_user_ids() -> list[int]:
    cursor = _get_col().find({}, {"_id": 1})
    docs = await cursor.to_list(length=None)
    return [d["_id"] for d in docs]


async def get_stats() -> dict:
    col = _get_col()
    total = await col.count_documents({})
    premium = await col.count_documents({"is_premium": True})
    daily_cutoff = time.time() - 86400
    daily_active = await col.count_documents({"last_reset": {"$gte": daily_cutoff}})
    return {"total": total, "premium": premium, "daily_active": daily_active}
