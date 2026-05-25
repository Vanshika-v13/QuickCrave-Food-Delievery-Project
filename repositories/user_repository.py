"""users collection — PyMongo only."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from repositories.mongo_client import get_collection, next_sequence, seed_sequence

logger = logging.getLogger(__name__)


def _coll():
    return get_collection("users")


def ensure_indexes():
    c = _coll()
    c.create_index("user_id", unique=True)
    c.create_index("email", unique=True)
    c.create_index("roles")
    c.create_index([("role", 1), ("rider_status", 1), ("is_active", 1)])
    c.create_index("online")
    c.create_index([("role", 1), ("online", 1), ("is_active", 1)])


def _parse_roles(val) -> List[str]:
    if not val:
        return ["customer"]
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        try:
            return json.loads(val)
        except Exception:
            return ["customer"]
    return ["customer"]


def _to_api(doc: Optional[Dict]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    roles = _parse_roles(doc.get("roles"))
    return {
        "id": doc["user_id"],
        "name": doc.get("name"),
        "email": doc.get("email"),
        "password": doc.get("password"),
        "google_id": doc.get("google_id"),
        "profile_pic": doc.get("profile_pic"),
        "role": doc.get("role") or (roles[0] if roles else "customer"),
        "roles": roles,
        "is_active": doc.get("is_active", 1),
        "phone": doc.get("phone"),
        "vehicle_type": doc.get("vehicle_type"),
        "license_number": doc.get("license_number"),
        "rider_status": doc.get("rider_status"),
        "online": bool(doc.get("online", False)),
        "last_heartbeat": doc.get("last_heartbeat"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def find_by_email(email: str) -> Optional[Dict[str, Any]]:
    doc = _coll().find_one({"email": email})
    return _to_api(doc)


def find_by_user_id(user_id: int) -> Optional[Dict[str, Any]]:
    return get_rider_by_id_safe(user_id)


def _user_id_lookup_values(raw_id: Union[int, str, None]) -> List[Any]:
    """Build MongoDB user_id match values for int and string storage."""
    if raw_id is None:
        return []
    values: List[Any] = []
    if isinstance(raw_id, int):
        values.append(raw_id)
        values.append(str(raw_id))
        return values
    s = str(raw_id).strip()
    if not s:
        return []
    if s.isdigit():
        n = int(s)
        values.extend([n, s])
    else:
        values.append(s)
    return values


def get_rider_by_id_safe(rider_id: Union[int, str, None]) -> Optional[Dict[str, Any]]:
    """
    Resolve rider by user_id whether stored as int (5) or string ("5").
  """
    lookup = _user_id_lookup_values(rider_id)
    if not lookup:
        return None
    doc = _coll().find_one({"user_id": {"$in": lookup}})
    api = _to_api(doc)
    logger.info(
        "[ADMIN_RIDER_LOOKUP] rider_id=%r found=%s name=%s",
        rider_id,
        bool(api),
        (api or {}).get("name"),
    )
    return api


_RIDER_MAP_PROJECTION = {
    "_id": 0,
    "user_id": 1,
    "name": 1,
    "email": 1,
    "phone": 1,
    "profile_pic": 1,
    "role": 1,
    "roles": 1,
    "is_active": 1,
    "rider_status": 1,
    "online": 1,
    "vehicle_type": 1,
    "license_number": 1,
    "created_at": 1,
}


def find_map_by_user_ids(user_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not user_ids:
        return {}
    lookup_values: List[Any] = []
    for uid in user_ids:
        lookup_values.extend(_user_id_lookup_values(uid))
    lookup_values = list({v for v in lookup_values})
    cursor = _coll().find(
        {"user_id": {"$in": lookup_values}},
        _RIDER_MAP_PROJECTION,
    )
    out: Dict[int, Dict[str, Any]] = {}
    for doc in cursor:
        api = _to_api(doc)
        if api:
            out[int(api["id"])] = api
    return out


def list_admin_users(page: int = 1, limit: int = 20) -> Dict[str, Any]:
    page = max(1, int(page))
    limit = min(100, max(1, int(limit)))
    skip = (page - 1) * limit
    query = {
        "$or": [
            {"role": {"$in": ["customer", "rider"]}},
            {"roles": {"$in": ["customer", "rider"]}},
        ]
    }
    coll = _coll()
    total = coll.count_documents(query)
    cursor = (
        coll.find(
            query,
            {
                "_id": 0,
                "user_id": 1,
                "name": 1,
                "email": 1,
                "phone": 1,
                "role": 1,
                "roles": 1,
                "is_active": 1,
                "rider_status": 1,
                "created_at": 1,
            },
        )
        .sort("created_at", -1)
        .skip(skip)
        .limit(limit)
    )
    users = [_to_api(d) for d in cursor if d]
    pages = max(1, (total + limit - 1) // limit)
    return {"items": users, "total": total, "page": page, "limit": limit, "pages": pages}


def create_user(
    name, email, hashed_password=None, google_id=None, profile_pic=None, roles=None
) -> Optional[int]:
    if roles is None:
        roles = ["customer"]
    now = datetime.now(timezone.utc)
    user_id = next_sequence("user_id")
    doc = {
        "user_id": user_id,
        "name": name,
        "email": email,
        "password": hashed_password,
        "google_id": google_id,
        "profile_pic": profile_pic,
        "role": roles[0] if roles else "customer",
        "roles": roles,
        "is_active": 1,
        "rider_status": "offline",
        "created_at": now,
        "updated_at": now,
    }
    try:
        _coll().insert_one(doc)
        return user_id
    except Exception:
        return None


def update_user_google_info(user_id: int, google_id: str, profile_pic: str) -> bool:
    res = _coll().update_one(
        {"user_id": int(user_id)},
        {
            "$set": {
                "google_id": google_id,
                "profile_pic": profile_pic,
                "updated_at": datetime.now(timezone.utc),
            }
        },
    )
    return res.modified_count > 0


def create_rider_by_admin(
    name, email, phone, password_hash, vehicle_type, license_number, profile_pic=None
) -> Optional[int]:
    now = datetime.now(timezone.utc)
    user_id = next_sequence("user_id")
    doc = {
        "user_id": user_id,
        "name": name,
        "email": email,
        "phone": phone,
        "password": password_hash,
        "role": "rider",
        "roles": ["rider"],
        "vehicle_type": vehicle_type,
        "license_number": license_number,
        "profile_pic": profile_pic,
        "rider_status": "offline",
        "is_active": 1,
        "created_at": now,
        "updated_at": now,
    }
    try:
        _coll().insert_one(doc)
        return user_id
    except Exception:
        return None


def toggle_user_active(user_id: int, status: int) -> bool:
    res = _coll().update_one(
        {"user_id": int(user_id)},
        {"$set": {"is_active": int(status), "updated_at": datetime.now(timezone.utc)}},
    )
    return res.matched_count > 0


def update_rider_status(user_id: int, rider_status: str) -> bool:
    res = _coll().update_one(
        {"user_id": int(user_id)},
        {"$set": {"rider_status": rider_status, "updated_at": datetime.now(timezone.utc)}},
    )
    return res.matched_count > 0


def count_customers() -> int:
    return _coll().count_documents(
        {"$or": [{"role": "customer"}, {"roles": "customer"}, {"roles": {"$in": ["customer"]}}]}
    )


def count_riders() -> int:
    return _coll().count_documents(
        {"$or": [{"role": "rider"}, {"roles": "rider"}, {"roles": {"$in": ["rider"]}}]}
    )


def _active_orders_count_by_rider() -> Dict[int, int]:
    from repositories import order_repository

    return order_repository.count_active_orders_grouped_by_rider()


def set_rider_online(rider_id: int, online: bool) -> bool:
    now = datetime.now(timezone.utc)
    res = _coll().update_one(
        {"user_id": int(rider_id)},
        {
            "$set": {
                "online": bool(online),
                "last_heartbeat": now,
                "updated_at": now,
                "rider_status": "available" if online else "offline",
            }
        },
    )
    return res.matched_count > 0


def touch_rider_heartbeat(rider_id: int) -> None:
    now = datetime.now(timezone.utc)
    _coll().update_one(
        {"user_id": int(rider_id)},
        {"$set": {"last_heartbeat": now, "updated_at": now}},
    )


def is_rider_online_db(rider_id: int) -> bool:
    doc = _coll().find_one({"user_id": int(rider_id)}, {"online": 1, "is_active": 1})
    if not doc or not doc.get("is_active", 1):
        return False
    return bool(doc.get("online"))


def find_all_riders() -> List[Dict[str, Any]]:
    from core.perf import timed_mongo

    with timed_mongo("admin riders list"):
        cursor = _coll().find(
            {"$or": [{"role": "rider"}, {"roles": {"$in": ["rider"]}}]},
            {
                "_id": 0,
                "user_id": 1,
                "name": 1,
                "email": 1,
                "phone": 1,
                "vehicle_type": 1,
                "license_number": 1,
                "rider_status": 1,
                "is_active": 1,
                "profile_pic": 1,
                "created_at": 1,
            },
        ).sort("created_at", -1)

    from repositories.order_repository import log_rider_availability
    from services.rider_status import build_rider_availability_payload, get_rider_work_status

    active_by_rider = _active_orders_count_by_rider()
    results = []
    stale_busy_ids: List[int] = []
    stale_available_ids: List[int] = []
    for doc in cursor:
        uid = int(doc["user_id"])
        active_orders_count = active_by_rider.get(uid, 0)
        stored_status = (doc.get("rider_status") or "offline").lower()
        name = doc.get("name") or "Unnamed"
        computed_status = get_rider_work_status(active_orders_count)
        if doc.get("is_active", 1):
            if computed_status == "available" and stored_status == "busy":
                stale_busy_ids.append(uid)
            elif computed_status == "busy" and stored_status == "available":
                stale_available_ids.append(uid)
        log_rider_availability(
            uid,
            active_orders_count,
            computed_status == "available",
        )
        availability = build_rider_availability_payload(uid, name, active_orders_count)
        results.append(
            {
                "id": uid,
                "name": name,
                "email": doc.get("email"),
                "phone": doc.get("phone") or "N/A",
                "vehicle_type": doc.get("vehicle_type") or "Not Set",
                "license_number": doc.get("license_number") or "N/A",
                **availability,
                "is_active": int(doc.get("is_active") or 0),
                "profile_pic": doc.get("profile_pic"),
                "created_at": _to_api(doc).get("created_at").isoformat()
                if hasattr(doc.get("created_at"), "isoformat")
                else str(doc.get("created_at")),
            }
        )
    now = datetime.now(timezone.utc)
    if stale_busy_ids:
        _coll().update_many(
            {"user_id": {"$in": stale_busy_ids}},
            {"$set": {"rider_status": "available", "updated_at": now}},
        )
    if stale_available_ids:
        _coll().update_many(
            {"user_id": {"$in": stale_available_ids}},
            {"$set": {"rider_status": "busy", "updated_at": now}},
        )
    return results


def upsert_from_mysql(row: Dict[str, Any]) -> None:
    uid = int(row["id"])
    seed_sequence("user_id", uid)
    roles = _parse_roles(row.get("roles"))
    now = datetime.now(timezone.utc)
    doc = {
        "user_id": uid,
        "name": row.get("name"),
        "email": row.get("email"),
        "password": row.get("password"),
        "google_id": row.get("google_id"),
        "profile_pic": row.get("profile_pic"),
        "role": row.get("role") or (roles[0] if roles else "customer"),
        "roles": roles,
        "is_active": row.get("is_active", 1),
        "phone": row.get("phone"),
        "vehicle_type": row.get("vehicle_type"),
        "license_number": row.get("license_number"),
        "rider_status": row.get("rider_status") or "offline",
        "created_at": row.get("created_at") or now,
        "updated_at": row.get("updated_at") or now,
    }
    _coll().update_one({"user_id": uid}, {"$set": doc}, upsert=True)
