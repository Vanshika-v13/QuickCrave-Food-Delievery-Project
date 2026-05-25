"""
MongoDB Atlas connection layer — Phase 1 (dual-database mode).

MongoDB Atlas is the sole application database. Sync data access uses repositories/mongo_client.py.
This module only manages Motor client lifecycle, health checks, and collection access.

Environment:
  MONGODB_URI       — Atlas connection string (required to enable MongoDB)
  MONGODB_DATABASE  — Database name (default: food_delivery)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MONGODB_URI: str = (os.getenv("MONGODB_URI") or "").strip()
MONGODB_DATABASE: str = (os.getenv("MONGODB_DATABASE") or "food_delivery").strip()

# Render-friendly timeouts: fail fast instead of blocking startup indefinitely
MONGODB_SERVER_SELECTION_TIMEOUT_MS = int(
    os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000")
)
MONGODB_CONNECT_TIMEOUT_MS = int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "5000"))

_motor_client: Optional[Any] = None
_database: Optional[Any] = None

_connection_state: dict[str, Any] = {
    "configured": False,
    "connected": False,
    "database_name": None,
    "last_error": None,
    "last_ping_ms": None,
}


def is_mongodb_configured() -> bool:
    """True when MONGODB_URI is set (MongoDB layer is intended to be used)."""
    return bool(MONGODB_URI)


def is_mongodb_connected() -> bool:
    return bool(_connection_state.get("connected"))


def get_connection_status() -> dict[str, Any]:
    """
    Safe status snapshot for health endpoints and ops dashboards.
    Never exposes credentials or full URI.
    """
    return {
        "configured": _connection_state["configured"],
        "connected": _connection_state["connected"],
        "database": _connection_state["database_name"],
        "last_error": _connection_state["last_error"],
        "last_ping_ms": _connection_state["last_ping_ms"],
    }


def get_database():
    """
    Return the active Motor database handle, or None if not connected.
    Phase 3+ services should use this only after verifying is_mongodb_connected().
    """
    return _database


def get_collection(name: str):
    """Convenience accessor for a collection on the active database."""
    if _database is None:
        return None
    return _database[name]


async def init_mongodb() -> bool:
    """
    Initialize MongoDB client and verify connectivity with ping.
    Returns True on success, False when skipped or failed.
    Does not raise — startup must remain safe when Atlas is unavailable.
    """
    global _motor_client, _database

    _connection_state["configured"] = is_mongodb_configured()
    _connection_state["database_name"] = MONGODB_DATABASE if is_mongodb_configured() else None

    if not is_mongodb_configured():
        logger.info("[MONGODB] Not configured (MONGODB_URI unset).")
        return False

    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError as exc:
        _connection_state["last_error"] = f"motor not installed: {exc}"
        logger.warning(
            "[MONGODB] motor package missing. Install with: pip install motor."
        )
        return False

    try:
        _motor_client = AsyncIOMotorClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=MONGODB_SERVER_SELECTION_TIMEOUT_MS,
            connectTimeoutMS=MONGODB_CONNECT_TIMEOUT_MS,
            readPreference="secondaryPreferred",
            retryReads=True,
        )
        _database = _motor_client[MONGODB_DATABASE]

        import time

        start = time.perf_counter()
        await _motor_client.admin.command("ping")
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)

        _connection_state["connected"] = True
        _connection_state["last_error"] = None
        _connection_state["last_ping_ms"] = elapsed_ms

        logger.info(
            "[MONGODB] Connected to database=%s ping_ms=%s",
            MONGODB_DATABASE,
            elapsed_ms,
        )
        return True
    except Exception as exc:
        _connection_state["connected"] = False
        _connection_state["last_error"] = str(exc)
        _motor_client = None
        _database = None
        logger.warning("[MONGODB] Connection failed: %s", exc)
        return False


async def close_mongodb() -> None:
    """Graceful shutdown — call from FastAPI shutdown handler."""
    global _motor_client, _database

    if _motor_client is not None:
        try:
            _motor_client.close()
            logger.info("[MONGODB] Client closed.")
        except Exception as exc:
            logger.warning("[MONGODB] Error during client close: %s", exc)

    _motor_client = None
    _database = None
    _connection_state["connected"] = False


async def check_mongodb_health() -> dict[str, Any]:
    """
    Runtime health check (re-ping). Used by /api/health and ops monitoring.
    """
    status = get_connection_status()

    if not status["configured"]:
        status["healthy"] = None  # not applicable
        return status

    if _motor_client is None:
        status["healthy"] = False
        return status

    try:
        import time

        start = time.perf_counter()
        await _motor_client.admin.command("ping")
        status["last_ping_ms"] = round((time.perf_counter() - start) * 1000, 2)
        status["healthy"] = True
        status["connected"] = True
        _connection_state["connected"] = True
        _connection_state["last_error"] = None
        _connection_state["last_ping_ms"] = status["last_ping_ms"]
    except Exception as exc:
        status["healthy"] = False
        status["connected"] = False
        status["last_error"] = str(exc)
        _connection_state["connected"] = False
        _connection_state["last_error"] = str(exc)

    return status
