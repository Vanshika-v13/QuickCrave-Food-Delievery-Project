#!/usr/bin/env python3
"""
Read-only MongoDB consistency audit (migration readiness).
Run: python scripts/validate_mongodb_consistency.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.mongo_client import get_collection, get_database  # noqa: E402


def dup_legacy_ids(coll_name: str, field: str) -> list:
    pipeline = [
        {"$match": {field: {"$exists": True, "$ne": None}}},
        {"$group": {"_id": f"${field}", "n": {"$sum": 1}}},
        {"$match": {"n": {"$gt": 1}}},
        {"$limit": 20},
    ]
    return list(get_collection(coll_name).aggregate(pipeline))


def main() -> int:
    db = get_database()
    report: dict = {"collections": {}, "issues": [], "warnings": []}

    collections = [
        "users",
        "food_items",
        "carts",
        "orders",
        "order_tracking",
        "user_addresses",
        "rider_locations",
        "admin_audit_log",
        "counters",
    ]

    for name in collections:
        try:
            report["collections"][name] = db[name].count_documents({})
        except Exception as e:
            report["collections"][name] = None
            report["issues"].append(f"count_failed:{name}:{e}")

    # order_items: embedded in orders; optional legacy collection
    try:
        oi_count = db["order_items"].count_documents({})
        if oi_count:
            report["warnings"].append(
                f"legacy order_items collection has {oi_count} docs (app uses embedded items[])"
            )
    except Exception:
        pass

    users = get_collection("users")
    food = get_collection("food_items")
    orders = get_collection("orders")
    carts = get_collection("carts")
    addresses = get_collection("user_addresses")

    user_ids = {u["user_id"] for u in users.find({}, {"user_id": 1})}
    food_ids = set()
    for doc in food.find({}, {"legacy_mysql_id": 1, "item_id": 1}):
        fid = doc.get("legacy_mysql_id") or doc.get("item_id")
        if fid is not None:
            food_ids.add(int(fid))

    missing_user_refs = 0
    orphan_items = 0
    orders_no_items = 0
    for o in orders.find({}, {"order_id": 1, "user_id": 1, "items": 1}):
        if o.get("user_id") not in user_ids:
            missing_user_refs += 1
        items = o.get("items") or []
        if not items:
            orders_no_items += 1
        for it in items:
            iid = int(it.get("item_id", -1))
            if iid not in food_ids:
                orphan_items += 1

    if missing_user_refs:
        report["issues"].append(f"orders_with_unknown_user_id:{missing_user_refs}")
    if orphan_items:
        report["issues"].append(f"order_line_items_missing_food:{orphan_items}")
    if orders_no_items:
        report["warnings"].append(f"orders_without_embedded_items:{orders_no_items}")

    cart_dup_user = dup_legacy_ids("carts", "user_id")
    if cart_dup_user:
        report["issues"].append(f"duplicate_cart_user_ids:{cart_dup_user}")

    carts_bad_user = 0
    carts_bad_item = 0
    for c in carts.find({}):
        uid = c.get("user_id")
        if uid not in user_ids:
            carts_bad_user += 1
        for it in c.get("items") or []:
            iid = int(it.get("item_id", -1))
            if iid not in food_ids:
                carts_bad_item += 1
    if carts_bad_user:
        report["issues"].append(f"carts_unknown_user:{carts_bad_user}")
    if carts_bad_item:
        report["issues"].append(f"cart_items_missing_food:{carts_bad_item}")

    for coll, field in [
        ("food_items", "legacy_mysql_id"),
        ("users", "legacy_mysql_id"),
        ("orders", "legacy_mysql_id"),
    ]:
        dups = dup_legacy_ids(coll, field)
        if dups:
            report["issues"].append(f"duplicate_{coll}_{field}:{dups}")

    addr_bad = sum(
        1 for a in addresses.find({}, {"user_id": 1}) if a.get("user_id") not in user_ids
    )
    if addr_bad:
        report["issues"].append(f"addresses_unknown_user:{addr_bad}")

    tracking_orphans = 0
    order_ids = {o["order_id"] for o in orders.find({}, {"order_id": 1})}
    for t in get_collection("order_tracking").find({}, {"order_id": 1}):
        if t.get("order_id") not in order_ids:
            tracking_orphans += 1
    if tracking_orphans:
        report["warnings"].append(f"order_tracking_orphan_order_id:{tracking_orphans}")

    report["summary"] = {
        "issue_count": len(report["issues"]),
        "warning_count": len(report["warnings"]),
        "ready_hint": len(report["issues"]) == 0,
    }

    print(json.dumps(report, indent=2, default=str))
    return 0 if not report["issues"] else 1


if __name__ == "__main__":
    sys.exit(main())
