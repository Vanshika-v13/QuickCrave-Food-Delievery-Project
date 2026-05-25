import re

with open('c:/Food Chatbot/main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace the block
old_block = '''# --- Redis Integration (Hardened Startup) ---
import os

REDIS_URL = os.getenv("REDIS_URL")

if REDIS_URL:
    try:
        redis_client = redis.from_url(
            REDIS_URL, 
            decode_responses=True, 
            socket_timeout=0.5, 
            socket_connect_timeout=0.5
        )
        redis_client.ping()
        logger.info("[REDIS] Connection established.")
    except Exception as e:
        redis_client = None
        logger.warning(f"Redis disabled - running in degraded mode: {e}")
else:
    redis_client = None
    logger.warning("Redis disabled - no REDIS_URL found")'''

new_block = '''# --- Redis Integration (Hardened Startup) ---
from services import redis_service
from services.redis_service import init_redis, get_cache, set_cache'''

content = content.replace(old_block, new_block)

# Remove 'import redis' at top if exists
content = content.replace('import redis\n', '')

# Find and replace redis_client.get(...) -> get_cache(...)
content = re.sub(r'redis_client\.get\((.*?)\)', r'get_cache(\1)', content)
# Be careful with redis_client.set, it might use ex=3600
content = re.sub(r'redis_client\.set\((.*?),\s*(.*?),\s*ex=(.*?)\)', r'set_cache(\1, \2, \3)', content)
content = re.sub(r'redis_client\.set\((.*?),\s*(.*?)\)', r'set_cache(\1, \2)', content)

# Replace other usages of redis_client with redis_service.redis_client
content = re.sub(r'\bredis_client\b', 'redis_service.redis_client', content)

# Hook up init_redis to startup
startup_old = '''@app.on_event("startup")
async def startup_event():
    """Safe Startup Wrapper."""
    try:
        logger.info("[SERVER] Initializing services...")'''

startup_new = '''@app.on_event("startup")
async def startup_event():
    """Safe Startup Wrapper."""
    init_redis()
    try:
        logger.info("[SERVER] Initializing services...")'''

content = content.replace(startup_old, startup_new)

with open('c:/Food Chatbot/main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print('Modified main.py')

# Also modify order_repository.py
with open('c:/Food Chatbot/repositories/order_repository.py', 'r', encoding='utf-8') as f:
    content_repo = f.read()

repo_old = '''def _clear_rider_redis(rider_id: int) -> None:
    try:
        import redis
        import os

        REDIS_URL = os.getenv("REDIS_URL")
        if not REDIS_URL:
            return

        r = redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_timeout=0.3,
        )
        r.delete(f"rider_last_known:{rider_id}")
        r.delete(f"rider_throttle:{rider_id}")
    except Exception:
        pass'''

repo_new = '''def _clear_rider_redis(rider_id: int) -> None:
    from services.redis_service import delete_cache
    delete_cache(f"rider_last_known:{rider_id}")
    delete_cache(f"rider_throttle:{rider_id}")'''

content_repo = content_repo.replace(repo_old, repo_new)

with open('c:/Food Chatbot/repositories/order_repository.py', 'w', encoding='utf-8') as f:
    f.write(content_repo)

print('Modified order_repository.py')
