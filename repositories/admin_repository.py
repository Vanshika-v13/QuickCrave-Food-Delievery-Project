"""admin_audit_log collection — PyMongo only."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from repositories import order_repository, user_repository
from repositories.mongo_client import get_collection, next_sequence, seed_sequence


def _coll():
    return get_collection("admin_audit_log")


def ensure_indexes():
    c = _coll()
    c.create_index("admin_id")
    c.create_index("order_id")
    c.create_index("timestamp")
    c.create_index([("timestamp", -1)])


def log_admin_action(admin_id: int, action: str, order_id=None, details=None) -> bool:
    try:
        _coll().insert_one(
            {
                "id": next_sequence("admin_audit_id"),
                "admin_id": int(admin_id),
                "action": action,
                "order_id": int(order_id) if order_id is not None else None,
                "details": details,
                "timestamp": datetime.now(timezone.utc),
            }
        )
        return True
    except Exception:
        return False


def get_admin_dashboard_stats() -> Dict[str, Any]:
    try:
        from core.cache import get_cached, set_cached
        from core.perf import timed_mongo

        cache_key = "admin_dashboard_stats"
        cached = get_cached(cache_key)
        if cached is not None:
            return cached

        with timed_mongo("admin dashboard stats"):
            order_stats = order_repository.aggregate_admin_dashboard_stats()
            total_customers = user_repository.count_customers()
            total_riders = user_repository.count_riders()

        stats = {
            **order_stats,
            "total_customers": total_customers,
            "total_riders": total_riders,
        }
        set_cached(cache_key, stats, ttl_seconds=20)
        return stats
    except Exception:
        return {
            "total_orders": 0,
            "active_orders": 0,
            "delivered_orders": 0,
            "total_customers": 0,
            "total_riders": 0,
            "total_revenue": 0,
            "today_revenue": 0,
        }


def list_audit_logs(page: int = 1, limit: int = 20) -> Dict[str, Any]:
    page = max(1, int(page))
    limit = min(100, max(1, int(limit)))
    skip = (page - 1) * limit
    coll = _coll()
    total = coll.count_documents({})
    cursor = (
        coll.find(
            {},
            {
                "_id": 0,
                "id": 1,
                "admin_id": 1,
                "action": 1,
                "order_id": 1,
                "details": 1,
                "timestamp": 1,
            },
        )
        .sort("timestamp", -1)
        .skip(skip)
        .limit(limit)
    )
    items = []
    for doc in cursor:
        ts = doc.get("timestamp")
        items.append(
            {
                "id": doc.get("id"),
                "admin_id": doc.get("admin_id"),
                "action": doc.get("action"),
                "order_id": doc.get("order_id"),
                "details": doc.get("details"),
                "created_at": ts.isoformat() if hasattr(ts, "isoformat") else ts,
            }
        )
    pages = max(1, (total + limit - 1) // limit)
    return {"items": items, "total": total, "page": page, "limit": limit, "pages": pages}


def insert_from_mysql(row: Dict[str, Any]) -> None:
    audit_id = int(row.get("id") or next_sequence("admin_audit_id"))
    seed_sequence("admin_audit_id", audit_id)
    doc = {
        "id": audit_id,
        "admin_id": row.get("admin_id"),
        "action": row.get("action"),
        "order_id": row.get("order_id"),
        "details": row.get("details"),
        "timestamp": row.get("timestamp") or datetime.now(timezone.utc),
    }
    _coll().replace_one({"id": audit_id}, doc, upsert=True)
