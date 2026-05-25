"""food_items collection — PyMongo only."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from repositories.mongo_client import get_collection, read_with_retry, seed_sequence


def _coll():
    return get_collection("food_items")


def ensure_indexes():
    c = _coll()
    c.create_index("name")
    c.create_index("category")
    c.create_index("item_id")
    c.create_index("is_available")
    c.create_index("legacy_mysql_id", unique=True, sparse=True)


def doc_to_row(doc: Dict[str, Any]) -> Dict[str, Any]:
    legacy_id = doc.get("legacy_mysql_id") or doc.get("item_id")
    return {
        "item_id": int(legacy_id) if legacy_id is not None else None,
        "name": doc.get("name", ""),
        "price": float(doc.get("price") or 0),
        "description": doc.get("description") or "",
        "image_url": doc.get("image_url"),
        "rating": float(doc.get("rating") or 4.5),
        "tag": doc.get("category") or doc.get("tag") or "General",
    }


def _fetch_all_food_items_query(include_unavailable: bool) -> List[Dict[str, Any]]:
    query: Dict[str, Any] = {}
    if not include_unavailable:
        query["$or"] = [{"is_available": True}, {"is_available": {"$exists": False}}]
    rows = []
    for doc in _coll().find(query).sort("legacy_mysql_id", 1):
        row = doc_to_row(doc)
        if row.get("item_id") is not None:
            rows.append(row)
    return rows


def fetch_all_food_items(include_unavailable: bool = False) -> List[Dict[str, Any]]:
    """Menu catalog read — retries on ReplicaSetNoPrimary / server selection timeouts."""
    return read_with_retry(
        "MENU_FETCH",
        lambda: _fetch_all_food_items_query(include_unavailable),
        max_attempts=int(os.getenv("MONGODB_MENU_READ_RETRIES", "2")),
    )


def fetch_food_item_by_name(name: str) -> Optional[Dict[str, Any]]:
    raw = (name or "").strip()
    if not raw:
        return None
    availability = {"$or": [{"is_available": True}, {"is_available": {"$exists": False}}]}
    exact = _coll().find_one(
        {**availability, "name": {"$regex": f"^{re.escape(raw)}$", "$options": "i"}}
    )
    if exact:
        row = doc_to_row(exact)
        return {"item_id": row["item_id"], "name": row["name"], "price": row["price"]}
    pattern = re.compile(re.escape(raw.lower()), re.IGNORECASE)
    candidates = list(_coll().find({**availability, "name": pattern}))
    if not candidates:
        return None
    candidates.sort(key=lambda d: len((d.get("name") or "")))
    row = doc_to_row(candidates[0])
    return {"item_id": row["item_id"], "name": row["name"], "price": row["price"]}


def fetch_food_item_by_legacy_mysql_id(item_id: int) -> Optional[Dict[str, Any]]:
    doc = _coll().find_one({"legacy_mysql_id": int(item_id)}) or _coll().find_one(
        {"item_id": int(item_id)}
    )
    return doc_to_row(doc) if doc else None


def fetch_map_by_legacy_ids(item_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not item_ids:
        return {}
    ids = [int(i) for i in item_ids]
    cursor = _coll().find(
        {
            "$or": [
                {"legacy_mysql_id": {"$in": ids}},
                {"item_id": {"$in": ids}},
            ]
        },
        {
            "_id": 0,
            "legacy_mysql_id": 1,
            "item_id": 1,
            "name": 1,
            "price": 1,
            "image_url": 1,
        },
    )
    out: Dict[int, Dict[str, Any]] = {}
    for doc in cursor:
        row = doc_to_row(doc)
        key = row.get("item_id")
        if key is not None:
            out[int(key)] = row
    return out


def fetch_item_name_by_id(item_id: int) -> Optional[str]:
    row = fetch_food_item_by_legacy_mysql_id(item_id)
    return row["name"] if row else None


def upsert_from_row(row: Dict[str, Any]) -> None:
    item_id = int(row["item_id"])
    seed_sequence("food_item_id", item_id)
    now = datetime.now(timezone.utc)
    doc = {
        "legacy_mysql_id": item_id,
        "item_id": item_id,
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "price": float(row.get("price") or 0),
        "category": row.get("tag") or "General",
        "image_url": row.get("image_url"),
        "rating": float(row.get("rating") or 4.5),
        "is_available": True,
        "updated_at": now,
    }
    _coll().update_one(
        {"legacy_mysql_id": item_id},
        {"$set": doc, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
