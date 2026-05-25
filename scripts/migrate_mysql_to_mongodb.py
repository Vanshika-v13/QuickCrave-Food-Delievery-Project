#!/usr/bin/env python3
"""
One-time migration: MySQL (TiDB) → MongoDB Atlas.
Requires MySQL env vars for READ only. Safe to re-run (upserts).

Usage:
  python scripts/migrate_mysql_to_mongodb.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def mysql_connect():
    import mysql.connector
    import os

    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", 4000)),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )


def _require_real_mongodb_uri() -> None:
    import os

    uri = (os.getenv("MONGODB_URI") or "").strip()
    if not uri:
        raise SystemExit("MONGODB_URI is not set. Add it to .env and retry.")
    if "<" in uri or ">" in uri:
        raise SystemExit(
            "MONGODB_URI still contains placeholders (<username> / <new_password>). "
            "Rotate the Atlas password, update .env, then retry."
        )


def main() -> int:
    _require_real_mongodb_uri()
    from repositories.mongo_client import get_client
    from repositories import (
        food_repository,
        user_repository,
        address_repository,
        cart_repository,
        order_repository,
        rider_repository,
        admin_repository,
    )

    get_client()
    cnx = mysql_connect()
    cur = cnx.cursor(dictionary=True)

    cur.execute("SELECT item_id, name, price, description, image_url, rating, tag FROM food_items")
    for row in cur.fetchall():
        food_repository.upsert_from_row(row)
    logger.info("[MIGRATE] food_items done")

    cur.execute("SELECT * FROM users")
    for row in cur.fetchall():
        user_repository.upsert_from_mysql(row)
    logger.info("[MIGRATE] users done")

    cur.execute("SELECT * FROM user_addresses")
    for row in cur.fetchall():
        address_repository.upsert_from_mysql(row)
    logger.info("[MIGRATE] user_addresses done")

    cur.execute("SELECT user_id, item_id, quantity FROM cart")
    carts = {}
    for row in cur.fetchall():
        uid = int(row["user_id"])
        carts.setdefault(uid, []).append(
            {"item_id": int(row["item_id"]), "quantity": int(row["quantity"])}
        )
    from repositories.mongo_client import get_collection
    from datetime import datetime, timezone

    for uid, items in carts.items():
        get_collection("carts").update_one(
            {"user_id": uid},
            {"$set": {"user_id": uid, "items": items, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    logger.info("[MIGRATE] carts done")

    cur.execute("SELECT * FROM orders")
    orders = cur.fetchall()
    for o in orders:
        oid = o["order_id"]
        cur.execute(
            "SELECT item_id, quantity, price, total_price FROM order_items WHERE order_id = %s",
            (oid,),
        )
        items = [
            {
                "item_id": int(i["item_id"]),
                "quantity": int(i["quantity"]),
                "price": float(i["price"]),
                "total_price": float(i.get("total_price") or 0),
            }
            for i in cur.fetchall()
        ]
        cur.execute(
            "SELECT status, old_status, actor, lat, lng, created_at FROM order_tracking WHERE order_id = %s ORDER BY created_at",
            (oid,),
        )
        tracking = [
            {
                "status": t["status"],
                "old_status": t.get("old_status"),
                "actor": t.get("actor"),
                "lat": t.get("lat"),
                "lng": t.get("lng"),
                "created_at": t.get("created_at"),
                "timestamp": t.get("created_at"),
            }
            for t in cur.fetchall()
        ]
        order_repository.upsert_order_from_mysql(o, items, tracking)
    logger.info("[MIGRATE] orders done")

    cur.execute("SELECT * FROM rider_locations")
    for row in cur.fetchall():
        rider_repository.upsert_location_from_mysql(row)
    logger.info("[MIGRATE] rider_locations done")

    try:
        cur.execute("SELECT * FROM admin_audit_log")
        for row in cur.fetchall():
            admin_repository.insert_from_mysql(row)
        logger.info("[MIGRATE] admin_audit_log done")
    except Exception:
        logger.info("[MIGRATE] admin_audit_log skipped (table may not exist)")

    _backfill_users_referenced_by_orders_and_carts()

    cur.close()
    cnx.close()
    logger.info("[MIGRATE] Complete")
    return 0


def _backfill_users_referenced_by_orders_and_carts() -> None:
    """Create stub users for legacy order/cart FKs when MySQL users row was deleted."""
    from datetime import datetime, timezone

    from repositories.mongo_client import get_collection, seed_sequence

    users_coll = get_collection("users")
    known = {int(u["user_id"]) for u in users_coll.find({}, {"user_id": 1})}
    needed: set[int] = set()
    for doc in get_collection("orders").find({}, {"user_id": 1}):
        if doc.get("user_id") is not None:
            needed.add(int(doc["user_id"]))
    for doc in get_collection("carts").find({}, {"user_id": 1}):
        if doc.get("user_id") is not None:
            needed.add(int(doc["user_id"]))

    missing = sorted(needed - known)
    if not missing:
        logger.info("[MIGRATE] user backfill: none needed")
        return

    now = datetime.now(timezone.utc)
    for uid in missing:
        seed_sequence("user_id", uid)
        users_coll.update_one(
            {"user_id": uid},
            {
                "$setOnInsert": {
                    "user_id": uid,
                    "name": f"Legacy User {uid}",
                    "email": f"legacy_user_{uid}@migrated.local",
                    "password": None,
                    "roles": ["customer"],
                    "role": "customer",
                    "is_active": 0,
                    "rider_status": "offline",
                    "created_at": now,
                    "updated_at": now,
                    "legacy_backfill": True,
                }
            },
            upsert=True,
        )
    logger.info("[MIGRATE] user backfill: created %s stub user(s)", len(missing))


if __name__ == "__main__":
    raise SystemExit(main())
