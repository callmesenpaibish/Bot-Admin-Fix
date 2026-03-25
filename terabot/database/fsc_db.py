from motor.motor_asyncio import AsyncIOMotorCollection

_col: AsyncIOMotorCollection = None


def init_fsc_col(col: AsyncIOMotorCollection):
    global _col
    _col = col


async def get_fsc_channels() -> list[dict]:
    cursor = _col.find({})
    return await cursor.to_list(length=None)


async def add_fsc_channel(chat_id: int, mode: str = "joined") -> None:
    """
    mode: 'joined' (strict) or 'requested' (pending request allowed)
    """
    await _col.update_one(
        {"_id": chat_id},
        {"$set": {"_id": chat_id, "mode": mode}},
        upsert=True,
    )


async def remove_fsc_channel(chat_id: int) -> None:
    await _col.delete_one({"_id": chat_id})
