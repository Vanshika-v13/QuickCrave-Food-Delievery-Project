"""Authentication — MongoDB only."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional, Tuple

from repositories import user_repository

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_EMAIL = "vanshika@gmail.com"
DEFAULT_ADMIN_PASSWORD = "123456"
DEFAULT_ADMIN_NAME = "Vanshika Admin"

AuthError = Tuple[str, int]


def create_user(name, email, hashed_password=None, google_id=None, profile_pic=None):
    return user_repository.create_user(name, email, hashed_password, google_id, profile_pic)


def update_user_google_info(user_id, google_id, profile_pic):
    return user_repository.update_user_google_info(user_id, google_id, profile_pic)


def get_user_by_email(email):
    return user_repository.find_by_email(email)


def get_user_by_id(user_id):
    return user_repository.find_by_user_id(user_id)


def ensure_default_admin(hash_password: Callable[[str], str]) -> None:
    """Idempotent seed for the default admin account."""
    existing = user_repository.find_by_email(DEFAULT_ADMIN_EMAIL)
    if existing and "admin" in (existing.get("roles") or []):
        logger.info("[ADMIN] Default admin already exists")
        return
    if existing:
        logger.warning(
            "[ADMIN] %s exists but is not an admin; skipping default admin seed",
            DEFAULT_ADMIN_EMAIL,
        )
        return
    hashed = hash_password(DEFAULT_ADMIN_PASSWORD)
    user_id = user_repository.create_user(
        DEFAULT_ADMIN_NAME,
        DEFAULT_ADMIN_EMAIL,
        hashed,
        roles=["admin"],
    )
    if user_id:
        logger.info("[ADMIN] Default admin created")
    else:
        logger.error("[ADMIN] Failed to create default admin")


def validate_role_login(
    db_user: Optional[Dict[str, Any]],
    plain_password: str,
    verify_password_fn: Callable[[str, str], bool],
    *,
    required_role: str,
    not_found_message: str,
    invalid_password_message: str,
    access_denied_message: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[AuthError]]:
    """
    Role-scoped login validation.
    Returns (user, None) on success or (None, (message, http_status)) on failure.
    """
    if not db_user:
        return None, (not_found_message, 404)
    if not verify_password_fn(plain_password, db_user.get("password")):
        return None, (invalid_password_message, 401)
    roles = db_user.get("roles") or []
    if required_role not in roles:
        return None, (access_denied_message, 403)
    return db_user, None
