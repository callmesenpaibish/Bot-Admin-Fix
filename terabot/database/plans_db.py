import time
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorCollection

_col: AsyncIOMotorCollection = None


def init_plans_col(col: AsyncIOMotorCollection):
    global _col
    _col = col


async def get_plans() -> list[dict]:
    cursor = _col.find({})
    return await cursor.to_list(length=None)


async def get_plan_by_id(plan_id: str) -> dict | None:
    try:
        return await _col.find_one({"_id": ObjectId(plan_id)})
    except Exception:
        return None


async def add_plan(name: str, price: float, duration_days: int) -> str:
    doc = {
        "name": name,
        "price": price,
        "duration_days": duration_days,
        "created_at": time.time(),
    }
    result = await _col.insert_one(doc)
    return str(result.inserted_id)


async def edit_plan(plan_id: str, **kwargs) -> None:
    try:
        await _col.update_one({"_id": ObjectId(plan_id)}, {"$set": kwargs})
    except Exception:
        pass


async def delete_plan(plan_id: str) -> None:
    try:
        await _col.delete_one({"_id": ObjectId(plan_id)})
    except Exception:
        pass
