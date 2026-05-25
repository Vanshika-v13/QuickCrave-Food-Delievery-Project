"""User profile — MongoDB only."""

from __future__ import annotations

from services import auth_service


def get_user_by_id(user_id: int):
    return auth_service.get_user_by_id(user_id)


def get_profile(user_id: int):
    return get_user_by_id(user_id)


def verify_user_active(user_id: int):
    db_user = get_user_by_id(user_id)
    if not db_user:
        return None
    if not db_user.get("is_active", 1):
        return None
    return db_user
