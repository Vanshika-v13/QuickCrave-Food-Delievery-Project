"""Order ETA helpers — status-only (no DB)."""

from __future__ import annotations

import logging

from services.order_lifecycle import normalize_status_internal

logger = logging.getLogger(__name__)

TOTAL_DELIVERY_MINUTES = 45
FALLBACK_ETA = {
    "remaining_minutes": TOTAL_DELIVERY_MINUTES,
    "remaining_seconds": TOTAL_DELIVERY_MINUTES * 60,
    "eta_text": f"{TOTAL_DELIVERY_MINUTES} min left",
}

ETA_BY_STATUS_MINUTES = {
    "PLACED": 45,
    "CONFIRMED": 35,
    "READY": 25,
    "ASSIGNED": 20,
    "PICKED_UP": 10,
    "ON_WAY": 5,
    "ARRIVING": 5,
    "DELIVERED": 0,
    "CANCELLED": 0,
}


def calculate_remaining_delivery_time(order):
    try:
        raw = (order or {}).get("status") if isinstance(order, dict) else None
        status_key = normalize_status_internal(raw)
        if status_key in ("DELIVERED",):
            return {"remaining_minutes": 0, "remaining_seconds": 0, "eta_text": "Delivered"}
        if status_key == "CANCELLED":
            return {"remaining_minutes": 0, "remaining_seconds": 0, "eta_text": "Cancelled"}
        minutes = ETA_BY_STATUS_MINUTES.get(status_key, ETA_BY_STATUS_MINUTES["PLACED"])
        sec = minutes * 60
        return {
            "remaining_minutes": minutes,
            "remaining_seconds": sec,
            "eta_text": f"{minutes} min left" if minutes else "Delivered",
        }
    except Exception as e:
        logger.warning(f"[ETA] fallback used: {e}")
        return dict(FALLBACK_ETA)
