"""Short-lived in-memory TTL cache for expensive read endpoints."""

from __future__ import annotations

import time
from threading import Lock
from typing import Any, Callable, Dict, Optional, Tuple

_lock = Lock()
_store: Dict[str, Tuple[float, Any]] = {}

DEFAULT_TTL_SECONDS = 20


def get_cached(key: str) -> Optional[Any]:
    now = time.monotonic()
    with _lock:
        entry = _store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if now >= expires_at:
            _store.pop(key, None)
            return None
        return value


def set_cached(key: str, value: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    with _lock:
        _store[key] = (time.monotonic() + ttl_seconds, value)


def cached(key: str, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> Callable:
    """Decorator for sync functions returning cacheable dashboard data."""

    def decorator(fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            hit = get_cached(key)
            if hit is not None:
                return hit
            value = fn(*args, **kwargs)
            set_cached(key, value, ttl_seconds)
            return value

        return wrapper

    return decorator


def invalidate(key: str) -> None:
    with _lock:
        _store.pop(key, None)
