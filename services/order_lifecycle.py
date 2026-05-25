"""
Order status lifecycle — single source of truth for transitions and normalization.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Canonical statuses (API / WS / DB writes after normalization)
PLACED = "PLACED"
CONFIRMED = "CONFIRMED"
READY = "READY"
ASSIGNED = "ASSIGNED"
PICKED_UP = "PICKED_UP"
ON_WAY = "ON_WAY"
ARRIVING = "ARRIVING"
DELIVERED = "DELIVERED"
CANCELLED = "CANCELLED"

ALL_CANONICAL = {
    PLACED,
    CONFIRMED,
    READY,
    ASSIGNED,
    PICKED_UP,
    ON_WAY,
    ARRIVING,
    DELIVERED,
    CANCELLED,
}

ORDER_FLOW = {
    PLACED: CONFIRMED,
    CONFIRMED: READY,
    READY: ASSIGNED,
    ASSIGNED: PICKED_UP,
    PICKED_UP: ON_WAY,
    ON_WAY: ARRIVING,
    ARRIVING: DELIVERED,
}

ASSIGNABLE_STATUSES = {READY}
ADMIN_ALLOWED_STATUSES = {CONFIRMED, READY}
RIDER_ALLOWED_STATUSES = {PICKED_UP, ON_WAY, ARRIVING, DELIVERED}

# Legacy aliases → canonical (read path / inbound API)
_LEGACY_TO_CANONICAL = {
    "ORDER_PLACED": PLACED,
    "PLACED": PLACED,
    "RESTAURANT_CONFIRMED": CONFIRMED,
    "CONFIRMED": CONFIRMED,
    "PREPARING": READY,
    "PREPARING_FOOD": READY,
    "FOOD_READY": READY,
    "READY": READY,
    "RIDER_ASSIGNED": ASSIGNED,
    "PARTNER_ASSIGNED": ASSIGNED,
    "DELIVERY_PARTNER_ASSIGNED": ASSIGNED,
    "ASSIGNED": ASSIGNED,
    "ORDER_ACCEPTED": ASSIGNED,
    "ACCEPTED": ASSIGNED,
    "PICKED": PICKED_UP,
    "ORDER_PICKED_UP": PICKED_UP,
    "PICKED_UP": PICKED_UP,
    "ON_THE_WAY": ON_WAY,
    "OUT_FOR_DELIVERY": ON_WAY,
    "ON_WAY": ON_WAY,
    "NEAR_YOUR_LOCATION": ARRIVING,
    "NEAR_CUSTOMER_LOCATION": ARRIVING,
    "ARRIVING": ARRIVING,
    "DELIVERED_SUCCESS": DELIVERED,
    "DELIVERED": DELIVERED,
    "CANCELLED": CANCELLED,
}


def normalize_status_internal(status) -> str:
    """Map any stored or inbound status to the canonical lifecycle string."""
    if not status:
        return PLACED
    raw = status
    s = str(status).upper().replace(" ", "_")
    clean = _LEGACY_TO_CANONICAL.get(s, s)
    if clean not in ALL_CANONICAL:
        if s in ALL_CANONICAL:
            clean = s
        else:
            logger.warning("[STATUS_NORMALIZE] Unknown status %r — defaulting to PLACED", raw)
            clean = PLACED
    logger.info("[STATUS_NORMALIZE][RAW] %s", raw)
    logger.info("[STATUS_NORMALIZE][CLEAN] %s", clean)
    return clean


def validate_status_transition(current_status: str, next_status: str) -> bool:
    """Only allow the exact next step in ORDER_FLOW."""
    current = normalize_status_internal(current_status)
    next_st = normalize_status_internal(next_status)
    if current == next_st:
        return False
    expected_next = ORDER_FLOW.get(current)
    if expected_next != next_st:
        logger.warning(
            "[TRANSITION_REJECTED] %s -> %s (expected: %s)",
            current,
            next_st,
            expected_next,
        )
        return False
    return True


def is_admin_allowed_status(status: str) -> bool:
    return normalize_status_internal(status) in ADMIN_ALLOWED_STATUSES


def is_rider_allowed_status(status: str) -> bool:
    return normalize_status_internal(status) in RIDER_ALLOWED_STATUSES
