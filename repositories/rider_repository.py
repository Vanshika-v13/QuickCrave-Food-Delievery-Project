"""rider_locations collection + rider user reads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from repositories import user_repository
from repositories.mongo_client import get_collection


def _loc_coll():
    return get_collection("rider_locations")


def ensure_indexes():
    _loc_coll().create_index("rider_id", unique=True)


def upsert_rider_location(rider_id: int, lat, lng, heading=0, speed=0) -> bool:
    try:
        lat_f, lng_f = float(lat), float(lng)
        if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
            return False
    except (TypeError, ValueError):
        return False
    now = datetime.now(timezone.utc)
    _loc_coll().update_one(
        {"rider_id": int(rider_id)},
        {
            "$set": {
                "rider_id": int(rider_id),
                "lat": lat_f,
                "lng": lng_f,
                "heading": float(heading or 0),
                "speed": float(speed or 0),
                "updated_at": now,
            }
        },
        upsert=True,
    )
    return True


def get_rider_location(rider_id: int) -> Optional[Dict[str, Any]]:
    doc = _loc_coll().find_one({"rider_id": int(rider_id)})
    if not doc:
        return None
    return {
        "rider_id": doc["rider_id"],
        "lat": doc.get("lat"),
        "lng": doc.get("lng"),
        "heading": doc.get("heading"),
        "speed": doc.get("speed"),
        "updated_at": doc.get("updated_at"),
    }


def get_rider_realtime_state(rider_id: int) -> Optional[Dict[str, Any]]:
    rider = user_repository.find_by_user_id(rider_id)
    if not rider:
        return None
    loc = get_rider_location(rider_id)
    updated_at_value = (
        loc.get("updated_at") if loc and loc.get("updated_at") else rider.get("updated_at")
    )
    updated_at_iso = (
        updated_at_value.isoformat()
        if updated_at_value and hasattr(updated_at_value, "isoformat")
        else str(updated_at_value) if updated_at_value else None
    )
    version = (
        int(updated_at_value.timestamp())
        if updated_at_value and hasattr(updated_at_value, "timestamp")
        else 0
    )
    return {
        "rider_id": rider["id"],
        "rider_status": rider.get("rider_status"),
        "lat": float(loc["lat"]) if loc and loc.get("lat") is not None else None,
        "lng": float(loc["lng"]) if loc and loc.get("lng") is not None else None,
        "heading": float(loc["heading"]) if loc and loc.get("heading") is not None else 0.0,
        "updated_at": updated_at_iso,
        "version": version,
    }


def build_rider_payload_for_order(rider_id: int) -> Optional[Dict[str, Any]]:
    rider = user_repository.find_by_user_id(rider_id)
    if not rider:
        return None
    loc = get_rider_location(rider_id)
    updated_at = None
    if loc and loc.get("updated_at"):
        u = loc["updated_at"]
        updated_at = u.isoformat() if hasattr(u, "isoformat") else str(u)
    elif rider.get("updated_at"):
        u = rider["updated_at"]
        updated_at = u.isoformat() if hasattr(u, "isoformat") else str(u)
    return {
        "id": rider["id"],
        "riderId": rider["id"],
        "name": rider.get("name"),
        "phone": rider.get("phone"),
        "status": rider.get("rider_status"),
        "lat": float(loc["lat"]) if loc and loc.get("lat") is not None else None,
        "lng": float(loc["lng"]) if loc and loc.get("lng") is not None else None,
        "heading": float(loc["heading"]) if loc and loc.get("heading") is not None else 0.0,
        "updated_at": updated_at,
    }


def upsert_location_from_mysql(row: Dict[str, Any]) -> None:
    if not row:
        return
    _loc_coll().update_one(
        {"rider_id": int(row["rider_id"])},
        {
            "$set": {
                "rider_id": int(row["rider_id"]),
                "lat": row.get("lat"),
                "lng": row.get("lng"),
                "heading": row.get("heading"),
                "speed": row.get("speed"),
                "updated_at": row.get("updated_at") or datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )
