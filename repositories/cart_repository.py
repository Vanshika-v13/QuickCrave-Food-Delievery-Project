"""carts collection — one document per user_id."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from repositories import food_repository
from repositories.mongo_client import get_collection


def _coll():
    return get_collection("carts")


def ensure_indexes():
    _coll().create_index("user_id", unique=True)


def _enrich_items(items: List[Dict]) -> List[Dict[str, Any]]:
    out = []
    for it in items:
        row = food_repository.fetch_food_item_by_legacy_mysql_id(it["item_id"])
        if not row:
            continue
        out.append(
            {
                "item_id": row["item_id"],
                "name": row["name"],
                "price": row["price"],
                "description": row.get("description"),
                "quantity": int(it.get("quantity", 1)),
                "image_url": row.get("image_url"),
            }
        )
    return out


def get_cart_items(user_id: int) -> List[Dict[str, Any]]:
    doc = _coll().find_one({"user_id": int(user_id)})
    if not doc or not doc.get("items"):
        return []
    return _enrich_items(doc["items"])


def _save_items(user_id: int, items: List[Dict]) -> None:
    _coll().update_one(
        {"user_id": int(user_id)},
        {"$set": {"items": items, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


def add_to_cart(user_id: int, item_id: int, quantity: int = 1) -> bool:
    if not food_repository.fetch_food_item_by_legacy_mysql_id(item_id):
        return False
    doc = _coll().find_one({"user_id": int(user_id)}) or {"items": []}
    items = list(doc.get("items") or [])
    found = False
    for it in items:
        if int(it["item_id"]) == int(item_id):
            it["quantity"] = int(it.get("quantity", 0)) + int(quantity)
            found = True
            break
    if not found:
        food = food_repository.fetch_food_item_by_legacy_mysql_id(item_id)
        items.append(
            {
                "item_id": int(item_id),
                "name": food["name"],
                "price": float(food["price"]),
                "quantity": int(quantity),
            }
        )
    _save_items(user_id, items)
    return True


def update_cart_quantity(user_id: int, item_id: int, quantity: int) -> bool:
    doc = _coll().find_one({"user_id": int(user_id)})
    items = list((doc or {}).get("items") or [])
    if quantity <= 0:
        items = [it for it in items if int(it["item_id"]) != int(item_id)]
    else:
        updated = False
        for it in items:
            if int(it["item_id"]) == int(item_id):
                it["quantity"] = int(quantity)
                updated = True
        if not updated:
            return False
    _save_items(user_id, items)
    return True


def remove_from_cart(user_id: int, item_id: int) -> bool:
    return update_cart_quantity(user_id, item_id, 0)


def clear_cart(user_id: int) -> bool:
    _coll().update_one(
        {"user_id": int(user_id)},
        {"$set": {"items": [], "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )
    return True


def get_raw_items_for_order(user_id: int) -> List[Dict[str, Any]]:
    doc = _coll().find_one({"user_id": int(user_id)})
    return list((doc or {}).get("items") or [])
