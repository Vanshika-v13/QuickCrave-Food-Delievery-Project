"""user_addresses collection — PyMongo only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from repositories.mongo_client import get_collection, next_sequence, seed_sequence


def _coll():
    return get_collection("user_addresses")


def ensure_indexes():
    c = _coll()
    c.create_index("address_id", unique=True)
    c.create_index("user_id")
    c.create_index([("user_id", 1), ("is_default", 1)])


def _to_api(doc: Optional[Dict]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    return {
        "id": doc["address_id"],
        "user_id": doc["user_id"],
        "name": doc.get("name"),
        "phone": doc.get("phone"),
        "address_line": doc.get("address_line"),
        "city": doc.get("city"),
        "state": doc.get("state"),
        "pincode": doc.get("pincode"),
        "is_default": bool(doc.get("is_default", False)),
        "latitude": doc.get("latitude"),
        "longitude": doc.get("longitude"),
        "created_at": doc.get("created_at"),
    }


def find_by_address_id(address_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    doc = _coll().find_one({"address_id": int(address_id), "user_id": int(user_id)})
    return _to_api(doc)


def find_map_by_address_user_pairs(
    pairs: List[tuple],
) -> Dict[tuple, Dict[str, Any]]:
    if not pairs:
        return {}
    or_clauses = [
        {"address_id": int(aid), "user_id": int(uid)} for aid, uid in pairs
    ]
    cursor = _coll().find(
        {"$or": or_clauses},
        {
            "_id": 0,
            "address_id": 1,
            "user_id": 1,
            "name": 1,
            "phone": 1,
            "address_line": 1,
            "city": 1,
            "pincode": 1,
        },
    )
    out: Dict[tuple, Dict[str, Any]] = {}
    for doc in cursor:
        api = _to_api(doc)
        if api:
            out[(int(api["id"]), int(api["user_id"]))] = api
    return out


def list_by_user(user_id: int) -> List[Dict[str, Any]]:
    cursor = _coll().find({"user_id": int(user_id)}).sort("created_at", -1)
    return [_to_api(d) for d in cursor if d]


def get_default_or_first(user_id: int) -> Optional[Dict[str, Any]]:
    doc = _coll().find_one({"user_id": int(user_id), "is_default": True})
    if not doc:
        doc = _coll().find_one({"user_id": int(user_id)}, sort=[("address_id", 1)])
    return _to_api(doc)


def add_address(
    user_id, name, phone, address_line, city, state, pincode, is_default=False, latitude=None, longitude=None
):
    coll = _coll()
    existing = coll.find_one(
        {"user_id": int(user_id), "address_line": address_line, "pincode": pincode}
    )
    if existing:
        return int(existing["address_id"])
    if coll.count_documents({"user_id": int(user_id)}) == 0:
        is_default = True
    if is_default:
        coll.update_many({"user_id": int(user_id)}, {"$set": {"is_default": False}})
    lat_val = lng_val = None
    if latitude is not None and longitude is not None:
        try:
            lat_val = float(latitude)
            lng_val = float(longitude)
            if not (-90.0 <= lat_val <= 90.0 and -180.0 <= lng_val <= 180.0):
                lat_val = lng_val = None
        except (TypeError, ValueError):
            lat_val = lng_val = None
    address_id = next_sequence("address_id")
    now = datetime.now(timezone.utc)
    coll.insert_one(
        {
            "address_id": address_id,
            "user_id": int(user_id),
            "name": name,
            "phone": phone,
            "address_line": address_line,
            "city": city,
            "state": state,
            "pincode": pincode,
            "is_default": bool(is_default),
            "latitude": lat_val,
            "longitude": lng_val,
            "created_at": now,
        }
    )
    return address_id


def add_user_address(user_id: int, data: dict) -> Optional[int]:
    return add_address(
        user_id,
        data.get("name"),
        data.get("phone"),
        data.get("address_line"),
        data.get("city"),
        data.get("state"),
        data.get("pincode"),
        bool(data.get("is_default", False)),
    )


def delete_address(user_id: int, address_id: int) -> bool:
    coll = _coll()
    doc = coll.find_one({"address_id": int(address_id), "user_id": int(user_id)})
    if not doc:
        return False
    was_default = doc.get("is_default")
    coll.delete_one({"address_id": int(address_id), "user_id": int(user_id)})
    if was_default:
        another = coll.find_one({"user_id": int(user_id)}, sort=[("address_id", 1)])
        if another:
            coll.update_one(
                {"address_id": another["address_id"]},
                {"$set": {"is_default": True}},
            )
    return True


def set_default_address(address_id: int, user_id: int) -> bool:
    coll = _coll()
    if not coll.find_one({"address_id": int(address_id), "user_id": int(user_id)}):
        return False
    coll.update_many({"user_id": int(user_id)}, {"$set": {"is_default": False}})
    coll.update_one(
        {"address_id": int(address_id), "user_id": int(user_id)},
        {"$set": {"is_default": True}},
    )
    return True


def update_user_address(address_id: int, user_id: int, data: dict) -> bool:
    coll = _coll()
    if not coll.find_one({"address_id": int(address_id), "user_id": int(user_id)}):
        return False
    if data.get("is_default"):
        coll.update_many({"user_id": int(user_id)}, {"$set": {"is_default": False}})
    allowed = ("name", "phone", "address_line", "city", "state", "pincode", "is_default")
    updates = {k: data[k] for k in allowed if k in data}
    if not updates:
        return True
    coll.update_one(
        {"address_id": int(address_id), "user_id": int(user_id)},
        {"$set": updates},
    )
    return True


def update_coordinates(address_id: int, user_id: int, lat: float, lng: float) -> None:
    _coll().update_one(
        {"address_id": int(address_id), "user_id": int(user_id)},
        {"$set": {"latitude": lat, "longitude": lng}},
    )


def upsert_from_mysql(row: Dict[str, Any]) -> None:
    aid = int(row["id"])
    seed_sequence("address_id", aid)
    _coll().update_one(
        {"address_id": aid},
        {
            "$set": {
                "address_id": aid,
                "user_id": int(row["user_id"]),
                "name": row.get("name"),
                "phone": row.get("phone"),
                "address_line": row.get("address_line"),
                "city": row.get("city"),
                "state": row.get("state"),
                "pincode": row.get("pincode"),
                "is_default": bool(row.get("is_default", False)),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "created_at": row.get("created_at") or datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
