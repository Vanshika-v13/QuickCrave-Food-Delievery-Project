"""Workload-based rider availability (ignores socket / Redis presence)."""

from __future__ import annotations

# Orders in these statuses count toward rider workload (busy).
RIDER_WORKLOAD_STATUSES = frozenset(
    {
        "ASSIGNED",
        "PICKED_UP",
        "ON_WAY",
        "ARRIVING",
        # Legacy values still present in some documents
        "ACCEPTED",
        "ORDER_ACCEPTED",
        "ORDER_PICKED_UP",
        "OUT_FOR_DELIVERY",
        "ON_THE_WAY",
        "NEAR_CUSTOMER_LOCATION",
        "NEAR_YOUR_LOCATION",
    }
)


def get_rider_work_status(active_orders_count: int) -> str:
    if active_orders_count > 0:
        return "busy"
    return "available"


def build_rider_availability_payload(
    rider_id: int,
    rider_name: str,
    active_orders_count: int,
    *,
    extra: dict | None = None,
) -> dict:
    """Standard rider availability fields for admin APIs."""
    payload = {
        "rider_id": int(rider_id),
        "rider_name": rider_name,
        "active_orders_count": int(active_orders_count),
        "active_orders": int(active_orders_count),
        "rider_status": get_rider_work_status(active_orders_count),
    }
    if extra:
        payload.update(extra)
    return payload
