import os
import redis
import time
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
load_dotenv()

logger = logging.getLogger(__name__)

redis_client = None


def _resolve_redis_url() -> str:
    url = (os.getenv("REDIS_URL") or os.getenv("REDIS_URI") or "").strip()
    if not url:
        url = "redis://127.0.0.1:6379/0"
        logger.warning("[REDIS] REDIS_URL not set — using default %s", url)
    return url


def init_redis():
    global redis_client

    redis_url = _resolve_redis_url()
    safe_log = redis_url.split("@")[-1] if "@" in redis_url else redis_url
    logger.info("[REDIS] Connecting to %s", safe_log)

    retries = 3
    delay = 1

    for attempt in range(retries):
        try:
            redis_client = redis.from_url(
                redis_url,
                decode_responses=True,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            redis_client.ping()
            logger.info("[REDIS] Connected successfully")
            return redis_client
        except Exception as e:
            logger.warning("[REDIS] Connection failed attempt %s: %s", attempt + 1, e)
            time.sleep(delay)
            delay *= 2

    logger.error(
        "[REDIS] Failed to connect after retries. Cart will use in-memory fallback (not shared across workers)."
    )
    redis_client = None
    return None


def get_cache(key: str):
    if not redis_client:
        return None
    try:
        return redis_client.get(key)
    except Exception as e:
        logger.warning("[REDIS] get_cache failed key=%s: %s", key, e)
        return None


def set_cache(key: str, value, ttl: int = 300) -> bool:
    if not redis_client:
        return False
    try:
        redis_client.setex(key, ttl, value)
        return True
    except Exception as e:
        logger.warning("[REDIS] set_cache failed key=%s: %s", key, e)
        return False


def delete_cache(key: str) -> bool:
    if not redis_client:
        return False
    try:
        redis_client.delete(key)
        return True
    except Exception as e:
        logger.warning("[REDIS] delete_cache failed key=%s: %s", key, e)
        return False
