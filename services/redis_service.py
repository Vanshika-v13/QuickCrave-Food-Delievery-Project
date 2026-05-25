import os
import redis
import time
import logging

logger = logging.getLogger(__name__)

redis_client = None

def init_redis():
    global redis_client

    REDIS_URL = os.getenv("REDIS_URL")

    if not REDIS_URL:
        logger.warning("[REDIS] No REDIS_URL found, running without cache")
        return None

    retries = 3
    delay = 1

    for attempt in range(retries):
        try:
            redis_client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_timeout=1,
                socket_connect_timeout=1,
                retry_on_timeout=True
            )

            redis_client.ping()
            logger.info("[REDIS] Connected successfully")
            return redis_client

        except Exception as e:
            logger.warning(f"[REDIS] Connection failed attempt {attempt+1}: {e}")
            time.sleep(delay)
            delay *= 2  # exponential backoff

    logger.error("[REDIS] Failed to connect after retries. Running without cache.")
    redis_client = None
    return None

def get_cache(key: str):
    if not redis_client:
        return None
    try:
        return redis_client.get(key)
    except Exception:
        return None

def set_cache(key: str, value, ttl: int = 300):
    if not redis_client:
        return
    try:
        redis_client.setex(key, ttl, value)
    except Exception:
        pass

def delete_cache(key: str):
    if not redis_client:
        return
    try:
        redis_client.delete(key)
    except Exception:
        pass
