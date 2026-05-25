"""
Central PyMongo client — sole database access for the application runtime.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

try:
    from pymongo import MongoClient, ReadPreference
    from pymongo.collection import Collection
    from pymongo.database import Database
except ImportError:
    logger.error("PyMongo is not installed. Run: pip install pymongo")
    raise

MONGODB_URI = (os.getenv("MONGODB_URI") or "").strip()
MONGODB_DATABASE = (os.getenv("MONGODB_DATABASE") or "food_delivery").strip()

_client: Optional[MongoClient] = None
_db: Optional[Database] = None
_last_connect_mode: str = "unknown"


def is_transient_replica_error(exc: BaseException) -> bool:
    """True when the cluster has no primary or server selection is timing out."""
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    needles = (
        "replicasetnoprimary",
        "no primary",
        "not primary",
        "not master",
        "serverselectiontimeout",
        "serverselection",
        "server selection",
        "topologydescription",
    )
    return any(n in msg or n in name for n in needles)


def get_last_connect_mode() -> str:
    return _last_connect_mode


def log_replica_set_debug(client: MongoClient, *, context: str = "") -> None:
    """Temporary ops logging — replica member roles and states."""
    prefix = f"[MONGODB][REPLICA_DEBUG]{f'[{context}]' if context else ''}"
    try:
        status = client.admin.command("replSetGetStatus")
        members = status.get("members") or []
        primary = [m for m in members if m.get("stateStr") == "PRIMARY"]
        secondary = [m for m in members if m.get("stateStr") == "SECONDARY"]
        unknown = [m for m in members if m.get("stateStr") not in ("PRIMARY", "SECONDARY")]
        logger.info(
            "%s primary_detected=%s secondary_count=%s unknown_count=%s members=%s",
            prefix,
            bool(primary),
            len(secondary),
            len(unknown),
            [(m.get("name"), m.get("stateStr")) for m in members[:8]],
        )
    except Exception as exc:
        logger.warning("%s replSetGetStatus unavailable: %s", prefix, exc)


def _create_client() -> MongoClient:
    return MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=int(
            os.getenv("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000")
        ),
        connectTimeoutMS=int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "5000")),
        readPreference="secondaryPreferred",
        retryReads=True,
    )


def _verify_client_connectivity(client: MongoClient) -> str:
    """
    Ping the cluster. Prefer primary; fall back to secondary when no primary exists.
    Returns connect mode label: primary_ok | secondary_ok | degraded.
    """
    global _last_connect_mode
    try:
        client.admin.command("ping")
        _last_connect_mode = "primary_ok"
        logger.info("[MONGODB] Connected database=%s mode=primary_ok", MONGODB_DATABASE)
        return _last_connect_mode
    except Exception as primary_exc:
        if not is_transient_replica_error(primary_exc):
            raise
        logger.warning(
            "[MONGODB] Primary unavailable (%s); attempting secondary read fallback",
            primary_exc,
        )
        log_replica_set_debug(client, context="primary_absent")

    try:
        client.admin.command("ping", read_preference=ReadPreference.SECONDARY_PREFERRED)
        _last_connect_mode = "secondary_ok"
        logger.info(
            "[MONGODB] Connected database=%s mode=secondary_ok (read fallback)",
            MONGODB_DATABASE,
        )
        return _last_connect_mode
    except Exception as secondary_exc:
        _last_connect_mode = "degraded"
        logger.warning(
            "[MONGODB] Degraded mode database=%s — client kept for read retries: %s",
            MONGODB_DATABASE,
            secondary_exc,
        )
        log_replica_set_debug(client, context="degraded")
        return _last_connect_mode


def reset_client() -> None:
    """Drop cached client so the next get_client() reconnects (menu read retries)."""
    global _client, _db
    if _client is not None:
        try:
            _client.close()
        except Exception:
            pass
    _client = None
    _db = None


def get_client() -> MongoClient:
    global _client
    if not MONGODB_URI:
        raise RuntimeError("MONGODB_URI is required. MySQL has been removed from this application.")
    if _client is None:
        client = _create_client()
        try:
            _verify_client_connectivity(client)
        except Exception as exc:
            err = str(exc).lower()
            if "authentication failed" in err or "bad auth" in err:
                try:
                    client.close()
                except Exception:
                    pass
                raise RuntimeError(
                    "MongoDB authentication failed. Verify Atlas user, password, "
                    "readWrite on food_delivery, and IP whitelist."
                ) from exc
            if is_transient_replica_error(exc):
                logger.warning(
                    "[MONGODB] Transient cluster error at connect; keeping client for reads: %s",
                    exc,
                )
                _last_connect_mode = "degraded"
                _client = client
                return _client
            try:
                client.close()
            except Exception:
                pass
            raise RuntimeError(f"MongoDB connection failed: {exc}") from exc
        _client = client
    return _client


def get_database() -> Database:
    global _db
    if _db is None:
        _db = get_client()[MONGODB_DATABASE]
    return _db


def get_collection(name: str) -> Collection:
    return get_database()[name]


def read_with_retry(
    operation: str,
    fn,
    *,
    max_attempts: int = 2,
    retry_delay_s: float = 0.35,
):
    """
    Run a read callable with limited retries on replica / selection errors.
    Used by menu reads only.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if not is_transient_replica_error(exc) or attempt >= max_attempts:
                logger.warning(
                    "[MONGODB][%s] read failed attempt=%s/%s mode=%s error=%s",
                    operation,
                    attempt,
                    max_attempts,
                    get_last_connect_mode(),
                    exc,
                )
                raise
            logger.warning(
                "[MONGODB][%s] transient error attempt=%s/%s — reset client: %s",
                operation,
                attempt,
                max_attempts,
                exc,
            )
            reset_client()
            time.sleep(retry_delay_s)
    if last_exc:
        raise last_exc
    raise RuntimeError(f"{operation} read failed")


def next_sequence(name: str) -> int:
    """Atomic integer sequences (user_id, order_id, address_id, ...)."""
    coll = get_collection("counters")
    doc = coll.find_one_and_update(
        {"_id": name},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    return int(doc["seq"])


def seed_sequence(name: str, minimum: int) -> None:
    """Ensure counter is at least `minimum` (used after MySQL migration)."""
    coll = get_collection("counters")
    coll.update_one(
        {"_id": name},
        {"$max": {"seq": int(minimum)}},
        upsert=True,
    )


def close_client() -> None:
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
