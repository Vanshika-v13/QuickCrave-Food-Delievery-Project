"""
Order domain — MongoDB only.
"""

from __future__ import annotations

from typing import List, Optional

from core import order_presenter
from order_states import ACTIVE_STATES, HISTORY_STATES
from repositories import order_repository
from services.order_lifecycle import (
    ASSIGNABLE_STATUSES,
    normalize_status_internal,
    validate_status_transition,
    is_admin_allowed_status,
    is_rider_allowed_status,
)


class OrderService:
    @staticmethod
    def classify(status: str) -> str:
        if status in ACTIVE_STATES:
            return "ACTIVE"
        if status in HISTORY_STATES:
            return "HISTORY"
        return "PENDING"

    @staticmethod
    def normalize(status: str) -> str:
        return normalize_status_internal(status)

    @staticmethod
    def validate_transition(old_status: str, new_status: str) -> str:
        if not old_status:
            return new_status
        if old_status in HISTORY_STATES:
            raise Exception(f"Terminal State Violation: Cannot update order in state '{old_status}'")
        return new_status

    @staticmethod
    def assert_mutual_exclusion(status: str):
        if status in ACTIVE_STATES and status in HISTORY_STATES:
            raise Exception(f"State Corruption: Status '{status}' detected in both sets.")


def get_order_by_id(order_id: int):
    doc = order_repository.find_by_order_id(order_id)
    return order_repository.order_doc_to_row(doc) if doc else None


def get_order_summary(order_id: int, is_admin_view: bool = False):
    return order_presenter.get_order_summary(order_id, is_admin_view=is_admin_view)


def get_order_details(order_id: int):
    return order_presenter.get_order_summary(order_id)


def validate_order_owner(order_id: int, user_id: int) -> str:
    return order_repository.validate_order_owner(order_id, user_id)


def insert_order_tracking(
    order_id, status, actor="SYSTEM", lat=None, lng=None, expected_previous_status=None
):
    return order_repository.insert_order_tracking(
        order_id, status, actor, lat, lng, expected_previous_status
    )


def place_order_in_db(
    user_id, address_id, items=None, payment_method="COD", restaurant_lat=None, restaurant_lng=None, clear_cart=True
):
    return order_repository.place_order_in_db(
        user_id, address_id, items, payment_method, restaurant_lat, restaurant_lng, clear_cart
    )


def delete_customer_order_placed(order_id: int, user_id: int) -> str:
    return order_repository.delete_customer_order_placed(order_id, user_id)


def resolve_order_status(order_id: int):
    return order_repository.build_status_object(order_id)


def get_order_status_for_user(order_id: int, user_id: int):
    return order_repository.get_order_status_for_user(order_id, user_id)


def get_user_orders_full(user_id: int):
    full_orders = []
    for order in order_repository.get_user_orders(user_id):
        summary = order_presenter.get_order_summary(order["order_id"])
        if summary:
            full_orders.append(summary)
    return full_orders


def get_active_rider_location_for_order(order_id: int):
    return order_repository.get_active_rider_location_for_order(order_id)


def assign_rider_to_order(order_id, rider_id, actor="ADMIN", admin_id=None):
    return order_repository.assign_rider_to_order(order_id, rider_id, actor, admin_id)


def accept_assigned_order(order_id: int, rider_id: int):
    return order_repository.accept_assigned_order(order_id, rider_id)


def admin_update_order_status(order_id: int, new_status: str) -> dict:
    new_status = normalize_status_internal(new_status)
    if not is_admin_allowed_status(new_status):
        return {"ok": False, "http_status": 403, "detail": f"Admins are not permitted to set status to {new_status}"}
    summary = order_presenter.get_order_summary(order_id, is_admin_view=True)
    if not summary:
        return {"ok": False, "http_status": 404, "detail": "Order not found"}
    current_status = summary["status"]["current_status"]
    if not validate_status_transition(current_status, new_status):
        return {
            "ok": False,
            "http_status": 400,
            "detail": f"Invalid transition from {current_status} to {new_status}",
        }
    if not insert_order_tracking(order_id, new_status, actor="ADMIN", expected_previous_status=current_status):
        return {"ok": False, "http_status": 500, "detail": "Failed to update order status"}
    return {"ok": True, "new_status": new_status}


def rider_update_order_status(order_id, rider_id, new_status, lat=None, lng=None) -> dict:
    new_status = normalize_status_internal(new_status)
    if not is_rider_allowed_status(new_status):
        return {"ok": False, "http_status": 403, "detail": f"Riders are not permitted to set status to {new_status}"}
    summary = order_presenter.get_order_summary(order_id, is_admin_view=True)
    if not summary:
        return {"ok": False, "http_status": 404, "detail": "Order not found"}
    assigned = summary.get("rider")
    if not assigned or assigned.get("riderId") != rider_id:
        return {"ok": False, "http_status": 403, "detail": "Access denied: You are not assigned to this order"}
    current_status = summary["status"]["current_status"]
    if normalize_status_internal(current_status) == "ASSIGNED" and new_status == "PICKED_UP":
        doc = order_repository.find_by_order_id(order_id)
        if not doc or not doc.get("accepted_at"):
            return {
                "ok": False,
                "http_status": 400,
                "detail": "Accept the order before marking picked up",
            }
    if not validate_status_transition(current_status, new_status):
        return {
            "ok": False,
            "http_status": 400,
            "detail": f"Invalid transition from {current_status} to {new_status}",
        }
    if not insert_order_tracking(order_id, new_status, actor="RIDER", lat=lat, lng=lng, expected_previous_status=current_status):
        return {"ok": False, "http_status": 500, "detail": "Failed to update order status"}
    return {"ok": True, "new_status": new_status}


def validate_assignable_for_rider_assignment(order_id: int) -> Optional[str]:
    summary = order_presenter.get_order_summary(order_id)
    if not summary:
        return None
    current_status = summary["status"]["current_status"]
    if normalize_status_internal(current_status) not in ASSIGNABLE_STATUSES:
        return (
            f"Cannot assign rider: Order is {current_status}. "
            f"Must be one of: {', '.join(sorted(ASSIGNABLE_STATUSES))}."
        )
    return None


def authorize_order_access(order_id: int, user_id: int, user_roles: List[str]) -> dict:
    summary = order_presenter.get_order_summary(order_id)
    if not summary:
        return {"allowed": False, "http_status": 404, "detail": "Order not found"}
    if "admin" in user_roles:
        return {"allowed": True, "summary": summary}
    if "rider" in user_roles:
        if summary.get("rider") and summary["rider"].get("riderId") == user_id:
            return {"allowed": True, "summary": summary}
        return {"allowed": False, "http_status": 403, "detail": "Access denied: you are not assigned to this order"}
    ownership = validate_order_owner(order_id, user_id)
    if ownership == "ORDER_NOT_FOUND":
        return {"allowed": False, "http_status": 404, "detail": "Order not found"}
    if ownership == "ACCESS_DENIED":
        return {"allowed": False, "http_status": 403, "detail": "Access denied: you do not own this order"}
    return {"allowed": True, "summary": summary}
