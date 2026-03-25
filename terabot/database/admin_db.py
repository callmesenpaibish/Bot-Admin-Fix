from motor.motor_asyncio import AsyncIOMotorCollection

_col: AsyncIOMotorCollection = None


def init_admin_col(col: AsyncIOMotorCollection):
    global _col
    _col = col


_DEFAULTS = {
    "forwarding": True,
    "deltime": 0,
    "limit_use": 5,
    "qr_file_id": None,
    "admins": [],
}


async def get_settings() -> dict:
    doc = await _col.find_one({"_id": "settings"})
    if not doc:
        await _col.insert_one({"_id": "settings", **_DEFAULTS})
        return dict(_DEFAULTS)
    return doc


async def set_setting(key: str, value) -> None:
    await _col.update_one(
        {"_id": "settings"},
        {"$set": {key: value}},
        upsert=True,
    )


async def get_extra_admins() -> list[int]:
    settings = await get_settings()
    return settings.get("admins", [])


async def add_extra_admin(user_id: int) -> None:
    await _col.update_one(
        {"_id": "settings"},
        {"$addToSet": {"admins": user_id}},
        upsert=True,
    )


async def remove_extra_admin(user_id: int) -> None:
    await _col.update_one(
        {"_id": "settings"},
        {"$pull": {"admins": user_id}},
    )
