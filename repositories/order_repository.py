"""orders, order_items (embedded), order_tracking collections."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.eta import FALLBACK_ETA, TOTAL_DELIVERY_MINUTES, calculate_remaining_delivery_time
from core.geocode import geocode_address_snapshot
from order_states import ACTIVE_STATES, HISTORY_STATES
from services.order_lifecycle import ASSIGNABLE_STATUSES, normalize_status_internal
from services.rider_status import (
    RIDER_WORKLOAD_STATUSES,
    build_rider_availability_payload,
    get_rider_work_status,
)
from repositories import address_repository, cart_repository, food_repository, user_repository
from repositories.mongo_client import get_collection, next_sequence, seed_sequence

logger = logging.getLogger(__name__)


def _coerce_rider_id(value) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    s = str(value).strip()
    if s.isdigit():
        return int(s)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

TERMINAL = ("DELIVERED", "CANCELLED", "DELIVERED_SUCCESS")
_ASSIGNED_STATUS_VALUES = ("ASSIGNED", "ACCEPTED", "ORDER_ACCEPTED")
_DELIVERY_ACTIVE_STATUSES = (
    "PICKED_UP",
    "ON_WAY",
    "ARRIVING",
    "ORDER_PICKED_UP",
    "OUT_FOR_DELIVERY",
    "NEAR_CUSTOMER_LOCATION",
    "ACCEPTED",
)


def _orders():
    return get_collection("orders")


def _tracking():
    return get_collection("order_tracking")


def ensure_indexes():
    o = _orders()
    o.create_index("order_id", unique=True)
    o.create_index("user_id")
    o.create_index("rider_id")
    o.create_index("status")
    o.create_index("created_at")
    o.create_index([("status", 1), ("created_at", -1)])
    o.create_index([("rider_id", 1), ("status", 1)])
    t = _tracking()
    t.create_index("order_id")
    t.create_index("created_at")
    t.create_index([("order_id", 1), ("created_at", 1)])


def _iso(val):
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def find_by_order_id(order_id: int) -> Optional[Dict[str, Any]]:
    return _orders().find_one({"order_id": int(order_id)})


def order_doc_to_row(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "order_id": doc["order_id"],
        "user_id": doc["user_id"],
        "address_id": doc.get("address_id"),
        "subtotal": doc.get("subtotal"),
        "delivery_fee": doc.get("delivery_fee", 40),
        "total_amount": doc.get("total_amount"),
        "address": doc.get("address"),
        "payment_method": doc.get("payment_method", "COD"),
        "payment_status": doc.get("payment_status", "PENDING"),
        "status": normalize_status_internal(doc.get("status", "PLACED")),
        "created_at": doc.get("created_at"),
        "restaurant_lat": doc.get("restaurant_lat"),
        "restaurant_lng": doc.get("restaurant_lng"),
        "user_lat": doc.get("user_lat"),
        "user_lng": doc.get("user_lng"),
        "rider_id": doc.get("rider_id"),
        "version": doc.get("version", 1),
        "assigned_at": doc.get("assigned_at"),
        "accepted_at": doc.get("accepted_at"),
        "picked_up_at": doc.get("picked_up_at"),
        "delivered_at": doc.get("delivered_at"),
    }


def build_items_with_food_images(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for item in doc.get("items") or []:
        food = food_repository.fetch_food_item_by_legacy_mysql_id(item["item_id"])
        rows.append(
            {
                "item_id": item["item_id"],
                "quantity": item.get("quantity"),
                "price": item.get("price"),
                "unit_price": item.get("price"),
                "name": food["name"] if food else item.get("name", "Unknown"),
                "food_image": food.get("image_url") if food else None,
            }
        )
    return rows


def build_status_object(order_id: int) -> Optional[Dict[str, Any]]:
    doc = find_by_order_id(order_id)
    if not doc:
        return None
    history = list(doc.get("tracking") or [])
    if not history:
        track_cursor = _tracking().find({"order_id": int(order_id)}).sort("created_at", 1)
        history = list(track_cursor)

    current_status = normalize_status_internal(doc.get("status", "PLACED"))
    order_created_at = doc.get("created_at")
    try:
        eta_data = calculate_remaining_delivery_time({"status": current_status})
    except Exception:
        eta_data = dict(FALLBACK_ETA)

    latest = history[-1] if history else {}
    normalized_history = [
        {
            "status": normalize_status_internal(h.get("status")),
            "timestamp": _iso(h.get("created_at") or h.get("timestamp")),
        }
        for h in history
    ]
    return {
        "current_status": current_status,
        "last_updated": _iso(latest.get("created_at") or latest.get("timestamp") or order_created_at),
        "order_created_at": _iso(order_created_at),
        "estimated_total_minutes": TOTAL_DELIVERY_MINUTES,
        "remaining_minutes": eta_data["remaining_minutes"],
        "remaining_seconds": eta_data["remaining_seconds"],
        "eta_text": eta_data["eta_text"],
        "status_history": normalized_history,
        "payment_status": doc.get("payment_status"),
        "version": doc.get("version", 1),
        "lat": latest.get("lat"),
        "lng": latest.get("lng"),
    }


def _append_tracking(
    order_id: int,
    status: str,
    old_status: str,
    actor: str = "SYSTEM",
    lat=None,
    lng=None,
) -> None:
    now = datetime.now(timezone.utc)
    entry = {
        "status": status,
        "old_status": old_status,
        "actor": actor,
        "lat": lat,
        "lng": lng,
        "created_at": now,
        "timestamp": now,
    }
    _orders().update_one({"order_id": int(order_id)}, {"$push": {"tracking": entry}})
    _tracking().insert_one({"order_id": int(order_id), **entry})


def _clear_rider_redis(rider_id: int) -> None:
    try:
        import redis
        import os

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_timeout=0.3,
        )
        r.delete(f"rider_last_known:{rider_id}")
        r.delete(f"rider_throttle:{rider_id}")
    except Exception:
        pass


def insert_order_tracking(
    order_id,
    status,
    actor="SYSTEM",
    lat=None,
    lng=None,
    expected_previous_status=None,
) -> bool:
    if lat is not None and lng is not None:
        try:
            lat_f, lng_f = float(lat), float(lng)
            if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
                lat, lng = None, None
        except (TypeError, ValueError):
            lat, lng = None, None

    doc = find_by_order_id(order_id)
    if not doc:
        return False
    old_status = doc.get("status")
    status = normalize_status_internal(status)
    old_norm = normalize_status_internal(old_status)
    if old_norm == status:
        return True

    now = datetime.now(timezone.utc)
    updates: Dict[str, Any] = {
        "status": status,
        "version": int(doc.get("version", 1)) + 1,
        "updated_at": now,
    }
    if status.upper() == "DELIVERED":
        if doc.get("payment_method", "COD").upper() == "COD":
            updates["payment_status"] = "PAID"
        updates["delivered_at"] = now
    if status.upper() in TERMINAL and doc.get("rider_id"):
        user_repository.update_rider_status(doc["rider_id"], "available")
        _clear_rider_redis(doc["rider_id"])

    _orders().update_one({"order_id": int(order_id)}, {"$set": updates})
    _append_tracking(order_id, status, old_status, actor, lat, lng)
    logger.info(f"[STATUS][ORDER:{order_id}] {old_status} -> {status} by {actor}")
    return True


def place_order_in_db(
    user_id,
    address_id,
    items=None,
    payment_method="COD",
    restaurant_lat=None,
    restaurant_lng=None,
    clear_cart=True,
):
    if items is not None:
        processed = []
        for it in items:
            iid = it.get("item_id") or it.get("id")
            food = food_repository.fetch_food_item_by_legacy_mysql_id(iid)
            if food:
                processed.append(
                    {
                        "item_id": int(iid),
                        "quantity": it.get("quantity", 1),
                        "price": float(food["price"]),
                        "name": food["name"],
                    }
                )
        items = processed
    else:
        raw = cart_repository.get_raw_items_for_order(user_id)
        items = [
            {
                "item_id": int(it["item_id"]),
                "quantity": int(it.get("quantity", 1)),
                "price": float(it.get("price", 0)),
                "name": it.get("name"),
            }
            for it in raw
        ]

    if not items:
        raise Exception("Cannot place order: Cart is empty. Please add items to your cart.")

    subtotal = round(sum(max(1, int(i["quantity"])) * float(i["price"]) for i in items), 2)
    delivery_fee = 40.0
    total_amount = subtotal + delivery_fee

    addr = address_repository.find_by_address_id(address_id, user_id)
    if not addr:
        raise Exception(f"Address with ID {address_id} not found for user {user_id}")

    address_string = (
        f"{addr['name']}, {addr['address_line']}, {addr['city']}, {addr['state']} - {addr['pincode']}"
    )
    user_lat_snap = user_lng_snap = None
    if addr.get("latitude") is not None and addr.get("longitude") is not None:
        try:
            user_lat_snap = float(addr["latitude"])
            user_lng_snap = float(addr["longitude"])
        except (TypeError, ValueError):
            pass
    if user_lat_snap is None or user_lng_snap is None:
        geo_lat, geo_lng = geocode_address_snapshot(addr)
        if geo_lat is not None and geo_lng is not None:
            user_lat_snap, user_lng_snap = geo_lat, geo_lng
            address_repository.update_coordinates(address_id, user_id, geo_lat, geo_lng)

    if user_lat_snap is None or user_lng_snap is None:
        raise Exception(
            "DELIVERY_COORDS_INVALID: Your delivery address needs valid coordinates before placing an order."
        )

    order_id = next_sequence("order_id")
    now = datetime.now(timezone.utc)
    payment_status = "PAID" if payment_method.upper() == "ONLINE" else "PENDING"
    order_items = []
    for item in items:
        qty = max(1, int(item["quantity"]))
        unit_price = float(item["price"])
        order_items.append(
            {
                "item_id": int(item["item_id"]),
                "name": item.get("name"),
                "quantity": qty,
                "price": unit_price,
                "total_price": round(unit_price * qty, 2),
            }
        )

    doc = {
        "order_id": order_id,
        "user_id": int(user_id),
        "address_id": int(address_id),
        "address": address_string,
        "subtotal": subtotal,
        "delivery_fee": delivery_fee,
        "total_amount": total_amount,
        "payment_method": payment_method,
        "payment_status": payment_status,
        "status": "PLACED",
        "restaurant_lat": restaurant_lat,
        "restaurant_lng": restaurant_lng,
        "user_lat": user_lat_snap,
        "user_lng": user_lng_snap,
        "rider_id": None,
        "items": order_items,
        "tracking": [
            {
                "status": "PLACED",
                "old_status": None,
                "actor": "SYSTEM",
                "created_at": now,
                "timestamp": now,
            }
        ],
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    _orders().insert_one(doc)
    _tracking().insert_one(
        {"order_id": order_id, "status": "PLACED", "actor": "SYSTEM", "created_at": now}
    )
    if clear_cart:
        cart_repository.clear_cart(user_id)
    return order_id


def validate_order_owner(order_id: int, user_id: int) -> str:
    doc = find_by_order_id(order_id)
    if not doc:
        return "ORDER_NOT_FOUND"
    if doc["user_id"] != int(user_id):
        return "ACCESS_DENIED"
    return "ALLOWED"


def _normalize_status_strict(status):
    return normalize_status_internal(status)


def delete_customer_order_placed(order_id: int, user_id: int) -> str:
    doc = find_by_order_id(order_id)
    if not doc:
        return "NOT_FOUND"
    if doc["user_id"] != int(user_id):
        return "FORBIDDEN"
    if _normalize_status_strict(doc.get("status")) != "PLACED":
        return "NOT_DELETABLE"
    if doc.get("rider_id") is not None:
        return "NOT_DELETABLE"
    _orders().delete_one({"order_id": int(order_id)})
    _tracking().delete_many({"order_id": int(order_id)})
    get_collection("admin_audit_log").delete_many({"order_id": int(order_id)})
    return "DELETED"


def assign_rider_to_order(order_id, rider_id, actor="ADMIN", admin_id=None):
    rider = user_repository.find_by_user_id(rider_id)
    if not rider:
        return "invalid_rider"
    roles = rider.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if "rider" not in roles and rider.get("role") != "rider":
        return "invalid_rider"
    if not rider.get("is_active", 1):
        return "invalid_rider"
    active_count = count_active_orders_for_rider(rider_id)
    if active_count > 0:
        log_rider_availability(rider_id, active_count, False)
        return "rider_busy"
    log_rider_availability(rider_id, 0, True)
    doc = find_by_order_id(order_id)
    if not doc:
        return "order_not_found"
    if doc.get("rider_id") is not None:
        return "already_assigned"
    norm_status = normalize_status_internal(doc.get("status"))
    if norm_status not in ASSIGNABLE_STATUSES:
        return "order_not_ready"
    status_before = normalize_status_internal(doc.get("status"))
    now = datetime.now(timezone.utc)
    res = _orders().update_one(
        {"order_id": int(order_id), "rider_id": None},
        {
            "$set": {
                "rider_id": int(rider_id),
                "status": "ASSIGNED",
                "assigned_at": now,
                "version": int(doc.get("version", 1)) + 1,
                "updated_at": now,
            }
        },
    )
    if res.modified_count == 0:
        return "already_assigned"
    _append_tracking(order_id, "ASSIGNED", status_before, actor)
    user_repository.update_rider_status(rider_id, "busy")
    logger.info("[RIDER_ASSIGN] Assigned rider %s to order %s", rider_id, order_id)
    if admin_id:
        from repositories import admin_repository

        admin_repository.log_admin_action(
            admin_id, "RIDER_ASSIGNED", order_id, f"Rider {rider_id} assigned via {actor}"
        )
    return "assigned"


def accept_assigned_order(order_id: int, rider_id: int):
    doc = find_by_order_id(order_id)
    if not doc:
        return "order_not_found"
    if doc.get("rider_id") != int(rider_id):
        return "not_assigned_to_rider"
    if doc.get("accepted_at"):
        return "already_accepted"
    if normalize_status_internal(doc.get("status")) != "ASSIGNED":
        return "invalid_order_status"
    now = datetime.now(timezone.utc)
    _orders().update_one(
        {"order_id": int(order_id)},
        {
            "$set": {
                "accepted_at": now,
                "version": int(doc.get("version", 1)) + 1,
                "updated_at": now,
            }
        },
    )
    logger.info(
        "[RIDER_ASSIGN] rider %s accepted order %s (status remains ASSIGNED)",
        rider_id,
        order_id,
    )
    return "accepted"


def get_order_status_for_user(order_id: int, user_id: int) -> Optional[str]:
    doc = find_by_order_id(order_id)
    if not doc or doc["user_id"] != int(user_id):
        return None
    return doc.get("status")


def get_user_orders(user_id: int) -> List[Dict[str, Any]]:
    cursor = _orders().find({"user_id": int(user_id)}).sort("created_at", -1)
    return [
        {
            "order_id": d["order_id"],
            "status": d.get("status"),
            "created_at": d.get("created_at"),
            "total_amount": d.get("total_amount"),
        }
        for d in cursor
    ]


def list_all_order_ids() -> List[int]:
    return [d["order_id"] for d in _orders().find({}, {"order_id": 1}).sort("created_at", -1)]


def list_order_ids_by_rider_and_status(rider_id: int, statuses: tuple) -> List[int]:
    return [
        d["order_id"]
        for d in _orders().find({"rider_id": int(rider_id), "status": {"$in": list(statuses)}}).sort(
            "created_at", -1
        )
    ]


def list_available_order_ids_for_rider(rider_id: int) -> List[int]:
    """ASSIGNED to this rider, not yet accepted."""
    cursor = _orders().find(
        {
            "rider_id": int(rider_id),
            "status": {"$in": list(_ASSIGNED_STATUS_VALUES)},
            "$or": [{"accepted_at": None}, {"accepted_at": {"$exists": False}}],
        },
        {"order_id": 1},
    ).sort("created_at", -1)
    return [d["order_id"] for d in cursor]


def list_active_delivery_order_ids_for_rider(rider_id: int) -> List[int]:
    """Accepted ASSIGNED or in delivery pipeline."""
    cursor = _orders().find(
        {
            "rider_id": int(rider_id),
            "status": {"$nin": list(TERMINAL)},
            "$or": [
                {
                    "status": {"$in": list(_ASSIGNED_STATUS_VALUES)},
                    "accepted_at": {"$exists": True, "$ne": None},
                },
                {"status": {"$in": list(_DELIVERY_ACTIVE_STATUSES)}},
            ],
        },
        {"order_id": 1},
    ).sort("created_at", -1)
    return [d["order_id"] for d in cursor]


def _rider_workload_order_filter(rider_id: int | None = None) -> Dict[str, Any]:
    filt: Dict[str, Any] = {
        "rider_id": {"$ne": None, "$exists": True},
        "status": {"$in": list(RIDER_WORKLOAD_STATUSES)},
    }
    if rider_id is not None:
        filt["rider_id"] = int(rider_id)
    return filt


def count_active_orders_for_rider(rider_id: int) -> int:
    return _orders().count_documents(_rider_workload_order_filter(rider_id))


def count_active_orders_grouped_by_rider() -> Dict[int, int]:
    pipeline = [
        {"$match": _rider_workload_order_filter()},
        {"$group": {"_id": "$rider_id", "count": {"$sum": 1}}},
    ]
    return {int(r["_id"]): int(r["count"]) for r in _orders().aggregate(pipeline)}


def log_rider_availability(rider_id: int, active_orders: int, available: bool) -> None:
    logger.info(
        "[RIDER_AVAILABILITY] rider_id=%s active_orders=%s available=%s",
        rider_id,
        active_orders,
        available,
    )


def is_rider_available_for_assignment(rider_id: int) -> bool:
    """True when rider is active, has rider role, and has no non-terminal assigned order."""
    rider = user_repository.find_by_user_id(rider_id)
    if not rider:
        log_rider_availability(rider_id, 0, False)
        return False
    roles = rider.get("roles") or []
    if isinstance(roles, str):
        roles = [roles]
    if "rider" not in roles and rider.get("role") != "rider":
        log_rider_availability(rider_id, 0, False)
        return False
    if not rider.get("is_active", 1):
        log_rider_availability(rider_id, 0, False)
        return False
    active_count = count_active_orders_for_rider(rider_id)
    available = active_count == 0
    log_rider_availability(rider_id, active_count, available)
    return available


def count_all_orders() -> int:
    return _orders().count_documents({})


def count_active_orders() -> int:
    return _orders().count_documents({"status": {"$nin": list(TERMINAL)}})


def sum_revenue_delivered() -> float:
    pipeline = [
        {"$match": {"status": {"$in": ["DELIVERED", "DELIVERED_SUCCESS"]}}},
        {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}},
    ]
    res = list(_orders().aggregate(pipeline))
    return float(res[0]["total"]) if res else 0.0


def sum_revenue_delivered_today() -> float:
    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    pipeline = [
        {
            "$match": {
                "status": {"$in": ["DELIVERED", "DELIVERED_SUCCESS"]},
                "created_at": {"$gte": start_of_day},
            }
        },
        {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}},
    ]
    res = list(_orders().aggregate(pipeline))
    return float(res[0]["total"]) if res else 0.0


_DELIVERED_STATUSES = ["DELIVERED", "DELIVERED_SUCCESS"]

ADMIN_ORDER_PROJECTION = {
    "_id": 0,
    "order_id": 1,
    "user_id": 1,
    "address_id": 1,
    "status": 1,
    "total_amount": 1,
    "subtotal": 1,
    "delivery_fee": 1,
    "created_at": 1,
    "rider_id": 1,
    "items": 1,
    "payment_method": 1,
    "address": 1,
    "assigned_at": 1,
    "version": 1,
}


def aggregate_admin_dashboard_stats() -> Dict[str, Any]:
    """Single aggregation for order-side dashboard metrics."""
    from core.perf import timed_mongo

    start_of_day = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    pipeline = [
        {
            "$facet": {
                "total_orders": [{"$count": "n"}],
                "active_orders": [
                    {"$match": {"status": {"$nin": list(TERMINAL)}}},
                    {"$count": "n"},
                ],
                "delivered_orders": [
                    {"$match": {"status": {"$in": _DELIVERED_STATUSES}}},
                    {"$count": "n"},
                ],
                "total_revenue": [
                    {"$match": {"status": {"$in": _DELIVERED_STATUSES}}},
                    {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}},
                ],
                "today_revenue": [
                    {
                        "$match": {
                            "status": {"$in": _DELIVERED_STATUSES},
                            "created_at": {"$gte": start_of_day},
                        }
                    },
                    {"$group": {"_id": None, "total": {"$sum": "$total_amount"}}},
                ],
            }
        }
    ]
    with timed_mongo("orders dashboard stats aggregation"):
        rows = list(_orders().aggregate(pipeline, allowDiskUse=False))
    facet = rows[0] if rows else {}

    def _facet_count(key: str) -> int:
        arr = facet.get(key) or []
        return int(arr[0]["n"]) if arr else 0

    def _facet_sum(key: str) -> float:
        arr = facet.get(key) or []
        return float(arr[0]["total"]) if arr else 0.0

    return {
        "total_orders": _facet_count("total_orders"),
        "active_orders": _facet_count("active_orders"),
        "delivered_orders": _facet_count("delivered_orders"),
        "total_revenue": round(_facet_sum("total_revenue"), 2),
        "today_revenue": round(_facet_sum("today_revenue"), 2),
    }


def _hydrate_assigned_rider(
    rid_raw,
    users_map: Dict[int, Dict[str, Any]],
    active_by_rider: Dict[int, int],
) -> tuple:
    """Returns (rider_id, rider_name, rider_online, rider_active_orders, rider_obj)."""
    rid = _coerce_rider_id(rid_raw)
    if rid is None:
        return None, None, False, 0, None

    rider = users_map.get(rid)
    if not rider:
        rider = user_repository.get_rider_by_id_safe(rid)
        if rider:
            users_map[rid] = rider

    if not rider:
        logger.warning("[ADMIN_RIDER_RENDER] rider_id=%s not found in users map", rid)
        return rid, None, False, 0, None

    active_orders = int(active_by_rider.get(rid, 0))
    name = rider.get("name") or "Rider"
    work_status = get_rider_work_status(active_orders)
    rider_obj = build_rider_availability_payload(
        rid,
        name,
        active_orders,
        extra={
            "id": rid,
            "riderId": rid,
            "name": name,
            "phone": rider.get("phone"),
            "profile_pic": rider.get("profile_pic"),
        },
    )
    logger.info(
        "[ADMIN_RIDER_RENDER] order rider_id=%s name=%s rider_status=%s active_orders=%s",
        rid,
        name,
        work_status,
        active_orders,
    )
    return rid, name, True, active_orders, rider_obj


def _build_admin_order_entry(
    doc: Dict[str, Any],
    users_map: Dict[int, Dict[str, Any]],
    foods_map: Dict[int, Dict[str, Any]],
    addresses_map: Dict[tuple, Dict[str, Any]],
    active_by_rider: Dict[int, int],
) -> Dict[str, Any]:
    uid = int(doc["user_id"])
    customer = users_map.get(uid) or {}
    customer_name = customer.get("name") or "Unknown"
    customer_phone = customer.get("phone") or "Unknown"

    address_info = None
    if doc.get("address_id"):
        address_info = addresses_map.get((int(doc["address_id"]), uid))
    if not address_info and isinstance(doc.get("address"), dict):
        snap = doc["address"]
        address_info = {
            "name": snap.get("name") or customer_name,
            "phone": snap.get("phone") or customer_phone,
            "address_line": snap.get("address_line") or snap.get("line") or "Unknown",
            "city": snap.get("city") or "Unknown",
            "pincode": snap.get("pincode") or "Unknown",
        }

    items_normalized = []
    subtotal = 0.0
    for item in doc.get("items") or []:
        iid = int(item.get("item_id") or 0)
        food = foods_map.get(iid) or {}
        unit_price = float(item.get("price") or item.get("unit_price") or food.get("price") or 0)
        qty = int(item.get("quantity") or 0)
        line_total = round(unit_price * qty, 2)
        subtotal += line_total
        items_normalized.append(
            {
                "item_id": iid,
                "name": item.get("name") or food.get("name") or "Unknown Item",
                "quantity": qty,
                "unit_price": unit_price,
                "total_price": line_total,
                "food_image": food.get("image_url"),
            }
        )

    delivery_fee = float(doc.get("delivery_fee") or 40)
    total_amount = float(doc.get("total_amount") or (subtotal + delivery_fee))

    rid, rider_name, rider_online, rider_active_orders, rider = _hydrate_assigned_rider(
        doc.get("rider_id"), users_map, active_by_rider
    )

    status_str = normalize_status_internal(doc.get("status") or "PLACED")
    addr = address_info or {}

    return {
        "order_id": doc["order_id"],
        "status": status_str,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer": {
            "name": customer_name,
            "phone": customer_phone,
            "address": {
                "address_line": addr.get("address_line") or "Unknown",
                "city": addr.get("city") or "Unknown",
                "pincode": addr.get("pincode") or "Unknown",
            },
        },
        "rider_name": rider_name,
        "rider_id": rid,
        "rider_online": rider_online,
        "rider_active_orders": rider_active_orders,
        "rider": rider,
        "items": items_normalized,
        "payment_method": doc.get("payment_method", "COD"),
        "total_amount": round(total_amount, 2),
        "created_at": _iso(doc.get("created_at")),
        "assigned_at": _iso(doc.get("assigned_at")),
        "version": doc.get("version", 1),
    }


def list_admin_orders_paginated(page: int = 1, limit: int = 20) -> Dict[str, Any]:
    """Batch-loaded admin order list — avoids per-order N+1 queries."""
    from core.perf import timed_mongo

    page = max(1, int(page))
    limit = min(100, max(1, int(limit)))
    skip = (page - 1) * limit

    with timed_mongo("admin orders count"):
        total = _orders().count_documents({})

    with timed_mongo("admin orders page fetch"):
        docs = list(
            _orders()
            .find({}, ADMIN_ORDER_PROJECTION)
            .sort("created_at", -1)
            .skip(skip)
            .limit(limit)
        )

    user_ids = {int(d["user_id"]) for d in docs}
    rider_ids = set()
    for d in docs:
        rid = _coerce_rider_id(d.get("rider_id"))
        if rid is not None:
            rider_ids.add(rid)
    all_user_ids = list(user_ids | rider_ids)
    active_by_rider = count_active_orders_grouped_by_rider()

    food_ids = set()
    addr_pairs = []
    for d in docs:
        if d.get("address_id"):
            addr_pairs.append((int(d["address_id"]), int(d["user_id"])))
        for it in d.get("items") or []:
            if it.get("item_id") is not None:
                food_ids.add(int(it["item_id"]))

    with timed_mongo("admin orders batch lookups"):
        users_map = user_repository.find_map_by_user_ids(all_user_ids)
        foods_map = food_repository.fetch_map_by_legacy_ids(list(food_ids))
        addresses_map = address_repository.find_map_by_address_user_pairs(addr_pairs)

    with timed_mongo("admin orders serialization"):
        items = [
            _build_admin_order_entry(doc, users_map, foods_map, addresses_map, active_by_rider)
            for doc in docs
        ]

    pages = max(1, (total + limit - 1) // limit)
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages,
    }


def get_admin_order_snapshot(order_id: int) -> Optional[Dict[str, Any]]:
    """Single-order admin payload with hydrated rider fields (post-assign sync)."""
    from core.perf import timed_mongo

    doc = find_by_order_id(order_id)
    if not doc:
        return None
    uid = int(doc["user_id"])
    rid = _coerce_rider_id(doc.get("rider_id"))
    user_ids = [uid]
    if rid is not None:
        user_ids.append(rid)
    active_by_rider = count_active_orders_grouped_by_rider()
    food_ids = {int(it["item_id"]) for it in (doc.get("items") or []) if it.get("item_id") is not None}
    addr_pairs = []
    if doc.get("address_id"):
        addr_pairs.append((int(doc["address_id"]), uid))
    with timed_mongo("admin order snapshot lookups"):
        users_map = user_repository.find_map_by_user_ids(user_ids)
        foods_map = food_repository.fetch_map_by_legacy_ids(list(food_ids))
        addresses_map = address_repository.find_map_by_address_user_pairs(addr_pairs)
    return _build_admin_order_entry(doc, users_map, foods_map, addresses_map, active_by_rider)


def get_active_orders_for_rider(rider_id: int) -> List[int]:
    return [
        d["order_id"]
        for d in _orders().find(
            {"rider_id": int(rider_id), "status": {"$nin": list(TERMINAL)}},
            {"order_id": 1},
        )
    ]


def get_active_rider_location_for_order(order_id: int) -> Dict[str, Any]:
    from repositories import rider_repository

    doc = find_by_order_id(order_id)
    if not doc or not doc.get("rider_id"):
        return {"status": "No rider assigned", "location": None}
    rid = doc["rider_id"]
    loc = rider_repository.get_rider_location(rid)
    if loc and loc.get("lat") is not None:
        return {
            "activeRider": {
                "riderId": rid,
                "lat": float(loc["lat"]),
                "lng": float(loc["lng"]),
                "heading": loc.get("heading"),
                "speed": loc.get("speed"),
            },
            "status": "Online",
        }
    history = list(reversed(doc.get("tracking") or []))
    for h in history:
        if h.get("lat") is not None:
            return {
                "activeRider": {
                    "riderId": rid,
                    "lat": float(h["lat"]),
                    "lng": float(h["lng"]),
                    "heading": 0,
                    "speed": 0,
                },
                "status": "Last Known (Offline)",
                "last_seen": _iso(h.get("created_at")),
            }
    return {"status": "Rider offline", "location": None}


def get_rider_stats_for_today(rider_id: int) -> Dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    completed = 0
    earnings = 0.0
    active_count = 0
    for doc in _orders().find({"rider_id": int(rider_id)}):
        st = doc.get("status")
        if st in ("DELIVERED", "DELIVERED_SUCCESS"):
            delivered = doc.get("delivered_at") or doc.get("created_at")
            if delivered and hasattr(delivered, "date") and delivered.date() == today:
                completed += 1
                earnings += float(doc.get("delivery_fee") or 0)
        if st not in TERMINAL:
            active_count += 1
    return {
        "completed_today": completed,
        "earnings_today": float(earnings),
        "active_count": active_count,
    }


def get_rider_history_rows(rider_id: int) -> List[Dict[str, Any]]:
    cursor = _orders().find(
        {"rider_id": int(rider_id), "status": "DELIVERED"}
    ).sort("created_at", -1)
    rows = []
    for doc in cursor:
        row = order_doc_to_row(doc)
        cust = user_repository.find_by_user_id(doc["user_id"])
        row["customer_name"] = cust.get("name") if cust else None
        rows.append(row)
    return rows


def upsert_order_from_mysql(order_row: Dict, items: List[Dict], tracking: List[Dict]) -> None:
    oid = int(order_row["order_id"])
    seed_sequence("order_id", oid)
    doc = {
        "order_id": oid,
        "user_id": int(order_row["user_id"]),
        "address_id": order_row.get("address_id"),
        "subtotal": float(order_row.get("subtotal") or 0),
        "delivery_fee": float(order_row.get("delivery_fee") or 40),
        "total_amount": float(order_row.get("total_amount") or 0),
        "address": order_row.get("address"),
        "payment_method": order_row.get("payment_method", "COD"),
        "payment_status": order_row.get("payment_status", "PENDING"),
        "status": order_row.get("status", "ORDER_PLACED"),
        "restaurant_lat": order_row.get("restaurant_lat"),
        "restaurant_lng": order_row.get("restaurant_lng"),
        "user_lat": order_row.get("user_lat"),
        "user_lng": order_row.get("user_lng"),
        "rider_id": order_row.get("rider_id"),
        "items": items,
        "tracking": tracking,
        "version": order_row.get("version", 1),
        "created_at": order_row.get("created_at") or datetime.now(timezone.utc),
        "assigned_at": order_row.get("assigned_at"),
        "accepted_at": order_row.get("accepted_at"),
        "delivered_at": order_row.get("delivered_at"),
        "updated_at": datetime.now(timezone.utc),
    }
    _orders().update_one({"order_id": oid}, {"$set": doc}, upsert=True)
