"""Admin — MongoDB only."""

from __future__ import annotations

from repositories import admin_repository, order_repository, user_repository


def get_admin_dashboard_stats():
    return admin_repository.get_admin_dashboard_stats()


def get_admin_orders(page: int = 1, limit: int = 20):
    return order_repository.list_admin_orders_paginated(page, limit)


def get_audit_logs(page: int = 1, limit: int = 20):
    return admin_repository.list_audit_logs(page, limit)


def get_admin_users(page: int = 1, limit: int = 20):
    return user_repository.list_admin_users(page, limit)


def log_admin_action(admin_id, action, order_id=None, details=None):
    from core.cache import invalidate

    ok = admin_repository.log_admin_action(admin_id, action, order_id, details)
    if ok:
        invalidate("admin_dashboard_stats")
    return ok


def assign_rider_to_order(order_id: int, rider_id: int, admin_id: int):
    from core.cache import invalidate

    result = order_repository.assign_rider_to_order(
        order_id, rider_id, actor="ADMIN", admin_id=admin_id
    )
    invalidate("admin_dashboard_stats")
    return result
