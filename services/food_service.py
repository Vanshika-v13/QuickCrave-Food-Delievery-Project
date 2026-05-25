"""Menu / food catalog — MongoDB only."""

from __future__ import annotations

import logging

from core.cache import get_cached, set_cached
from core.media import normalize_image_path as _normalize_image_path
from repositories import food_repository
from repositories.mongo_client import get_last_connect_mode, is_transient_replica_error

logger = logging.getLogger(__name__)

MENU_CACHE_KEY = "api_menu_response"
MENU_STALE_CACHE_KEY = "api_menu_response_stale"
MENU_CACHE_TTL_SECONDS = 60
MENU_STALE_TTL_SECONDS = 86400

# Process-level last successful menu — survives cache TTL expiry during outages.
_last_successful_menu: list | None = None


def get_food_items():
    return food_repository.fetch_all_food_items()


def get_food_item_by_name(name: str):
    return food_repository.fetch_food_item_by_name(name)


def get_item_id_by_name(name: str):
    row = get_food_item_by_name(name)
    return row["item_id"] if row else None


def get_item_name_by_id(item_id: int):
    return food_repository.fetch_item_name_by_id(item_id)


def normalize_image_path(image_path):
    return _normalize_image_path(image_path)


def _rows_to_menu_payload(items) -> list:
    return [
        {
            "id": i["item_id"],
            "name": i["name"],
            "price": float(i["price"]),
            "category": i.get("tag", "General"),
            "image": normalize_image_path(i.get("image_url")),
        }
        for i in items
    ]


def _menu_degraded_fallback(exc: Exception, *, source: str) -> list:
    """Return best available menu snapshot; never raises."""
    stale = get_cached(MENU_STALE_CACHE_KEY)
    if stale is not None:
        logger.warning(
            "[MENU][DEGRADED] source=%s mode=%s fallback=stale_cache reason=%s",
            source,
            get_last_connect_mode(),
            exc,
        )
        return stale
    global _last_successful_menu
    if _last_successful_menu is not None:
        logger.warning(
            "[MENU][DEGRADED] source=%s mode=%s fallback=last_successful reason=%s",
            source,
            get_last_connect_mode(),
            exc,
        )
        return _last_successful_menu
    logger.warning(
        "[MENU][DEGRADED] source=%s mode=%s fallback=empty_list reason=%s",
        source,
        get_last_connect_mode(),
        exc,
    )
    return []


def build_menu_response():
    """
    Build /api/menu payload with cache + degraded fallback.
    Never raises — always returns a valid list for the menu endpoint.
    """
    global _last_successful_menu

    cached = get_cached(MENU_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        items = get_food_items()
        menu = _rows_to_menu_payload(items)
        set_cached(MENU_CACHE_KEY, menu, MENU_CACHE_TTL_SECONDS)
        set_cached(MENU_STALE_CACHE_KEY, menu, MENU_STALE_TTL_SECONDS)
        _last_successful_menu = menu
        return menu
    except Exception as exc:
        if is_transient_replica_error(exc):
            return _menu_degraded_fallback(exc, source="replica_outage")
        logger.exception("[MENU] build_menu_response failed; using degraded fallback")
        return _menu_degraded_fallback(exc, source="unexpected_error")
