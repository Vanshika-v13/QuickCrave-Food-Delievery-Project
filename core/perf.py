"""Request/query performance timing and slow-operation warnings."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Callable, Generator, Optional, TypeVar

logger = logging.getLogger(__name__)

SLOW_MS = 500

F = TypeVar("F", bound=Callable[..., Any])


class PerfTimer:
    def __init__(self, label: str):
        self.label = label
        self._t0 = time.perf_counter()
        self.mongo_ms = 0.0
        self.serialize_ms = 0.0

    @contextmanager
    def mongo(self) -> Generator[None, None, None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.mongo_ms += (time.perf_counter() - t0) * 1000

    @contextmanager
    def serialize(self) -> Generator[None, None, None]:
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.serialize_ms += (time.perf_counter() - t0) * 1000

    def finish(self) -> float:
        total_ms = (time.perf_counter() - self._t0) * 1000
        logger.info(
            "[PERF] %s completed in %.0fms (mongo=%.0fms, serialize=%.0fms)",
            self.label,
            total_ms,
            self.mongo_ms,
            self.serialize_ms,
        )
        if total_ms >= SLOW_MS:
            logger.warning(
                "[WARNING] Slow route: %s took %.0fms (mongo=%.0fms, serialize=%.0fms)",
                self.label,
                total_ms,
                self.mongo_ms,
                self.serialize_ms,
            )
        return total_ms


def log_slow_mongo(operation: str, elapsed_ms: float) -> None:
    if elapsed_ms >= SLOW_MS:
        logger.warning(
            "[WARNING] Slow Mongo query: %s took %.1fms", operation, elapsed_ms
        )


@contextmanager
def timed_mongo(operation: str) -> Generator[None, None, None]:
    t0 = time.perf_counter()
    try:
        yield
    finally:
        log_slow_mongo(operation, (time.perf_counter() - t0) * 1000)


def perf_route(route_name: str) -> Callable[[F], F]:
    """Log total wall time for a FastAPI handler (sync or async)."""

    def decorator(func: F) -> F:
        if hasattr(func, "__wrapped__"):
            # avoid double-wrap
            return func

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any):
            timer = PerfTimer(route_name)
            try:
                return await func(*args, **kwargs)
            finally:
                timer.finish()

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any):
            timer = PerfTimer(route_name)
            try:
                return func(*args, **kwargs)
            finally:
                timer.finish()

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator
