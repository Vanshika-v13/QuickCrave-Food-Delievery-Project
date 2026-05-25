"""Rider operations — MongoDB only."""

from __future__ import annotations

import logging

from core.order_presenter import get_order_summary
from repositories import order_repository, rider_repository, user_repository
from services.order_lifecycle import normalize_status_internal

logger = logging.getLogger(__name__)


def get_all_riders():
    return user_repository.find_all_riders()


def create_rider_by_admin(
    name, email, phone, password_hash, vehicle_type, license_number, profile_pic=None
):
    return user_repository.create_rider_by_admin(
        name, email, phone, password_hash, vehicle_type, license_number, profile_pic
    )


def toggle_user_active(user_id: int, status: int):
    return user_repository.toggle_user_active(user_id, status)


def set_rider_online(rider_id: int, online: bool) -> bool:
    return user_repository.set_rider_online(rider_id, online)


def get_rider_presence(rider_id: int) -> dict:
    rider = user_repository.find_by_user_id(rider_id)
    if not rider:
        return {"online": False}
    return {
        "online": bool(rider.get("online")),
        "rider_status": rider.get("rider_status") or "offline",
    }


def get_available_orders(rider_id=None):
    logger.info("[RIDER_QUERY] available_orders rider_id=%s", rider_id)
    normalized = []
    for oid in order_repository.list_available_order_ids_for_rider(rider_id):
        summary = get_order_summary(oid)
        if summary:
            normalized.append(summary)
    logger.info("[RIDER_QUERY] available count=%s", len(normalized))
    return normalized


def get_rider_active_orders(rider_id: int):
    logger.info("[RIDER_QUERY] active_orders rider_id=%s", rider_id)
    normalized = []
    for oid in order_repository.list_active_delivery_order_ids_for_rider(rider_id):
        summary = get_order_summary(oid)
        if summary:
            normalized.append(summary)
    logger.info("[RIDER_QUERY] active count=%s", len(normalized))
    return normalized


def get_rider_history_orders(rider_id: int):
    return order_repository.get_rider_history_rows(rider_id)


def get_rider_stats(rider_id: int):
    return order_repository.get_rider_stats_for_today(rider_id)


def get_rider_realtime_state(rider_id: int):
    state = rider_repository.get_rider_realtime_state(rider_id) or {}
    presence = get_rider_presence(rider_id)
    state["online"] = presence["online"]
    state["rider_status"] = presence["rider_status"]
    return state


def upsert_rider_location(rider_id: int, lat, lng, heading=0, speed=0):
    return rider_repository.upsert_rider_location(rider_id, lat, lng, heading, speed)


def get_active_orders_for_rider(rider_id: int):
    return order_repository.get_active_orders_for_rider(rider_id)


def accept_assigned_order(order_id: int, rider_id: int):
    logger.info("[RIDER_ASSIGN] accept order_id=%s rider_id=%s", order_id, rider_id)
    return order_repository.accept_assigned_order(order_id, rider_id)


def build_rider_orders_payload(rider_id: int) -> dict:
    active_orders = get_rider_active_orders(rider_id)
    available_orders = get_available_orders(rider_id)
    rider = get_rider_realtime_state(rider_id)
    return {
        "active_orders": active_orders,
        "available_orders": available_orders,
        "orders": active_orders,
        "active_order": active_orders[0] if active_orders else None,
        "rider": rider,
        "is_online": bool(rider.get("online")) if rider else False,
    }
