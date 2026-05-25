import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.websockets import WebSocketState
import mongodb_helper
print("[DEBUG] mongodb_helper imported")
from services import (
    admin_service,
    address_service,
    auth_service,
    cart_service,
    chatbot_service,
    food_service,
    order_service,
    rider_service,
    user_service,
)
from services.order_lifecycle import normalize_status_internal, is_admin_allowed_status
print("[DEBUG] services imported")
import generic_helper
print("[DEBUG] generic_helper imported")
import asyncio
import httpx
from pydantic import BaseModel
from typing import List, Optional
import jwt
from datetime import datetime, timezone, timedelta
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
import hashlib
import base64
from passlib.context import CryptContext
from fastapi.staticfiles import StaticFiles
import time
import math
from collections import defaultdict
import re
import json
import bcrypt
import traceback
import inspect

# --- FEATURE FLAGS ---
ENABLE_NEARBY_FEATURE = False
# --- Redis Integration (Hardened Startup) ---
from services import redis_service
from services.redis_service import init_redis, get_cache, set_cache
    
import os
logger.info(f"[DEBUG] MONGODB_DATABASE from env: {os.getenv('MONGODB_DATABASE', 'food_delivery')}")

# --- GPS Throttling & WebSocket Deduplication Cache ---
# Note: These are now STRICTLY Redis-backed. If Redis is down, these features are disabled
# to ensure multi-worker consistency.
rider_last_pos = {} # Local process fallback ONLY for critical smoothing, not for cross-process throttling
last_payloads = {}  # Local process fallback ONLY to prevent local loop spam

# --- GPS Smoothing Config ---
# Store last 3 points for moving average: {rider_id: [(lat, lng), ...]}
rider_gps_history = defaultdict(list)

# --- Dialogflow: session cart (session_id -> {item_id: {item_id, name, quantity, price}}) ---
inprogress_orders = defaultdict(dict)
# Pending orders: session_id -> {"item": "food_name"} waiting for quantity confirmation
pending_orders: dict = {}
chatbot_session_users = {}  # session_id -> (user_id, expires_at) or {user_id, email, expires_at}
chatbot_user_last_link = {}  # user_id -> (canonical_session_id, expires_at)
CHATBOT_SESSION_TTL = 86400
# Prevents re-entrant session linking (_safe_link_chatbot_session).
_chatbot_session_linking_in_progress = set()

CHATBOT_ORDER_STATUS_MESSAGES = {
    "PLACED": "Your order has been placed.",
    "CONFIRMED": "Restaurant confirmed your order.",
    "READY": "Your food is ready.",
    "ASSIGNED": "A rider has been assigned.",
    "PICKED_UP": "Your food has been picked up.",
    "ON_WAY": "Your order is on the way.",
    "ARRIVING": "Your rider is arriving.",
    "DELIVERED": "Your order has been delivered.",
}

def calculate_distance(lat1, lon1, lat2, lon2):
    """Haversine formula to calculate distance between two points in meters."""
    R = 6371000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c
 
# --- Rate Limiting Middleware ---
RATE_LIMIT_DURATION = 60  # 1 minute
RATE_LIMIT_REQUESTS = 100 # requests per minute
user_request_counts = defaultdict(list)

async def rate_limit_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    
    # Clean up old requests
    user_request_counts[client_ip] = [t for t in user_request_counts[client_ip] if now - t < RATE_LIMIT_DURATION]
    
    if len(user_request_counts[client_ip]) >= RATE_LIMIT_REQUESTS:
        return JSONResponse(status_code=429, content={"detail": "Too many requests. Please try again later."})
    
    user_request_counts[client_ip].append(now)
    return await call_next(request)

# Configure Password Hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str):
    pwd_bytes = password.encode('utf-8')
    sha256_hash = hashlib.sha256(pwd_bytes).digest()
    pre_hashed = base64.b64encode(sha256_hash).decode('utf-8')
    # Use bcrypt directly to bypass passlib 72-byte limit bug
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pre_hashed.encode('utf-8'), salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str):
    if not hashed_password:
        return False
    try:
        pwd_bytes = plain_password.encode('utf-8')
        sha256_hash = hashlib.sha256(pwd_bytes).digest()
        pre_hashed = base64.b64encode(sha256_hash).decode('utf-8')
        
        # Use bcrypt directly to bypass passlib version issues
        return bcrypt.checkpw(pre_hashed.encode('utf-8'), hashed_password.encode('utf-8'))
    except Exception as e:
        logger.error(f"Password verification error: {e}")
        # Fallback to passlib if direct bcrypt fails (legacy hashes)
        try:
            return pwd_context.verify(pre_hashed, hashed_password)
        except:
            return False

import os
from dotenv import load_dotenv

load_dotenv()

# Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "734567890123-abcdefghijklmnopqrstuvwxyz123456.apps.googleusercontent.com")
JWT_SECRET = os.getenv("JWT_SECRET", "your_super_secret_key_change_this")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRATION_MINUTES = int(os.getenv("JWT_EXPIRATION_MINUTES", 60))
JWT_REFRESH_EXPIRATION_DAYS = 7

# --- COORDINATE CONSTANTS & FALLBACKS (HARDENING) ---
RESTAURANT_LAT = 28.6304
RESTAURANT_LNG = 77.2177
DEFAULT_USER_LAT = 28.6484
DEFAULT_USER_LNG = 77.2397

def create_jwt_token(user_id: int, email: str, roles: List[str] = ["customer"]):
    expiration = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRATION_MINUTES)
    payload = {
        "user_id": user_id,
        "email": email,
        "roles": roles,
        "exp": expiration
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def validate_coordinates(lat, lng):
    if lat is None or lng is None:
        return False
    return -90 <= float(lat) <= 90 and -180 <= float(lng) <= 180

async def get_token_from_websocket(websocket: WebSocket):
    # Try to get token from query params or headers
    token = websocket.query_params.get("token")
    if not token:
        # Some clients send token in subprotocols
        auth_header = websocket.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
    
    if not token:
        return None
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        # Expired token is a DISTINCT failure — sentinel allows caller to close with code 4001
        # (not 1008) so the frontend can stop reconnect loops instead of retrying forever.
        logger.warning("[WS_AUTH][EXPIRED_TOKEN] JWT has expired")
        return "EXPIRED"
    except Exception as e:
        logger.warning(f"[WS_AUTH][INVALID_TOKEN] WS Auth failed: {e}")
        return None

from enum import Enum

class Role(str, Enum):
    CUSTOMER = "customer"
    ADMIN = "admin"
    RIDER = "rider"

class OrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    READY = "READY"
    ASSIGNED = "ASSIGNED"
    PICKED_UP = "PICKED_UP"
    ON_WAY = "ON_WAY"
    ARRIVING = "ARRIVING"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"

def standard_response(success: bool, message: str, data: any = None):
    return {"success": success, "message": message, "data": data}

security = HTTPBearer()

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: int = payload.get("user_id")
        email: str = payload.get("email")
        roles: List[str] = payload.get("roles", ["customer"])
        
        if user_id is None or email is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
            
        # Production-grade: Always verify user existence and active status in DB
        db_user = user_service.get_user_by_id(user_id)
        if not db_user:
            raise HTTPException(status_code=401, detail="User no longer exists")
        
        if not db_user.get("is_active", 1):
            raise HTTPException(status_code=403, detail="Account is disabled. Please contact support.")

        return {"user_id": user_id, "email": email, "roles": roles}
    except (jwt.PyJWTError, AttributeError, Exception) as e:
        # Check for expired token
        if "expired" in str(e).lower():
            raise HTTPException(status_code=401, detail="Token has expired")
        raise HTTPException(status_code=401, detail="Could not validate credentials")
    except Exception as e:
        logger.error(f"Unexpected auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")

def require_roles(allowed_roles: List[str]):
    """Generic RBAC middleware factory."""
    def role_checker(current_user: dict = Depends(get_current_user)):
        user_roles = current_user.get("roles", [])
        # Check if user has ANY of the allowed roles
        if not any(role in user_roles for role in allowed_roles):
            logger.warning(f"[SECURITY] Access denied for {current_user.get('email')} with roles {user_roles}. Required: {allowed_roles}")
            raise HTTPException(
                status_code=403, 
                detail=f"Access denied. Required roles: {', '.join(allowed_roles)}"
            )
        return current_user
    return role_checker

# Centralized Role Dependencies
admin_required = require_roles(["admin"])
rider_required = require_roles(["rider"])


def _normalize_token_roles(raw_roles) -> List[str]:
    if raw_roles is None:
        return ["customer"]
    if isinstance(raw_roles, str):
        return [raw_roles]
    return list(raw_roles)


async def get_admin_from_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """JWT-only admin check for read-heavy admin routes (skips per-request Mongo lookup)."""
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("user_id")
        email = payload.get("email")
        roles = _normalize_token_roles(payload.get("roles", ["customer"]))
        if user_id is None or email is None:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        if "admin" not in roles:
            raise HTTPException(status_code=403, detail="Access denied. Admin only.")
        return {"user_id": user_id, "email": email, "roles": roles}
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Could not validate credentials")


admin_read_required = get_admin_from_token
customer_required = require_roles(["customer"])

# ---------------------------------------------------------------------------
# ECOSYSTEM SOCKET MANAGER (Hardened Room-Based Architecture)
# ---------------------------------------------------------------------------
class EcosystemSocketManager:
    def __init__(self):
        self.rooms: dict[str, list[WebSocket]] = {}
        # Track last broadcasted position per order for deduplication: {order_id: (lat, lng)}
        self.last_broadcast_pos: dict[int, tuple[float, float]] = {}
    async def connect(self, room: str, websocket: WebSocket, user_id: int = None) -> None:
        """
        Hardened Connect:
        1. Prevents duplicate registrations for the same user in the same room.
        2. Ensures clean state before adding new socket.
        3. Initializes heartbeat tracking.
        """
        if room not in self.rooms:
            self.rooms[room] = []

        # 🔥 TASK 4: Initialize heartbeat tracking
        setattr(websocket, "last_ping_time", time.time())

        # If user_id is provided, kick old connections for this user in this room
        if user_id:
            setattr(websocket, "user_id", user_id) # Attach for future reference
            old_sockets = [ws for ws in self.rooms[room] if getattr(ws, "user_id", None) == user_id]
            for old_ws in old_sockets:
                logger.info(f"[WS] Removing duplicate connection for user {user_id} in room {room}")
                self.disconnect(room, old_ws)

        if websocket not in self.rooms[room]:
            self.rooms[room].append(websocket)
            
            # Track active session in Redis
            if redis_service.redis_client:
                try:
                    redis_service.redis_client.sadd(f"active_rooms:{room}", str(id(websocket)))
                except Exception as e:
                    logger.warning(f"[REDIS] Failed to track presence: {e}")
                
            logger.info(f"[WS] Room '{room}' joined. Total in room: {len(self.rooms[room])}")

    def disconnect(self, room: str, websocket: WebSocket) -> None:
        """
        Hardened Disconnect:
        1. Removes websocket from room.
        2. Deletes stale references.
        3. Cleans up Redis state.
        """
        if room in self.rooms and websocket in self.rooms[room]:
            self.rooms[room].remove(websocket)
            
            if redis_service.redis_client:
                try:
                    redis_service.redis_client.srem(f"active_rooms:{room}", str(id(websocket)))
                except:
                    pass
                    
            if not self.rooms[room] and room != "admin_monitor":
                del self.rooms[room]
                if redis_service.redis_client:
                    try:
                        redis_service.redis_client.delete(f"active_rooms:{room}")
                    except:
                        pass
        logger.info(f"[WS] Room '{room}' left.")

    async def _safe_send(self, ws: WebSocket, payload: dict, room: str) -> bool:
        """
        Send once, fail fast for closed sockets.
        Returns True if successful, False if dead.
        """
        if ws.client_state != WebSocketState.CONNECTED:
            return False
        try:
            await asyncio.wait_for(ws.send_json(payload), timeout=2.5)
            return True
        except Exception as e:
            logger.warning(f"[WS][SEND_FAIL] Room {room}: {e}")
            return False

    def _remove_websocket_from_all_rooms(self, ws: WebSocket) -> None:
        """Drop a dead socket from every room immediately (no retries)."""
        for r_name, r_ws_list in list(self.rooms.items()):
            if ws in r_ws_list:
                self.disconnect(r_name, ws)

    async def broadcast(self, room: str, payload: dict) -> None:
        """
        Hardened Broadcast:
        1. Copies room list to avoid mutation during loop.
        2. Checks connection state before sending.
        3. Retries on transient failure.
        4. Removes dead sockets safely AFTER loop.
        """
        payload_str = json.dumps(payload, sort_keys=True)
        
        # Deduplication using Redis
        if redis_service.redis_client:
            try:
                last_p = get_cache(f"last_payload:{room}")
                if last_p == payload_str:
                    return
                set_cache(f"last_payload:{room}", payload_str, 3600)
            except Exception as e:
                logger.warning(f"[REDIS] Broadcast deduplication failed: {e}")
                if last_payloads.get(room) == payload_str:
                    return
                last_payloads[room] = payload_str
        else:
            if last_payloads.get(room) == payload_str:
                return
            last_payloads[room] = payload_str

        # 🔥 TASK 2: ALWAYS iterate over a COPY of sockets
        room_sockets = self.rooms.get(room, [])
        if not room_sockets:
            return
            
        sockets_snapshot = list(room_sockets)
        
        # Collect admin monitors if this is a customer tracking room
        if room.startswith("customer_") and "admin_monitor" in self.rooms:
            sockets_snapshot.extend(list(self.rooms["admin_monitor"]))

        for ws in sockets_snapshot:
            if ws.client_state != WebSocketState.CONNECTED:
                self._remove_websocket_from_all_rooms(ws)
                continue

            success = await self._safe_send(ws, payload, room)
            if not success:
                self._remove_websocket_from_all_rooms(ws)

    async def broadcast_global(self, payload: dict) -> None:
        """Broadcasts payload to all connected rooms."""
        for room_name in list(self.rooms.keys()):
            await self.broadcast(room_name, payload)

    async def push_order_update(self, order_id: int, driver_lat: float = None, driver_lng: float = None) -> None:
        """
        Hardened broadcast: ensuring order_id, status, and rider_id are authoritative.
        Rule: NEVER use undefined variables. ALWAYS fetch from DB inside function.
        """
        try:
            logger.info(f"[ORDER_ASSIGN][WS_BROADCAST] Starting for order_id={order_id}")
            # 1. Authoritative DB Fetch (FIX 3)
            # db_helper.get_order_by_id now uses a fresh connection for total authority
            order = order_service.get_order_by_id(order_id)
            if not order:
                logger.warning(f"[WS] Order not found: {order_id}")
                return

            # AUTHORITATIVE NORMALIZATION (FIX 4)
            db_status = order.get("status")
            current_status = normalize_status_internal(db_status)
            rider_id = order.get("rider_id")
            
            logger.info(f"[WS][DB_STATE] order_id={order_id} db_status={db_status} normalized={current_status}")

            order_summary = order_service.get_order_summary(order_id) or {}
            rider_data = order_summary.get("rider")
            rider_location_flat = order_summary.get("rider_location")
            dl_ws = order_summary.get("delivery_location") or {}
            logger.info(
                f"[TRACK_ORDER_WS] order_id={order_id} "
                f"delivery_lat={dl_ws.get('latitude')} delivery_lng={dl_ws.get('longitude')}"
            )

            # 3. Payload Construction (BACKWARD COMPATIBLE)
            updated_at = datetime.now(timezone.utc).isoformat()
            
            payload = {
                "event": "ORDER_UPDATE",
                "order_id": order_id,
                "status": current_status,
                "rider_id": rider_id,
                "rider": rider_data,
                "rider_location": rider_location_flat,
                "updated_at": updated_at,
                "version": order_summary.get("version", 1),
                "estimated_total_minutes": order_summary.get("estimated_total_minutes", 45),
                "remaining_minutes": order_summary.get("remaining_minutes", 0),
                "remaining_seconds": order_summary.get("remaining_seconds", 0),
                "eta_text": order_summary.get("eta_text", "0 min left"),
                "data": order_summary
            }
            
            await self._execute_push(order_id, payload)
            logger.info(f"[WS][ORDER_UPDATE_SENT] order_id={order_id} status={current_status}")

        except Exception as e:
            logger.error(f"[WS][CRITICAL] push_order_update failed: {e}")

    async def push_order_removed(self, order_id: int) -> None:
        """Notify admin, tracking customers, and all online riders that an order was removed."""
        try:
            payload = {
                "event": "ORDER_REMOVED",
                "order_id": order_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            await self.broadcast("admin_monitor", payload)
            await self.broadcast(f"customer_{order_id}", payload)
            for room_name in list(self.rooms.keys()):
                if room_name.startswith("rider_"):
                    await self.broadcast(room_name, payload)
            logger.info(f"[WS][ORDER_REMOVED] Broadcast complete for order_id={order_id}")
        except Exception as e:
            logger.error(f"[WS][ORDER_REMOVED] Broadcast failed order_id={order_id}: {e}")

    async def push_rider_status_update(self, rider_id: int, rider_status: str = None, lat: float = None, lng: float = None, heading: float = None) -> None:
        """Broadcast rider status/location update globally."""
        rider_state = rider_service.get_rider_realtime_state(rider_id) or {"rider_id": rider_id}
        payload = {
            "event": "RIDER_STATUS_UPDATE",
            "rider_id": rider_id,
            "rider_status": rider_status or rider_state.get("rider_status"),
            "lat": lat if lat is not None else rider_state.get("lat"),
            "lng": lng if lng is not None else rider_state.get("lng"),
            "heading": heading if heading is not None else rider_state.get("heading", 0),
            "updated_at": rider_state.get("updated_at") or datetime.now(timezone.utc).isoformat(),
            "version": rider_state.get("version", 0)
        }
        await self.broadcast_global(payload)

    async def _execute_push(self, order_id: int, payload: dict) -> None:
        """Internal helper to broadcast to all relevant rooms."""
        # Broadcast to customer room
        await self.broadcast(f"customer_{order_id}", payload)
        
        # Broadcast to assigned rider room
        # We fetch this from payload instead of DB for consistency during this push
        rider_id = payload.get("rider_id")
        if rider_id:
            await self.broadcast(f"rider_{rider_id}", payload)
        
        # Admin Monitor always gets full view
        await self.broadcast("admin_monitor", payload)


ecosystem_socket_manager = EcosystemSocketManager()
print("[DEBUG] ecosystem_socket_manager initialized")

app = FastAPI()

app_state = {"ready": False}

_CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

prod_frontend_url = os.getenv("FRONTEND_URL")
if prod_frontend_url:
    _CORS_ALLOWED_ORIGINS.append(prod_frontend_url)


def _cors_preflight_response(request: Request) -> Response:
    """200 for OPTIONS preflight — mirrors requested headers (incl. cache-control from axios)."""
    origin = request.headers.get("origin", "")
    headers = {
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
        "Access-Control-Max-Age": "86400",
    }
    if origin in _CORS_ALLOWED_ORIGINS:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
        requested = request.headers.get("access-control-request-headers")
        headers["Access-Control-Allow-Headers"] = requested or "*"
    elif not origin:
        headers["Access-Control-Allow-Headers"] = "*"
    return Response(status_code=200, headers=headers)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "[GLOBAL_ERROR] %s %s",
        request.method,
        request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Internal server error"},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict):
        error_msg = detail.get("message") or detail.get("error") or str(detail)
    else:
        error_msg = str(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": error_msg},
    )


@app.middleware("http")
async def check_ready(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    if request.url.path in ["/health", "/api/health", "/api/menu"]:
        return await call_next(request)
    if not app_state.get("ready"):
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": "Server warming up"},
        )
    return await call_next(request)


app.middleware("http")(rate_limit_middleware)


@app.middleware("http")
async def options_preflight_middleware(request: Request, call_next):
    """Outermost: OPTIONS never hits auth, rate limits, or route validation."""
    if request.method == "OPTIONS":
        return _cors_preflight_response(request)
    return await call_next(request)


if os.path.exists("frontend/public/images"):
    app.mount("/images", StaticFiles(directory="frontend/public/images"), name="images")
else:
    logger.warning("Static files directory 'frontend/public/images' does not exist. Image mounting skipped.")

# --- Health Check Endpoint (No Auth Required) ---
@app.get("/api/health")
async def health_check():
    """Lightweight liveness probe. Frontend uses this before WebSocket reconnect attempts."""
    mongo_status = await mongodb_helper.check_mongodb_health()
    return {
        "success": True,
        "status": "ok",
        "redis": redis_service.redis_client is not None,
        "mongodb": mongo_status,
    }

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "QuickCrave backend is running"
    }

@app.get("/health")
def health():
    return {"status": "healthy"}

# --- RIDER-DEPENDENT STATUSES ---
RIDER_DEPENDENT_STATUSES = {
    "PICKED_UP",
    "ON_WAY",
    "ARRIVING",
    "DELIVERED",
}

def is_rider_online(rider_id: int) -> bool:
    """MongoDB is source of truth; Redis WS set is secondary."""
    if not rider_id:
        return False
    from repositories import user_repository

    if user_repository.is_rider_online_db(rider_id):
        return True
    if redis_service.redis_client:
        return redis_service.redis_client.sismember("online_riders", str(rider_id))
    return False


def clear_order_broadcast_cache(order_id: int, rider_id: int = None) -> None:
    """Drop WS dedup keys so assignment/status events are not swallowed."""
    rooms = [f"customer_{order_id}", "admin_monitor"]
    if rider_id:
        rooms.append(f"rider_{rider_id}")
    for room in rooms:
        if redis_service.redis_client:
            try:
                redis_service.redis_client.delete(f"last_payload:{room}")
            except Exception:
                pass
        last_payloads.pop(room, None)


@app.on_event("startup")
async def startup_event():
    """Safe Startup Wrapper."""
    init_redis()
    try:
        logger.info("[SERVER] Initializing services...")
        from repositories.mongo_client import get_client
        from repositories import (
            food_repository,
            user_repository,
            cart_repository,
            address_repository,
            order_repository,
            rider_repository,
            admin_repository,
        )

        get_client()
        for repo_name, ensure_fn in (
            ("food", food_repository.ensure_indexes),
            ("user", user_repository.ensure_indexes),
            ("cart", cart_repository.ensure_indexes),
            ("address", address_repository.ensure_indexes),
            ("order", order_repository.ensure_indexes),
            ("rider", rider_repository.ensure_indexes),
            ("admin", admin_repository.ensure_indexes),
        ):
            try:
                ensure_fn()
            except Exception as idx_exc:
                logger.warning(
                    "[MONGODB] ensure_indexes(%s) skipped (degraded): %s",
                    repo_name,
                    idx_exc,
                )
        logger.info("[SERVER] MongoDB connected (sole database)")

        auth_service.ensure_default_admin(get_password_hash)

        await mongodb_helper.init_mongodb()
        
        app_state["ready"] = True
        logger.info("[SERVER] Backend ready on port 8000")
    except Exception as e:
        logger.error(f"[SERVER][CRITICAL] Startup failed safely handled: {e}")
        # We don't exit(1) to allow the process to stay alive for debugging/logs if possible

@app.on_event("shutdown")
async def shutdown_event():
    await mongodb_helper.close_mongodb()
    from repositories.mongo_client import close_client

    close_client()
    logger.info("[SYSTEM] Shutdown complete.")

# --- WebSockets ---
@app.websocket("/ws/track/{order_id}")
async def track_order_ws(websocket: WebSocket, order_id: int):
    await websocket.accept()
    active_rooms_for_connection = set()
    
    try:
        # 1. Authenticate WebSocket — distinguish expired vs invalid tokens
        payload = await get_token_from_websocket(websocket)

        if payload == "EXPIRED":
            logger.warning(f"[WS_AUTH][EXPIRED_TOKEN] order_id={order_id} — closing with 4001")
            await websocket.close(code=4001)
            return

        if not payload:
            logger.warning(f"[WS_AUTH][INVALID_TOKEN] order_id={order_id} — closing with 1008")
            await websocket.close(code=1008)
            return

        user_id: int = payload.get("user_id")
        user_roles: list = payload.get("roles", [])

        # 2. Validate role
        if not any(role in user_roles for role in ["customer", "admin", "rider"]):
            logger.warning(f"[WS SECURITY] Role denied for order {order_id}: roles={user_roles}")
            await websocket.close(code=1008)
            return

        # 3. Enforce order ownership
        if "admin" not in user_roles:
            if "rider" in user_roles:
                order_summary = order_service.get_order_summary(order_id)
                if not order_summary or not order_summary.get("rider") or order_summary["rider"].get("riderId") != user_id:
                     logger.warning(f"[WS SECURITY] Rider {user_id} tried to track unassigned order {order_id} — ACCESS DENIED")
                     await websocket.close(code=1008)
                     return
            else:
                ownership = order_service.validate_order_owner(order_id, user_id)
                if ownership == "ORDER_NOT_FOUND" or ownership == "ACCESS_DENIED":
                    logger.warning(f"[WS SECURITY] Access denied for order {order_id} user {user_id}")
                    await websocket.close(code=1008)
                    return

        logger.info(f"[WS_AUTH][SUCCESS] order_id={order_id} user_id={user_id}")
        room = f"customer_{order_id}"
        
        # 🔥 TASK 4: PREVENT DUPLICATE ROOM REGISTRATION
        if room not in active_rooms_for_connection:
            await ecosystem_socket_manager.connect(room, websocket, user_id=user_id)
            active_rooms_for_connection.add(room)
            
        await ecosystem_socket_manager.push_order_update(order_id)

        while True:
            # Check connection state
            if websocket.client_state.name != "CONNECTED":
                break
            
            # 🔥 TASK 4: Heartbeat / Idle Cleanup (60s)
            last_ping = getattr(websocket, "last_ping_time", 0)
            if time.time() - last_ping > 60:
                logger.warning(f"[WS] Disconnecting idle socket for order {order_id} (user {user_id})")
                break

            try:
                # Use timeout on receive to allow regular heartbeat checks
                data = await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
                if data == "ping":
                    setattr(websocket, "last_ping_time", time.time())
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                # Just a timeout on receive, loop again to check heartbeat
                continue
            except Exception:
                break

    except Exception as e:
        logger.error(f"[WS] Error: {e}")
    finally:
        for r in active_rooms_for_connection:
            ecosystem_socket_manager.disconnect(r, websocket)
        active_rooms_for_connection.clear()
        try:
            await websocket.close()
        except:
            pass

@app.websocket("/ws/admin")
async def admin_ws(websocket: WebSocket):
    await websocket.accept()
    active_rooms_for_connection = set()
    
    try:
        # Authenticate WebSocket and check for admin role
        payload = await get_token_from_websocket(websocket)
        if not payload or "admin" not in payload.get("roles", []):
            await websocket.close(code=1008)
            return

        room = "admin_monitor"
        admin_id = payload.get("user_id")
        
        if room not in active_rooms_for_connection:
            await ecosystem_socket_manager.connect(room, websocket, user_id=admin_id)
            active_rooms_for_connection.add(room)

        while True:
            if websocket.client_state.name != "CONNECTED":
                break
                
            # 🔥 TASK 4: Heartbeat / Idle Cleanup (60s)
            last_ping = getattr(websocket, "last_ping_time", 0)
            if time.time() - last_ping > 60:
                logger.warning(f"[ADMIN][WS] Disconnecting idle admin socket {admin_id}")
                break

            try:
                # Use timeout on receive to allow regular heartbeat checks
                data = await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
                if data == "ping":
                    setattr(websocket, "last_ping_time", time.time())
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                continue
            except Exception:
                break
                
    except Exception as e:
        logger.error(f"[ADMIN][WS] Error: {e}")
    finally:
        for r in active_rooms_for_connection:
            ecosystem_socket_manager.disconnect(r, websocket)
        active_rooms_for_connection.clear()
        try:
            await websocket.close()
        except:
            pass

# --- Dialogflow Webhook ---
@app.post("/")
async def handle_request(request: Request):
    # =====================================================================
    # PIPELINE STEP 1: Extract raw inputs — NO cart access, NO side effects
    # =====================================================================
    payload = await request.json()
    query_result = payload.get("queryResult", {})
    intent = query_result.get("intent", {}).get("displayName", "")
    parameters = query_result.get("parameters", {}) or {}
    output_contexts = query_result.get("outputContexts", []) or []
    logger.info(f"[CHATBOT][RAW_OUTPUT_CONTEXTS] {output_contexts}")
    logger.info(f"[CHATBOT][PARAMETERS_BEFORE] {parameters}")
    parameters["_output_contexts"] = output_contexts
    logger.info(f"[CHATBOT][PARAMETERS_AFTER] {parameters}")
    query_text = query_result.get("queryText", "").lower().strip()

    logger.info(f"[CHATBOT][PIPELINE] STEP1 raw_intent={intent!r} query={query_text!r}")

    # =====================================================================
    # PIPELINE STEP 2: Intent guard — food-only must NOT hit order.remove
    # Without remove/delete/cancel keywords, route to order.add (quantity flow).
    # =====================================================================
    logger.info(f"[CHATBOT][INTENT_BEFORE] {intent}")
    logger.info(f"[CHATBOT][QUERY] {query_text}")
    
    has_remove_words = _has_remove_keywords(query_text)
    
    if has_remove_words:
        q_clean = _REMOVE_KEYWORDS_RE.sub("", query_text).strip()
        matched_food = _chatbot_detect_food_in_text(q_clean)
        if not matched_food:
            matched_food = _chatbot_detect_food_in_text(query_text)
    else:
        matched_food = _chatbot_detect_food_in_text(query_text)

    if not matched_food:
        param_foods = _chatbot_extract_food_names(parameters)
        if param_foods:
            row = chatbot_service.get_food_item_by_name(param_foods[0])
            matched_food = row["name"] if row else param_foods[0]

    qty_detected = None
    if matched_food:
        qty_detected = _chatbot_explicit_remove_qty_for_food(query_text, matched_food)

    logger.info(
        f"[CHATBOT][REMOVE_FORCE_ROUTE] "
        f"query='{query_text}' "
        f"food_detected={matched_food} "
        f"qty_detected={qty_detected}"
    )

    is_remove_intent = bool(intent and str(intent).startswith("order.remove"))

    if matched_food and not has_remove_words:
        prev_intent = intent
        intent = _ADD_INTENT
        parameters["food-item"] = [matched_food]
        logger.info(
            f"[CHATBOT][FORCE_ROUTE] Food '{matched_food}' without remove keyword — "
            f"overriding intent '{prev_intent}' → order.add"
        )
    elif matched_food and has_remove_words and not is_remove_intent:
        prev_intent = intent
        intent = _REMOVE_INTENT
        parameters["food-item"] = [matched_food]
        logger.info(
            f"[CHATBOT][FORCE_ROUTE] Food '{matched_food}' with remove keyword — "
            f"overriding intent '{prev_intent}' → order.remove"
        )
    elif is_remove_intent and not has_remove_words:
        prev_intent = intent
        intent = _ADD_INTENT
        if matched_food:
            parameters["food-item"] = [matched_food]
        logger.info(
            f"[CHATBOT][FORCE_ROUTE] order.remove without remove/delete/cancel — "
            f"overriding '{prev_intent}' → order.add"
        )

    # Route completion phrases even when Dialogflow mis-classifies the intent.
    logger.info(f"[CHATBOT][COMPLETE_CHECK] query={query_text}")
    
    raw_contexts = query_result.get('outputContexts', []) or []
    has_ongoing_order_context = any("ongoing-order" in ctx.get("name", "").lower() for ctx in raw_contexts)
    
    if _is_complete_order_phrase(query_text) and has_ongoing_order_context:
        prev_intent = intent
        intent = "order.complete - context: ongoing-order"
        logger.info(f"[CHATBOT][INTENT_FORCED] {intent}")

    logger.info(f"[CHATBOT][PIPELINE] STEP2 resolved_intent={intent!r}")

    # =====================================================================
    # PIPELINE STEP 3: Session extraction — still NO cart access
    # =====================================================================
    # IMPORTANT: Use a deterministic session_id key so add/remove mutate the
    # same in-memory cart across turns. Prefer payload.session (authoritative),
    # but migrate any in-memory state previously stored under a contexts-derived
    # key to avoid "cosmetic" updates.
    query_result = payload.get("queryResult", {})
    session_full = payload.get("session", "")

    session_id = session_full.split("/")[-1] if session_full else ""

    if not session_id:
        output_contexts = query_result.get("outputContexts", [])
        if output_contexts:
            ctx_name = output_contexts[0].get("name", "")
            parts = ctx_name.split("/sessions/")
            if len(parts) > 1:
                session_id = parts[1].split("/")[0]

    logger.info(f"[CHATBOT][SESSION_ID] {session_id}")

    if not session_id:
        session_id = "default-session"

    session_id = _normalize_chatbot_session_id(session_id)

    _consolidate_chatbot_session_state(session_id)

    resolved_user, auth_source = _resolve_chatbot_auth_user(session_id, request, payload)
    jwt_present = _chatbot_jwt_present(request, payload)
    auth_decision = "ALLOW" if resolved_user else "BLOCK"

    logger.info(
        f"[CHAT_AUTH] jwt_present={jwt_present} dialogflow_session={session_id!r} "
        f"resolved_user_id={resolved_user} auth_source={auth_source} decision={auth_decision}"
    )
    logger.info(f"[CHATBOT][PIPELINE] STEP3 session_id={session_id} resolved_user_id={resolved_user}")

    # =====================================================================
    # PIPELINE STEP 3.5: Pending quantity resolution
    # If no food item was detected in this message, but the session has an
    # item waiting for a quantity reply, route to add_to_order to complete it.
    # =====================================================================
    if not matched_food:
        pending = pending_orders.get(_chatbot_session_key(session_id))
        if pending and pending.get("item"):
            logger.info(
                f"[CHATBOT][PENDING_QTY] Session={session_id} has pending item "
                f"'{pending['item']}' — routing to add_to_order for quantity resolution"
            )
            intent = _ADD_INTENT

    # Pass raw query_text to handlers (remove safety + quantity detection)
    parameters["_query_text"] = query_text
    parameters["_has_remove_keywords"] = has_remove_words
    parameters["_chatbot_user_id"] = resolved_user
    parameters["_output_contexts"] = output_contexts
    parameters["_resolved_intent"] = intent

    # =====================================================================
    # PIPELINE STEP 4: Route to ONE handler — cart logic lives ONLY inside
    # each handler function below. Nothing after this point runs.
    # =====================================================================
    logger.info(f"[CHATBOT][INTENT] intent={intent}")
    INTENT_HANDLER_MAP = {
        'Default Welcome Intent': greeting_handler,
        'Default Fallback Intent': fallback_handler,
        'order.start': new_order_handler,
        'new.order': new_order_handler,
        'order.add - context: ongoing-order': add_to_order,
        'order.remove - context: ongoing-order': remove_from_order,
        'order.complete - context: ongoing-order': complete_order,
        'track-order - context: ongoing-tracking': track_order,
        'track.order': track_order,
        'order.cancel': cancel_order_handler,
    }

    handler = INTENT_HANDLER_MAP.get(intent)
    if handler is None:
        logger.warning(f"[CHATBOT][PIPELINE] STEP4 No handler for intent={intent!r}")
        return fallback_handler(parameters, session_id)

    logger.info(f"[CHATBOT][PIPELINE] STEP4 dispatching → {handler.__name__}")

    # Single dispatch point — this is the ONLY return from the webhook pipeline.
    # No code runs after this; the handler's return value is the final response.
    try:
        if inspect.iscoroutinefunction(handler):
            result = await handler(parameters, session_id)
        else:
            result = handler(parameters, session_id)
    except Exception:
        logger.exception("[CHATBOT][WEBHOOK_FATAL]")
        raise
    return _chatbot_finalize_webhook_response(result)


class ChatbotLinkSession(BaseModel):
    session_id: str


@app.post("/api/chatbot/link-session", dependencies=[Depends(customer_required)])
async def link_chatbot_session_endpoint(
    body: ChatbotLinkSession,
    current_user: dict = Depends(get_current_user),
):
    """Map Dialogflow session_id to the authenticated website user (idempotent)."""
    sid = ""
    user_id = None
    try:
        raw_session = getattr(body, "session_id", None) if body else None
        if not raw_session or not str(raw_session).strip():
            return JSONResponse(
                status_code=200,
                content={"success": False, "error": "session_id is required"},
            )

        sid = _normalize_chatbot_session_id(str(raw_session).strip())
        user_id = int(current_user["user_id"])
        email = current_user.get("email")

        existing = _read_session_mapped_user_id(sid, allow_fuzzy=False)
        if existing is not None and existing != user_id:
            logger.warning(
                "[CHATBOT][LINK-SESSION] session=%s already linked user=%s caller=%s",
                sid,
                existing,
                user_id,
            )
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "session_id": sid,
                    "user_id": user_id,
                    "message": "Chatbot session already linked",
                },
            )

        link_chatbot_session(sid, user_id, allow_overwrite=True, email=email)

        logger.info(
            "[CHAT_AUTH] link-session session=%s user=%s refresh=%s",
            sid,
            user_id,
            existing == user_id,
        )
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "session_id": sid,
                "user_id": user_id,
            },
        )
    except Exception:
        logger.exception(
            "[CHATBOT][LINK-SESSION] failed session=%s user=%s",
            sid or "?",
            user_id,
        )
        return JSONResponse(
            status_code=200,
            content={
                "success": False,
                "error": "Could not link chatbot session",
            },
        )

# --- Auth Endpoints ---
class UserSignup(BaseModel):
    name: str
    email: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class AssignRider(BaseModel):
    rider_id: int

@app.post("/signup")
@app.post("/api/customer/signup")
async def signup(user: UserSignup):
    hashed_pw = get_password_hash(user.password)
    user_id = auth_service.create_user(user.name, user.email, hashed_pw)
    if not user_id: raise HTTPException(status_code=400, detail="Signup failed")
    token = create_jwt_token(user_id, user.email, [Role.CUSTOMER])
    return standard_response(True, "Signup successful", {"token": token, "user": {"id": user_id, "name": user.name, "email": user.email, "roles": [Role.CUSTOMER]}})

def _raise_login_error(message: str, status_code: int) -> None:
    raise HTTPException(status_code=status_code, detail=message)


@app.post("/login")
@app.post("/api/customer/login")
async def customer_login(user: UserLogin):
    db_user = auth_service.get_user_by_email(user.email)
    db_user, err = auth_service.validate_role_login(
        db_user,
        user.password,
        verify_password,
        required_role=Role.CUSTOMER,
        not_found_message="User does not exist",
        invalid_password_message="Incorrect email or password",
        access_denied_message="This login is only for customers.",
    )
    if err:
        _raise_login_error(*err)

    if not db_user.get("is_active", 1):
        _raise_login_error("Account is disabled.", 403)

    token = create_jwt_token(db_user["id"], db_user["email"], db_user["roles"])
    return standard_response(
        True,
        "Login successful",
        {
            "token": token,
            "user": {
                "id": db_user["id"],
                "name": db_user["name"],
                "email": db_user["email"],
                "roles": db_user["roles"],
            },
        },
    )


@app.post("/api/admin/login")
async def admin_login(user: UserLogin):
    db_user = auth_service.get_user_by_email(user.email)
    db_user, err = auth_service.validate_role_login(
        db_user,
        user.password,
        verify_password,
        required_role=Role.ADMIN,
        not_found_message="Admin does not exist",
        invalid_password_message="Invalid admin credentials",
        access_denied_message="Access denied. Admin only.",
    )
    if err:
        logger.warning("[AUTH] Admin login failed for %s: %s", user.email, err[0])
        _raise_login_error(*err)

    if not db_user.get("is_active", 1):
        _raise_login_error(
            "Admin account is disabled. Contact system administrator.", 403
        )

    token = create_jwt_token(db_user["id"], db_user["email"], db_user["roles"])
    logger.info("[AUTH] Admin %s logged in successfully", user.email)
    return standard_response(
        True,
        "Admin login successful",
        {
            "token": token,
            "user": {
                "id": db_user["id"],
                "name": db_user["name"],
                "email": db_user["email"],
                "roles": db_user["roles"],
            },
        },
    )


@app.post("/api/rider/login")
async def rider_login(user: UserLogin):
    db_user = auth_service.get_user_by_email(user.email)
    db_user, err = auth_service.validate_role_login(
        db_user,
        user.password,
        verify_password,
        required_role=Role.RIDER,
        not_found_message="Rider does not exist",
        invalid_password_message="Invalid rider credentials",
        access_denied_message="Access denied. Rider only.",
    )
    if err:
        logger.warning("[AUTH] Rider login failed for %s: %s", user.email, err[0])
        _raise_login_error(*err)

    if not db_user.get("is_active", 1):
        _raise_login_error(
            "Rider account is disabled. Please contact rider support.", 403
        )

    token = create_jwt_token(db_user["id"], db_user["email"], db_user["roles"])
    logger.info("[AUTH] Rider %s logged in successfully", user.email)
    return standard_response(
        True,
        "Rider login successful",
        {
            "token": token,
            "user": {
                "id": db_user["id"],
                "name": db_user["name"],
                "email": db_user["email"],
                "roles": db_user["roles"],
            },
        },
    )

@app.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    return user_service.get_profile(current_user["user_id"])

@app.get("/api/admin/riders")
async def get_riders(current_user: dict = Depends(admin_read_required)):
    from core.perf import PerfTimer

    timer = PerfTimer("/api/admin/riders")
    with timer.mongo():
        riders = rider_service.get_all_riders()
    with timer.serialize():
        payload = riders
    timer.finish()
    return standard_response(True, "Riders fetched", payload)


@app.get("/api/admin/stats")
async def get_admin_stats(current_user: dict = Depends(admin_read_required)):
    from core.perf import PerfTimer

    timer = PerfTimer("/api/admin/stats")
    try:
        with timer.mongo():
            stats = admin_service.get_admin_dashboard_stats()
        if not stats:
            return standard_response(False, "Failed to fetch admin stats")
        with timer.serialize():
            payload = stats
        timer.finish()
        return standard_response(True, "Admin stats fetched successfully", payload)
    except Exception as e:
        logger.error(f"[ADMIN] Error fetching stats: {e}")
        timer.finish()
        return standard_response(False, "Failed to fetch admin stats")


@app.get("/api/admin/orders")
async def get_admin_orders(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(admin_read_required),
):
    from core.perf import PerfTimer

    timer = PerfTimer("/api/admin/orders")
    try:
        with timer.mongo():
            result = admin_service.get_admin_orders(page=page, limit=limit)
        with timer.serialize():
            payload = result
        timer.finish()
        return standard_response(True, "Admin orders fetched successfully", payload)
    except Exception as e:
        logger.error(f"[ADMIN] Error fetching orders: {e}")
        timer.finish()
        return standard_response(False, "Failed to fetch admin orders")


@app.get("/api/admin/audit-log")
async def get_admin_audit_log(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(admin_read_required),
):
    from core.perf import PerfTimer

    timer = PerfTimer("/api/admin/audit-log")
    with timer.mongo():
        result = admin_service.get_audit_logs(page=page, limit=limit)
    with timer.serialize():
        payload = result
    timer.finish()
    return standard_response(True, "Audit log fetched successfully", payload)


@app.get("/api/admin/users")
async def get_admin_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(admin_read_required),
):
    from core.perf import PerfTimer

    timer = PerfTimer("/api/admin/users")
    with timer.mongo():
        result = admin_service.get_admin_users(page=page, limit=limit)
    with timer.serialize():
        payload = result
    timer.finish()
    return standard_response(True, "Users fetched successfully", payload)

@app.put("/api/admin/orders/{order_id}/status")
async def admin_update_order_status(
    order_id: int, 
    status_update: dict, 
    current_user: dict = Depends(admin_required)
):
    """
    STRICT ADMIN STATUS UPDATE.
    Allowed Statuses: RESTAURANT_CONFIRMED, FOOD_READY.
    """
    new_status = status_update.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="Missing status")

    new_status = normalize_status_internal(new_status)
    if not is_admin_allowed_status(new_status):
        raise HTTPException(
            status_code=403,
            detail=f"Admins are not permitted to set status to {new_status}",
        )

    result = order_service.admin_update_order_status(order_id, new_status)
    if not result.get("ok"):
        raise HTTPException(status_code=result.get("http_status", 400), detail=result.get("detail"))
    from core.cache import invalidate

    order = order_service.get_order_by_id(order_id)
    clear_order_broadcast_cache(order_id, order.get("rider_id") if order else None)
    invalidate("admin_dashboard_stats")
    await ecosystem_socket_manager.push_order_update(order_id)
    return standard_response(True, f"Status updated to {new_status}")

@app.post("/api/admin/riders", dependencies=[Depends(admin_required)])
async def create_rider(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    name = payload.get("name")
    email = payload.get("email")
    phone = payload.get("phone")
    password = payload.get("password")
    vehicle_type = payload.get("vehicle_type")
    license_number = payload.get("license_number")
    profile_pic = payload.get("profile_pic")
    
    if not all([name, email, password]):
        raise HTTPException(status_code=400, detail="Missing required fields")
        
    hashed_pw = get_password_hash(password)
    user_id = rider_service.create_rider_by_admin(name, email, phone, hashed_pw, vehicle_type, license_number, profile_pic)
    
    if not user_id:
        raise HTTPException(status_code=400, detail="Failed to create rider. Email might be taken.")
        
    admin_service.log_admin_action(current_user["user_id"], "CREATE_RIDER", details=f"Created rider {email}")
    return standard_response(True, "Rider created successfully", {"id": user_id})

@app.put("/api/admin/riders/{rider_id}/status", dependencies=[Depends(admin_required)])
async def toggle_rider_status(rider_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    is_active = payload.get("is_active")
    
    success = rider_service.toggle_user_active(rider_id, 1 if is_active else 0)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update status")
        
    action = "ENABLE_RIDER" if is_active else "DISABLE_RIDER"
    admin_service.log_admin_action(current_user["user_id"], action, details=f"Rider ID: {rider_id}")
    await ecosystem_socket_manager.push_rider_status_update(
        rider_id=rider_id,
        rider_status="available" if is_active else "offline"
    )
    return standard_response(True, f"Rider {'enabled' if is_active else 'disabled'} successfully")

@app.delete("/api/admin/riders/{rider_id}", dependencies=[Depends(admin_required)])
async def delete_rider(rider_id: int, current_user: dict = Depends(get_current_user)):
    """Soft delete rider (set is_active = 0)."""
    success = rider_service.toggle_user_active(rider_id, 0)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete rider")
        
    admin_service.log_admin_action(current_user["user_id"], "DELETE_RIDER", details=f"Soft deleted rider ID: {rider_id}")
    return standard_response(True, "Rider deleted successfully")

@app.post("/api/admin/assign_rider", dependencies=[Depends(admin_required)])
async def admin_assign_rider(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    order_id = payload.get("order_id")
    rider_id = payload.get("rider_id")
    
    result = admin_service.assign_rider_to_order(order_id, rider_id, current_user["user_id"])
    
    if result == "already_assigned":
        raise HTTPException(status_code=409, detail="Order already assigned to another rider")
    if result == "no_change":
        return standard_response(True, "Rider already assigned (no change)")
    if result != "assigned":
        raise HTTPException(status_code=400, detail=f"Assignment failed: {result}")
        
    clear_order_broadcast_cache(order_id, rider_id)
    await ecosystem_socket_manager.push_order_update(order_id)
    await ecosystem_socket_manager.push_rider_status_update(rider_id=rider_id, rider_status="busy")
    return {"status": "success"}

@app.put("/api/admin/orders/{order_id}/assign-rider", dependencies=[Depends(admin_required)])
async def admin_assign_rider_put(order_id: int, payload: AssignRider, current_user: dict = Depends(get_current_user)):
    """
    Hardened Rider Assignment Endpoint.
    """
    assign_err = order_service.validate_assignable_for_rider_assignment(order_id)
    if assign_err:
        raise HTTPException(status_code=400, detail=assign_err)

    result = admin_service.assign_rider_to_order(order_id, payload.rider_id, current_user["user_id"])
    
    if result == "order_not_found":
        raise HTTPException(status_code=404, detail="Order not found")
    if result == "order_not_ready":
        raise HTTPException(status_code=400, detail="Cannot assign rider: Food is not ready yet.")
    if result == "invalid_order_status":
        raise HTTPException(status_code=400, detail="Cannot assign rider to a delivered or cancelled order")
    if result == "invalid_rider":
        raise HTTPException(status_code=400, detail="Invalid or inactive rider")
    if result == "rider_busy":
        raise HTTPException(status_code=400, detail="This rider already has an active delivery")
    if result == "rider_offline":
        raise HTTPException(status_code=400, detail="Rider is offline. Ask them to go online first.")
    if result == "already_assigned":
        raise HTTPException(status_code=409, detail="Order already assigned to another rider")
    if result == "no_change":
        return standard_response(True, "Rider already assigned (no change)")
    if result == "error":
        raise HTTPException(status_code=500, detail="Internal database error during assignment")

    from core.cache import invalidate
    from repositories import order_repository

    clear_order_broadcast_cache(order_id, payload.rider_id)
    invalidate("admin_dashboard_stats")
    logger.info(
        "[ADMIN_ASSIGN_SYNC] order_id=%s rider_id=%s",
        order_id,
        payload.rider_id,
    )
    await ecosystem_socket_manager.push_order_update(order_id)
    await ecosystem_socket_manager.push_rider_status_update(rider_id=payload.rider_id, rider_status="busy")
    order_snapshot = order_repository.get_admin_order_snapshot(order_id)
    return standard_response(True, "Rider assigned successfully", order_snapshot)



@app.get("/api/order/{order_id}/rider/location")
async def get_rider_location(order_id: int):
    """Fetch active rider location. Hardened: Safe fallback if not found."""
    loc = order_service.get_active_rider_location_for_order(order_id)
    # db_helper already returns safe fallback {"status": "Rider offline", "location": None}
    return loc

@app.get("/api/rider/available_orders", dependencies=[Depends(rider_required)])
async def get_rider_available_orders(current_user: dict = Depends(get_current_user)):
    return rider_service.get_available_orders(current_user["user_id"])

@app.get("/api/rider/orders", dependencies=[Depends(rider_required)])
async def get_rider_orders(current_user: dict = Depends(get_current_user)):
    """Returns only orders assigned to the logged-in rider."""
    rider_id = current_user["user_id"]
    data = rider_service.build_rider_orders_payload(rider_id)
    response = JSONResponse(content={
        "success": True,
        "message": "Rider orders fetched",
        "data": data,
    })
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response

@app.get("/api/rider/history", dependencies=[Depends(rider_required)])
@app.get("/api/rider/completed_orders", dependencies=[Depends(rider_required)])
async def get_rider_history(current_user: dict = Depends(get_current_user)):
    """Returns historical (delivered/cancelled) orders for the rider."""
    rider_id = current_user["user_id"]
    logger.info("[RIDER_HISTORY][REQUEST] /api/rider/history called")
    logger.info(f"[RIDER_HISTORY][RIDER_ID] {rider_id}")
    orders = rider_service.get_rider_history_orders(rider_id)
    logger.info(f"[RIDER_HISTORY][ORDERS_FOUND] {len(orders)} orders returned to frontend")
    return standard_response(True, "Rider history fetched successfully", orders)

@app.get("/api/rider/stats", dependencies=[Depends(rider_required)])
async def get_rider_stats_endpoint(current_user: dict = Depends(get_current_user)):
    """Returns today's statistics for the logged-in rider."""
    stats = rider_service.get_rider_stats(current_user["user_id"])
    return standard_response(True, "Rider stats fetched", stats)

@app.put("/api/rider/orders/{order_id}/status")
async def rider_update_order_status(
    order_id: int, 
    status_update: dict, 
    current_user: dict = Depends(rider_required)
):
    """
    STRICT RIDER STATUS UPDATE.
    Requirements:
    1. Must be the assigned rider.
    2. Order must be at least FOOD_READY.
    3. Allowed Statuses: PICKED_UP, ON_THE_WAY, ARRIVING, DELIVERED.
    """
    new_status = status_update.get("status")
    lat = status_update.get("lat")
    lng = status_update.get("lng")
    
    if not new_status:
        raise HTTPException(status_code=400, detail="Missing status")

    new_status = normalize_status_internal(new_status)
    logger.info("[RIDER_STATUS] rider %s order %s -> %s", current_user["user_id"], order_id, new_status)
    result = order_service.rider_update_order_status(
        order_id, current_user["user_id"], new_status, lat=lat, lng=lng
    )
    if not result.get("ok"):
        raise HTTPException(status_code=result.get("http_status", 400), detail=result.get("detail"))

    clear_order_broadcast_cache(order_id, current_user["user_id"])
    await ecosystem_socket_manager.push_order_update(order_id)
    if new_status == "DELIVERED":
        await ecosystem_socket_manager.push_rider_status_update(
            rider_id=current_user["user_id"],
            rider_status="available"
        )
    
    return standard_response(True, f"Status updated to {new_status}")


@app.post("/api/rider/accept_order", dependencies=[Depends(rider_required)])
async def rider_accept_order(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    order_id = payload.get("order_id")
    rider_id = current_user["user_id"]
    
    logger.info(f"[RIDER_ACCEPT][ORDER_ID] {order_id}")
    logger.info(f"[RIDER_ACCEPT][RIDER_ID] {rider_id}")

    # 1. Pre-check: order exists and belongs to this rider assignment.
    order = order_service.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.get("rider_id") != rider_id:
        raise HTTPException(status_code=409, detail="Order is not assigned to you")

    result = rider_service.accept_assigned_order(order_id, rider_id)
    if result == "not_assigned_to_rider":
        raise HTTPException(status_code=409, detail="Order is not assigned to you")
    if result == "invalid_order_status":
        raise HTTPException(status_code=400, detail="Only ASSIGNED orders can be accepted")
    if result == "already_accepted":
        return standard_response(True, "Order already accepted")
    if result == "order_not_found":
        raise HTTPException(status_code=404, detail="Order not found")
    if result == "error":
        raise HTTPException(status_code=500, detail="Database error during acceptance")
    
    clear_order_broadcast_cache(order_id, rider_id)
    await ecosystem_socket_manager.push_order_update(order_id)
    return standard_response(True, "Order accepted successfully")


@app.put("/api/rider/online", dependencies=[Depends(rider_required)])
async def rider_set_online(request: Request, current_user: dict = Depends(get_current_user)):
    """Persist rider online/offline in MongoDB (survives page refresh)."""
    payload = await request.json()
    online = bool(payload.get("online", True))
    rider_id = current_user["user_id"]
    rider_service.set_rider_online(rider_id, online)
    if online and redis_service.redis_client:
        try:
            redis_service.redis_client.sadd("online_riders", str(rider_id))
        except Exception:
            pass
    elif not online and redis_service.redis_client:
        try:
            redis_service.redis_client.srem("online_riders", str(rider_id))
        except Exception:
            pass
    await ecosystem_socket_manager.push_rider_status_update(
        rider_id=rider_id,
        rider_status="available" if online else "offline",
    )
    return standard_response(True, "Rider presence updated", {"online": online})


@app.get("/api/rider/presence", dependencies=[Depends(rider_required)])
async def rider_get_presence(current_user: dict = Depends(get_current_user)):
    return standard_response(
        True,
        "Rider presence",
        rider_service.get_rider_presence(current_user["user_id"]),
    )


@app.post("/api/rider/location", dependencies=[Depends(rider_required)])
@app.post("/rider/location/update", dependencies=[Depends(rider_required)])
async def update_location(request: Request, current_user: dict = Depends(get_current_user)):
    """Update rider location with GPS Smoothing & Throttling (Redis-backed)."""
    payload = await request.json()
    lat = payload.get("lat")
    lng = payload.get("lng")
    heading = payload.get("heading", 0)
    speed = payload.get("speed", 0)
    rider_id = current_user["user_id"]
    now = time.time()
    
    if lat is not None and lng is not None:
        if not validate_coordinates(lat, lng):
            raise HTTPException(status_code=400, detail="Invalid GPS coordinates")
            
        # 1. Throttling Logic (Redis-backed)
        throttle_key = f"rider_throttle:{rider_id}"
        if redis_service.redis_client:
            last_pos_data = get_cache(throttle_key)
            if last_pos_data:
                last_pos = json.loads(last_pos_data)
                time_diff = now - last_pos["time"]
                dist_diff = calculate_distance(lat, lng, last_pos["lat"], last_pos["lng"])
                
                # Rule: 2s OR 10m
                if time_diff < 2.0 and dist_diff < 10.0:
                    return {"status": "throttled", "reason": "No significant movement"}
        else:
            # Memory fallback
            last_pos = rider_last_pos.get(rider_id)
            if last_pos:
                if now - last_pos["time"] < 2.0 and calculate_distance(lat, lng, last_pos["lat"], last_pos["lng"]) < 10.0:
                    return {"status": "throttled", "reason": "No significant movement"}

        # 2. GPS Smoothing (Moving Average of last 3 points)
        history = rider_gps_history[rider_id]
        history.append((lat, lng))
        if len(history) > 3:
            history.pop(0)
        
        smoothed_lat = sum(p[0] for p in history) / len(history)
        smoothed_lng = sum(p[1] for p in history) / len(history)
        
        # 3. Update Persistence (Redis & DB)
        pos_payload = {"lat": smoothed_lat, "lng": smoothed_lng, "time": now}
        if redis_service.redis_client:
            set_cache(throttle_key, json.dumps(pos_payload), 3600)
            redis_service.redis_client.set(f"rider_last_known:{rider_id}", json.dumps({
                "lat": smoothed_lat, "lng": smoothed_lng, "heading": heading, "speed": speed, "updated_at": now
            }))
        else:
            rider_last_pos[rider_id] = pos_payload

        rider_service.upsert_rider_location(rider_id, smoothed_lat, smoothed_lng, heading, speed)
        await ecosystem_socket_manager.push_rider_status_update(
            rider_id=rider_id,
            lat=smoothed_lat,
            lng=smoothed_lng,
            heading=heading
        )
        
        # 4. Broadcast to all active order rooms for this rider (Rule 2)
        active_orders = rider_service.get_active_orders_for_rider(rider_id)
        for order_id in active_orders:
            await ecosystem_socket_manager.push_order_update(order_id, driver_lat=smoothed_lat, driver_lng=smoothed_lng)

    return {"status": "success"}

@app.websocket("/ws/rider")
async def rider_ws(websocket: WebSocket):
    await websocket.accept()
    active_rooms_for_connection = set()
    
    try:
        # 1. Authenticate WebSocket and check for rider role
        payload = await get_token_from_websocket(websocket)
        if not payload or "rider" not in payload.get("roles", []):
            await websocket.close(code=1008)
            return
        
        rider_id = payload.get("user_id")
        
        # Register to rider-specific room for isolated updates
        room = f"rider_{rider_id}"
        if room not in active_rooms_for_connection:
            await ecosystem_socket_manager.connect(room, websocket, user_id=rider_id)
            active_rooms_for_connection.add(room)
        
        from repositories import user_repository

        user_repository.set_rider_online(rider_id, True)
        if redis_service.redis_client:
            try:
                redis_service.redis_client.sadd("online_riders", str(rider_id))
                logger.info("[RIDER_WS] Rider %s connected (mongo+redis online)", rider_id)
            except Exception as e:
                logger.warning(f"[REDIS] Presence tracking failed: {e}")
        await ecosystem_socket_manager.push_rider_status_update(rider_id=rider_id, rider_status="available")

        while True:
            if websocket.client_state.name != "CONNECTED":
                break

            last_ping = getattr(websocket, "last_ping_time", 0)
            if time.time() - last_ping > 120:
                logger.warning(f"[RIDER][WS] Disconnecting idle rider socket {rider_id}")
                break

            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=20.0)
                if data == "ping":
                    setattr(websocket, "last_ping_time", time.time())
                    user_repository.touch_rider_heartbeat(rider_id)
                    await websocket.send_text("pong")
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    except Exception as e:
        logger.error(f"[RIDER][WS] Error: {e}")
    finally:
        if "rider_id" in locals():
            if redis_service.redis_client:
                try:
                    redis_service.redis_client.srem("online_riders", str(rider_id))
                except Exception:
                    pass
            logger.info("[RIDER_WS] Rider %s socket closed (mongo online preserved)", rider_id)
        for r in active_rooms_for_connection:
            ecosystem_socket_manager.disconnect(r, websocket)
        active_rooms_for_connection.clear()
        try:
            await websocket.close()
        except:
            pass


# --- Menu & Cart ---
@app.get("/api/menu")
async def get_menu():
    try:
        menu_data = food_service.build_menu_response()
    except Exception:
        logger.exception("[MENU] get_menu safety fallback triggered")
        menu_data = []
    return standard_response(True, "Menu fetched successfully", menu_data)

@app.get("/api/cart", dependencies=[Depends(customer_required)])
async def get_cart(current_user: dict = Depends(get_current_user)):
    return cart_service.get_cart_items(current_user["user_id"])

@app.post("/api/cart/add", dependencies=[Depends(customer_required)])
async def add_cart_item(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    item_id = payload.get("item_id")
    quantity = payload.get("quantity", 1)
    return cart_service.add_to_cart(current_user["user_id"], item_id, quantity)

@app.put("/api/cart/update", dependencies=[Depends(customer_required)])
async def update_cart_item(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    item_id = payload.get("item_id")
    quantity = payload.get("quantity")
    return cart_service.update_cart_quantity(current_user["user_id"], item_id, quantity)

@app.delete("/api/cart/remove/{item_id}", dependencies=[Depends(customer_required)])
async def remove_cart_item(item_id: int, current_user: dict = Depends(get_current_user)):
    return cart_service.remove_from_cart(current_user["user_id"], item_id)

@app.delete("/api/cart/clear", dependencies=[Depends(customer_required)])
async def clear_user_cart(current_user: dict = Depends(get_current_user)):
    cart_service.clear_cart(current_user["user_id"])
    return []

@app.post("/api/order/place", dependencies=[Depends(customer_required)])
async def place_order(request: Request, current_user: dict = Depends(get_current_user)):
    user_id = current_user["user_id"]
    try:
        payload = await request.json()
        address_id = payload.get("address_id")
        cart_items = payload.get("items")
        payment_method = payload.get("payment_method", "COD")

        logger.info(f"[ORDER][PLACE] user_id={user_id} address_id={address_id!r} payment={payment_method} items_count={len(cart_items) if cart_items else 0}")

        if not address_id:
            logger.warning(f"[ORDER][PLACE][VALIDATION] address_id is missing or falsy for user_id={user_id}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": "Address ID is required"}
            )

        # Order snapshot coords come from user_addresses when present (may be NULL if not geocoded).
        order_id = order_service.place_order_in_db(
            user_id,
            address_id,
            items=cart_items,
            payment_method=payment_method,
            restaurant_lat=RESTAURANT_LAT,
            restaurant_lng=RESTAURANT_LNG,
        )
        
        if not order_id:
            logger.error(f"[ORDER][PLACE][ERROR] DB creation failed for user_id={user_id}")
            return JSONResponse(
                status_code=500,
                content={"success": False, "message": "Database failure during order placement"}
            )

        # Initialize tracking
        order_service.insert_order_tracking(order_id, "PLACED")
        
        # ISOLATED WEBSOCKET BROADCAST
        # These failures must never return HTTP 500 if order insertion was successful.
        try:
            await ecosystem_socket_manager.push_order_update(order_id)
            logger.debug(f"[ORDER][PLACE] Tracking initialized for Order #{order_id}")
        except Exception as ws_err:
            logger.warning(f"[ORDER][PLACE] Non-critical broadcast failure for Order #{order_id}: {ws_err}")

        
        logger.info(f"[ORDER][PLACE][SUCCESS] Order #{order_id} created for user_id={user_id}")
        return {"success": True, "order_id": order_id}

    except Exception as e:
        error_summary = traceback.format_exc()
        err_msg = str(e)
        if "DELIVERY_COORDS_INVALID" in err_msg:
            customer_msg = err_msg.split(":", 1)[1].strip() if ":" in err_msg else err_msg
            logger.warning(f"[ORDER][PLACE][COORDS] user_id={user_id} | {customer_msg}")
            return JSONResponse(
                status_code=400,
                content={"success": False, "message": customer_msg},
            )
        print("ORDER ERROR:", err_msg)
        traceback.print_exc()
        with open("order_error.log", "a") as f:
            f.write(f"--- {datetime.now(timezone.utc)} ---\n{error_summary}\n")
        logger.error(f"[ORDER][PLACE][ERROR] user_id={user_id} | Exception: {type(e).__name__} | Detail: {err_msg}\n{error_summary}")
        
        return JSONResponse(
            status_code=500,
            content={
                "success": False, 
                "message": f"Unable to place order. Server side error: {err_msg}",
                "detail": error_summary
            }
        )

@app.delete("/api/order/{order_id}", dependencies=[Depends(customer_required)])
async def customer_delete_order(order_id: int, current_user: dict = Depends(get_current_user)):
    """
    Customer-only: hard-delete an order still in ORDER_PLACED with no rider assignment.
    Rejects safely if status changed mid-request (transaction + row lock).
    """
    user_id = current_user["user_id"]
    try:
        result = order_service.delete_customer_order_placed(order_id, user_id)
    except Exception as e:
        logger.error(f"[ORDER_DELETE][API] DB error order_id={order_id}: {e}")
        raise HTTPException(status_code=500, detail="Could not delete order. Please try again.")

    if result == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Order not found")
    if result == "FORBIDDEN":
        raise HTTPException(status_code=403, detail="You do not have permission to delete this order")
    if result == "NOT_DELETABLE":
        raise HTTPException(status_code=400, detail="Order can no longer be deleted")

    try:
        await ecosystem_socket_manager.push_order_removed(order_id)
    except Exception as ws_err:
        logger.warning(f"[ORDER_DELETE] WS broadcast non-critical failure order_id={order_id}: {ws_err}")

    return {
        "success": True,
        "order_id": order_id,
        "message": "Order deleted successfully",
    }


@app.get("/api/order/{order_id}")
async def get_order(order_id: int, current_user: dict = Depends(get_current_user)):
    """
    Fetch full order summary.
    """
    # 1. Fetch Summary FIRST (Required for role validation)
    access = order_service.authorize_order_access(
        order_id, current_user["user_id"], current_user.get("roles", [])
    )
    if not access.get("allowed"):
        raise HTTPException(status_code=access.get("http_status", 403), detail=access.get("detail"))
    summary = access["summary"]

    dl = summary.get("delivery_location") or {}
    logger.info(
        f"[TRACK_ORDER_API] order_id={order_id} "
        f"delivery_lat={dl.get('latitude')} delivery_lng={dl.get('longitude')}"
    )
    return summary

@app.get("/api/customer/orders/{order_id}")
async def get_customer_order_details(order_id: int, current_user: dict = Depends(get_current_user)):
    """Customer view: Hidden rider assignment until pickup."""
    order = order_service.get_order_summary(order_id, is_admin_view=False)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return standard_response(True, "Order fetched", order)


@app.get("/api/order/{order_id}/tracking")
async def get_order_tracking(order_id: int, current_user: dict = Depends(get_current_user)):
    """
    Returns live order tracking status.
    Security rule: enforces ownership exactly like /api/order/{order_id}.
    Admins bypass ownership check.
    """
    user_id: int = current_user["user_id"]
    user_roles: list = current_user.get("roles", [])

    access = order_service.authorize_order_access(order_id, user_id, user_roles)
    if not access.get("allowed"):
        raise HTTPException(status_code=access.get("http_status", 403), detail=access.get("detail"))

    status_obj = order_service.resolve_order_status(order_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Tracking data not found for this order")
    return status_obj

@app.get("/api/my-orders", dependencies=[Depends(customer_required)])
@app.get("/api/user_orders", dependencies=[Depends(customer_required)])
async def get_my_orders(current_user: dict = Depends(get_current_user)):
    return {"orders": order_service.get_user_orders_full(current_user["user_id"])}

# --- Address Endpoints ---
@app.get("/api/address", dependencies=[Depends(customer_required)])
async def get_addresses(current_user: dict = Depends(get_current_user)):
    return address_service.get_user_addresses(current_user["user_id"])

@app.post("/api/address/add", dependencies=[Depends(customer_required)])
async def add_address(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    address_id = address_service.add_address(
        current_user["user_id"],
        payload.get("full_name") or payload.get("name"),
        payload.get("phone"),
        payload.get("address_line"),
        payload.get("city"),
        payload.get("state"),
        payload.get("pincode"),
        payload.get("is_default", False),
        payload.get("latitude"),
        payload.get("longitude"),
    )
    return {"address_id": address_id}

@app.delete("/api/address/delete/{address_id}", dependencies=[Depends(customer_required)])
async def delete_address(address_id: int, current_user: dict = Depends(get_current_user)):
    address_service.delete_address(current_user["user_id"], address_id)
    return {"status": "success"}

@app.post("/api/address/set_default/{address_id}", dependencies=[Depends(customer_required)])
async def set_default_address(address_id: int, current_user: dict = Depends(get_current_user)):
    address_service.set_default_address(address_id, current_user["user_id"])
    return {"status": "success"}

# --- User profile address management (/api/user/address) ---
class UserAddressCreate(BaseModel):
    name: str
    phone: Optional[str] = None
    address_line: str
    city: str
    state: str
    pincode: str
    is_default: bool = False

class UserAddressUpdate(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None
    address_line: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    is_default: Optional[bool] = None

@app.post("/api/user/address", dependencies=[Depends(customer_required)])
async def create_user_address(
    body: UserAddressCreate,
    current_user: dict = Depends(get_current_user),
):
    address_id = address_service.add_user_address(current_user["user_id"], body.model_dump())
    if not address_id:
        raise HTTPException(status_code=500, detail="Failed to create address")
    return standard_response(True, "Address created", {"address_id": address_id})

@app.get("/api/user/address", dependencies=[Depends(customer_required)])
async def list_user_addresses(current_user: dict = Depends(get_current_user)):
    addresses = address_service.get_user_addresses(current_user["user_id"])
    return standard_response(True, "Addresses fetched", {"addresses": addresses})

@app.put("/api/user/address/{address_id}", dependencies=[Depends(customer_required)])
async def update_user_address(
    address_id: int,
    body: UserAddressUpdate,
    current_user: dict = Depends(get_current_user),
):
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=400, detail="No fields to update")
    updated = address_service.update_user_address(address_id, current_user["user_id"], payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Address not found")
    return standard_response(True, "Address updated")

@app.delete("/api/user/address/{address_id}", dependencies=[Depends(customer_required)])
async def remove_user_address(
    address_id: int,
    current_user: dict = Depends(get_current_user),
):
    deleted = address_service.delete_user_address(address_id, current_user["user_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Address not found")
    return standard_response(True, "Address deleted")

@app.post("/api/user/address/{address_id}/default", dependencies=[Depends(customer_required)])
async def mark_default_user_address(
    address_id: int,
    current_user: dict = Depends(get_current_user),
):
    ok = address_service.set_default_address(address_id, current_user["user_id"])
    if not ok:
        raise HTTPException(status_code=404, detail="Address not found")
    return standard_response(True, "Default address updated")

# ---------------------------------------------------------------------------
# NEARBY RESTAURANTS  (OpenStreetMap Overpass API)
# ---------------------------------------------------------------------------

# In-memory TTL cache: key → (timestamp, data)
_osm_cache: dict = {}
OSM_CACHE_TTL = 45  # seconds


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in kilometres between two WGS-84 coordinates."""
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


async def fetch_osm_restaurants(lat: float, lng: float, radius: float) -> list:
    """Fetch restaurants from OpenStreetMap Overpass API.
    Returns a list of dicts with id, name, lat, lng.
    Falls back to empty list on any error.
    """
    cache_key = f"{round(lat, 4)}:{round(lng, 4)}:{int(radius)}"
    now = time.time()

    # --- Cache hit ---
    if cache_key in _osm_cache:
        ts, data = _osm_cache[cache_key]
        if now - ts < OSM_CACHE_TTL:
            logger.info(f"[OSM] Cache hit for key={cache_key}")
            return data

    overpass_query = f"""
[out:json][timeout:25];
(
  node["amenity"="restaurant"](around:{int(radius)},{lat},{lng});
  way["amenity"="restaurant"](around:{int(radius)},{lat},{lng});
  relation["amenity"="restaurant"](around:{int(radius)},{lat},{lng});
);
out center;
""".strip()

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://overpass-api.de/api/interpreter",
                content=overpass_query,
                headers={"Content-Type": "text/plain"},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.TimeoutException:
        logger.warning("[OSM] Overpass API timeout — returning empty list")
        return []
    except Exception as exc:
        logger.error(f"[OSM] Overpass API error: {exc}")
        return []

    results = []
    for element in data.get("elements", []):
        name = element.get("tags", {}).get("name")
        if not name:
            continue  # skip unnamed restaurants

        # node has direct lat/lon; way/relation uses 'center'
        if element.get("type") == "node":
            r_lat = element.get("lat")
            r_lng = element.get("lon")
        else:
            center = element.get("center", {})
            r_lat = center.get("lat")
            r_lng = center.get("lon")

        if r_lat is None or r_lng is None:
            continue

        results.append({
            "id": element.get("id"),
            "name": name,
            "lat": float(r_lat),
            "lng": float(r_lng),
            "cuisine": element.get("tags", {}).get("cuisine", ""),
            "phone": element.get("tags", {}).get("phone", ""),
            "website": element.get("tags", {}).get("website", ""),
            "opening_hours": element.get("tags", {}).get("opening_hours", ""),
        })

    _osm_cache[cache_key] = (now, results)
    logger.info(f"[OSM] Fetched {len(results)} restaurants for key={cache_key}")
    return results


@app.get("/api/restaurants/nearby")
async def get_nearby_restaurants(
    lat: float,
    lng: float,
    radius: float = 8000.0,
    limit: int = 20,
):
    """
    Return real nearby restaurants sourced from OpenStreetMap Overpass API.
    Query params:
      lat    – user latitude  (required)
      lng    – user longitude (required)
      radius – search radius in metres (default 8000 = 8 km)
      limit  – max results returned  (default 20)
    """
    if not ENABLE_NEARBY_FEATURE:
        raise HTTPException(status_code=404, detail="Not Found")

    # --- Coordinate validation ---
    logger.info(f"[OSM] /nearby called: lat={lat}, lng={lng}, radius={radius}")

    if not validate_coordinates(lat, lng):
        raise HTTPException(status_code=400, detail="Invalid coordinates. lat must be in [-90,90] and lng in [-180,180].")

    if radius <= 0 or radius > 50000:
        raise HTTPException(status_code=400, detail="radius must be between 1 and 50000 metres.")

    if limit <= 0 or limit > 100:
        limit = 20

    raw = await fetch_osm_restaurants(lat, lng, radius)
    logger.info(f"[OSM] OSM restaurants found: {len(raw)} (radius={radius}m)")

    # --- Fallback: retry with 15km if nothing returned ---
    if len(raw) == 0 and radius < 15000:
        logger.warning(f"[OSM] No results at {radius}m — retrying with 15000m fallback")
        raw = await fetch_osm_restaurants(lat, lng, 15000)
        logger.info(f"[OSM] OSM restaurants found (fallback 15km): {len(raw)}")

    # --- Calculate distance + sort ---
    enriched = []
    for r in raw:
        dist_km = _haversine_km(lat, lng, r["lat"], r["lng"])
        enriched.append({
            "id": r["id"],
            "name": r["name"],
            "lat": r["lat"],
            "lng": r["lng"],
            "distance_km": round(dist_km, 3),
            "cuisine": r.get("cuisine", ""),
            "phone": r.get("phone", ""),
            "website": r.get("website", ""),
            "opening_hours": r.get("opening_hours", ""),
            "type": "restaurant",
        })

    enriched.sort(key=lambda x: x["distance_km"])
    logger.info(f"[OSM] Returning {min(len(enriched), limit)} restaurants to client")
    return enriched[:limit]


# --- Dialogflow helpers ---


def _normalize_chatbot_session_id(session: str) -> str:
    """Canonical session key: last path segment, no webdemo- prefix."""
    if not session:
        return ""
    s = str(session).strip()
    if "/sessions/" in s:
        s = s.split("/sessions/")[-1]
    s = s.split("/")[0].strip()
    return s.removeprefix("webdemo-")


def _session_id_variants(session_id: str) -> list:
    base = _normalize_chatbot_session_id(session_id)
    if not base:
        return []
    return list({base, f"webdemo-{base}"})


def _unpack_chatbot_session_entry(entry):
    if isinstance(entry, dict):
        return entry.get("user_id"), float(entry.get("expires_at") or 0)
    if isinstance(entry, (tuple, list)) and len(entry) >= 2:
        return entry[0], float(entry[1])
    return None, 0


def _sessions_related(a: str, b: str) -> bool:
    """True when two session ids likely refer to the same chat (e.g. webdemo-uuid vs uuid)."""
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 8 and len(b) >= 8 and (a in b or b in a):
        return True
    return False


def _migrate_chatbot_session_state(old_sid: str, new_sid: str) -> bool:
    old_sid = _normalize_chatbot_session_id(old_sid)
    new_sid = _normalize_chatbot_session_id(new_sid)
    if not old_sid or not new_sid or old_sid == new_sid:
        return False

    migrated = False

    if old_sid in inprogress_orders:
        if new_sid not in inprogress_orders:
            inprogress_orders[new_sid] = inprogress_orders.pop(old_sid)
        else:
            for iid, item in inprogress_orders.pop(old_sid).items():
                if iid in inprogress_orders[new_sid]:
                    inprogress_orders[new_sid][iid]["quantity"] += item.get("quantity", 0)
                else:
                    inprogress_orders[new_sid][iid] = item
        migrated = True

    if old_sid in pending_orders:
        if new_sid not in pending_orders:
            pending_orders[new_sid] = pending_orders.pop(old_sid)
        migrated = True

    if old_sid in chatbot_session_users:
        if new_sid not in chatbot_session_users:
            chatbot_session_users[new_sid] = chatbot_session_users.pop(old_sid)
        migrated = True

    return migrated


def _consolidate_chatbot_session_state(canonical_sid: str) -> None:
    """Merge cart/auth stored under alias session keys into the canonical session id."""
    canonical_sid = _normalize_chatbot_session_id(canonical_sid)
    if not canonical_sid:
        return

    for variant in _session_id_variants(canonical_sid):
        if variant != canonical_sid:
            _migrate_chatbot_session_state(variant, canonical_sid)

    for sid in list(inprogress_orders.keys()):
        if _normalize_chatbot_session_id(sid) == canonical_sid and sid != canonical_sid:
            _migrate_chatbot_session_state(sid, canonical_sid)

    for sid in list(pending_orders.keys()):
        if _normalize_chatbot_session_id(sid) == canonical_sid and sid != canonical_sid:
            _migrate_chatbot_session_state(sid, canonical_sid)

    for sid in list(chatbot_session_users.keys()):
        if _normalize_chatbot_session_id(sid) == canonical_sid and sid != canonical_sid:
            _migrate_chatbot_session_state(sid, canonical_sid)


def link_chatbot_session(
    session_id: str,
    user_id: int,
    allow_overwrite: bool = False,
    email: str = None,
) -> None:
    """Map session id (and aliases) → user. Refreshes TTL when allow_overwrite=True."""
    if not session_id or user_id is None:
        return

    canonical = _normalize_chatbot_session_id(session_id)
    expires_at = time.time() + CHATBOT_SESSION_TTL
    chatbot_user_last_link[user_id] = (canonical, expires_at)

    for variant in _session_id_variants(canonical):
        if redis_service.redis_client:
            try:
                if allow_overwrite:
                    redis_service.redis_client.setex(f"chatbot_session:{variant}", CHATBOT_SESSION_TTL, str(user_id))
                else:
                    redis_service.redis_client.set(
                        f"chatbot_session:{variant}",
                        str(user_id),
                        ex=CHATBOT_SESSION_TTL,
                        nx=True,
                    )
            except Exception as e:
                logger.warning(f"[CHATBOT] Redis session link failed for {variant}: {e}")

        if allow_overwrite or variant not in chatbot_session_users:
            if email:
                chatbot_session_users[variant] = {
                    "user_id": user_id,
                    "email": email,
                    "expires_at": expires_at,
                }
            else:
                chatbot_session_users[variant] = (user_id, expires_at)
            logger.info(
                f"[CHATBOT][LINK] session={variant} → user={user_id} overwrite={allow_overwrite}"
            )


def _fuzzy_resolve_chatbot_user(session_id: str) -> Optional[int]:
    """Read-only: match Dialogflow session to a related linked session id."""
    target = _normalize_chatbot_session_id(session_id)
    if not target:
        return None

    now = time.time()
    matches = []
    for sid, entry in list(chatbot_session_users.items()):
        uid, exp = _unpack_chatbot_session_entry(entry)
        if not uid or exp <= now:
            chatbot_session_users.pop(sid, None)
            continue
        other = _normalize_chatbot_session_id(sid)
        if _sessions_related(target, other):
            matches.append((uid, sid))

    unique_uids = {m[0] for m in matches}
    if len(matches) == 1 or len(unique_uids) == 1:
        uid, matched_sid = matches[0]
        logger.info(
            "[CHAT_SESSION] fuzzy_match old_session=%s new_session=%s user=%s",
            matched_sid,
            target,
            uid,
        )
        return uid

    return None


def _read_session_mapped_user_id(session_id: str, *, allow_fuzzy: bool = True) -> Optional[int]:
    """Read session→user mapping only. Never writes or links."""
    if not session_id:
        return None

    canonical = _normalize_chatbot_session_id(session_id)
    now = time.time()

    for variant in _session_id_variants(canonical):
        if redis_service.redis_client:
            try:
                val = get_cache(f"chatbot_session:{variant}")
                if val is not None:
                    return int(val)
            except Exception as e:
                logger.warning("[CHATBOT] Redis session lookup failed: %s", e)

        entry = chatbot_session_users.get(variant)
        if entry:
            user_id, expires_at = _unpack_chatbot_session_entry(entry)
            if user_id and now <= expires_at:
                return user_id
            chatbot_session_users.pop(variant, None)

    if allow_fuzzy:
        return _fuzzy_resolve_chatbot_user(canonical)

    return None


def _get_session_mapped_user_id(session_id: str) -> Optional[int]:
    """Backward-compatible alias — read-only session map (optional fuzzy)."""
    return _read_session_mapped_user_id(session_id, allow_fuzzy=True)


def get_chatbot_user_id(session_id: str):
    """Backward-compatible alias — session map only (auth uses _resolve_chatbot_auth_user)."""
    return _read_session_mapped_user_id(session_id, allow_fuzzy=True)


def _sole_active_chatbot_user(now: float = None) -> Optional[int]:
    """Return user_id only when exactly one user has a non-expired chatbot session."""
    now = now if now is not None else time.time()
    active_users = set()
    for entry in chatbot_session_users.values():
        uid, exp = _unpack_chatbot_session_entry(entry)
        if uid and exp > now:
            active_users.add(uid)
    if len(active_users) == 1:
        return next(iter(active_users))
    return None


def _decode_chatbot_user_token(token: str):
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("user_id")
    except Exception:
        return None


def _chatbot_jwt_present(request: Request, payload: dict) -> bool:
    """True when any JWT-shaped credential is attached (valid or not)."""
    auth_header = request.headers.get("Authorization") or ""
    if auth_header.startswith("Bearer ") and auth_header.split(" ", 1)[1].strip():
        return True
    for cookie_name in ("customerToken", "access_token", "token"):
        if request.cookies.get(cookie_name):
            return True
    try:
        inner = (payload.get("originalDetectIntentRequest") or {}).get("payload") or {}
        for key in ("userToken", "authToken", "token", "customerToken"):
            if inner.get(key):
                return True
    except Exception:
        pass
    return False


def _safe_link_chatbot_session(session_id: str, user_id: int) -> None:
    """Write session→user mapping. Never calls back into itself via lookup."""
    if not session_id or user_id is None:
        return

    canonical = _normalize_chatbot_session_id(session_id)
    lock_key = (canonical, int(user_id))
    if lock_key in _chatbot_session_linking_in_progress:
        return

    _chatbot_session_linking_in_progress.add(lock_key)
    try:
        existing = _read_session_mapped_user_id(canonical, allow_fuzzy=False)
        if existing is not None and existing != user_id:
            logger.warning(
                "[CHATBOT][SAFE_LINK] session=%s mapped user=%s, skip user=%s",
                canonical,
                existing,
                user_id,
            )
            return
        if existing == user_id:
            return
        link_chatbot_session(canonical, user_id, allow_overwrite=True)
    finally:
        _chatbot_session_linking_in_progress.discard(lock_key)


def _resolve_user_from_link_memory(target_session: str) -> Optional[int]:
    """Third-priority auth: user_id from /api/chatbot/link-session (independent of DF session)."""
    now = time.time()
    active: list[tuple[int, str, float]] = []
    for uid, (linked_sid, exp) in list(chatbot_user_last_link.items()):
        if exp <= now:
            chatbot_user_last_link.pop(uid, None)
            continue
        active.append((uid, linked_sid, exp))

    if not active:
        return None

    canonical = _normalize_chatbot_session_id(target_session)

    if canonical:
        for uid, linked_sid, exp in active:
            if _sessions_related(canonical, _normalize_chatbot_session_id(linked_sid)):
                _safe_link_chatbot_session(canonical, uid)
                if linked_sid and linked_sid != canonical:
                    _migrate_chatbot_session_state(linked_sid, canonical)
                return uid

    active.sort(key=lambda row: row[2], reverse=True)
    if len(active) == 1:
        uid, linked_sid, _ = active[0]
        if canonical:
            _safe_link_chatbot_session(canonical, uid)
            if linked_sid and linked_sid != canonical:
                _migrate_chatbot_session_state(linked_sid, canonical)
        return uid

    if len(active) > 1 and active[0][2] > active[1][2] + 1.0:
        uid, linked_sid, _ = active[0]
        if canonical:
            _safe_link_chatbot_session(canonical, uid)
            if linked_sid and linked_sid != canonical:
                _migrate_chatbot_session_state(linked_sid, canonical)
        return uid

    return None


def _extract_user_id_from_chatbot_request(request: Request, payload: dict) -> Optional[int]:
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        uid = _decode_chatbot_user_token(auth_header.split(" ", 1)[1])
        if uid:
            return uid
    if request is not None:
        for cookie_name in ("customerToken", "access_token", "token"):
            uid = _decode_chatbot_user_token(request.cookies.get(cookie_name))
            if uid:
                return uid
    try:
        inner = (payload.get("originalDetectIntentRequest") or {}).get("payload") or {}
        for key in ("userToken", "authToken", "token", "customerToken"):
            uid = _decode_chatbot_user_token(inner.get(key))
            if uid:
                return uid
    except Exception:
        pass
    return None


def _try_link_chatbot_session_from_request(request: Request, payload: dict, session_id: str) -> None:
    """Restore session→user mapping from JWT when Dialogflow forwards it."""
    if not session_id:
        return

    canonical = _normalize_chatbot_session_id(session_id)
    uid = _extract_user_id_from_chatbot_request(request, payload)
    if not uid:
        return

    existing = _read_session_mapped_user_id(canonical, allow_fuzzy=False)
    if existing is not None and existing != uid:
        logger.warning(
            "[CHATBOT][TRY_LINK] session=%s mapped user=%s jwt_user=%s",
            canonical,
            existing,
            uid,
        )

    _safe_link_chatbot_session(canonical, uid)


def _resolve_chatbot_auth_user(
    session_id: str, request: Request, payload: dict
) -> tuple:
    """
    Resolve authenticated customer once per webhook (JWT → session map → link-memory → sole).
    Dialogflow session_id is used only to attach cart mappings, not as the primary auth key.
    Returns (user_id | None, auth_source).
    """
    canonical = _normalize_chatbot_session_id(session_id) or "default-session"

    # 1) JWT — header, cookies, Dialogflow originalDetectIntentRequest payload
    jwt_uid = _extract_user_id_from_chatbot_request(request, payload)
    if jwt_uid:
        _safe_link_chatbot_session(canonical, jwt_uid)
        return jwt_uid, "JWT"

    # 2) Existing session→user mapping (including fuzzy variant match)
    mapped = _read_session_mapped_user_id(canonical, allow_fuzzy=True)
    if mapped:
        _safe_link_chatbot_session(canonical, mapped)
        return mapped, "session"

    # 3) Link-session memory from website (survives Dialogflow session id changes)
    from_link = _resolve_user_from_link_memory(canonical)
    if from_link:
        return from_link, "link-session"

    # 4) Single active linked user (local dev / single customer)
    sole = _sole_active_chatbot_user()
    if sole:
        _safe_link_chatbot_session(canonical, sole)
        return sole, "fallback"

    return None, "none"


def _chatbot_session_key(session_id: str) -> str:
    normalized = _normalize_chatbot_session_id(session_id)
    return normalized if normalized else "default-session"


def _chatbot_extract_quantity(parameters: dict) -> Optional[int]:
    """Return explicit quantity from parameters, or None — never default to 1."""
    if not parameters:
        return None
    for key in ("number", "Number", "quantity", "amount"):
        v = parameters.get(key)
        if v is None or v == "" or v == [] or v == [""]:
            continue
        if isinstance(v, list):
            for x in v:
                if x is None or str(x).strip() == "":
                    continue
                try:
                    return max(1, int(float(x)))
                except (TypeError, ValueError):
                    continue
        else:
            try:
                return max(1, int(float(v)))
            except (TypeError, ValueError):
                continue
    return None


def _chatbot_extract_food_names(parameters: dict) -> list:
    if not parameters:
        return []
    names = []
    # Check all possible keys Dialogflow might use
    for key in ("food-item", "food_item", "food", "Food", "dish", "item", "menu_item"):
        v = parameters.get(key)
        if v is None or v == "":
            continue
        if isinstance(v, list):
            for x in v:
                if x is not None and str(x).strip():
                    names.append(str(x).strip())
        else:
            s = str(v).strip()
            if s:
                names.append(s)
        if names:
            break
    return names


def _chatbot_extract_order_id(parameters: dict):
    if not parameters:
        return None
    for key in ("order_id", "order-id", "orderid", "OrderID", "number"):
        v = parameters.get(key)
        if v is None or v == "" or v == [] or v == [""]:
            continue
        if isinstance(v, list):
            for x in v:
                if x is None or str(x).strip() == "":
                    continue
                try:
                    return int(float(x))
                except (TypeError, ValueError):
                    continue
        else:
            try:
                return int(float(v))
            except (TypeError, ValueError):
                continue
    return None


_ORDER_ID_TEXT_RE = re.compile(
    r"(?:order\s*(?:id|#|number)?\s*[:#]?\s*)(\d+)|#(\d+)|\btrack\s+order\s+(\d+)\b",
    re.IGNORECASE,
)


def _chatbot_extract_order_id_from_text(query_text: str) -> Optional[int]:
    """Regex fallback when Dialogflow parameters omit the order id."""
    q = (query_text or "").strip()
    if not q:
        return None
    for m in _ORDER_ID_TEXT_RE.finditer(q):
        for g in m.groups():
            if g:
                try:
                    return int(g)
                except (TypeError, ValueError):
                    continue
    m = re.search(r"\b(\d{3,})\b", q)
    if m:
        try:
            return int(m.group(1))
        except (TypeError, ValueError):
            pass
    return None


def _chatbot_context_active(output_contexts, context_id: str) -> bool:
    needle = f"/contexts/{context_id}"
    for ctx in output_contexts or []:
        name = ctx.get("name") or ""
        if needle in name:
            return True
    return False


def _chatbot_require_ongoing_order(parameters) -> Optional[JSONResponse]:
    contexts = parameters.get("_output_contexts", [])
    logger.info(f"[CHATBOT][ONGOING_CONTEXT_CHECK] contexts={contexts}")

    contexts = parameters.get("_output_contexts", []) or []
    has_ongoing_order = any(
        "ongoing-order" in (ctx.get("name", "").lower())
        for ctx in contexts
    )

    if not has_ongoing_order:
        logger.info("[CHATBOT][ONGOING_CONTEXT_MISSING]")
        return JSONResponse(
            content={
                "fulfillmentText": "Please start a new order first by saying 'New Order'."
            }
        )
    return None


def _chatbot_friendly_track_status(status: str) -> str:
    s = (status or "").strip().upper()
    if s == "CONFIRMED":
        return "Preparing"
    if s == "DELIVERED":
        return "Delivered"
    return s.replace("_", " ").title()


def _chatbot_cart_summary(cart: dict) -> str:
    name_qty = {item["name"]: item["quantity"] for item in cart.values()}
    return generic_helper.get_str_from_food_dict(name_qty)


_REMOVE_KEYWORDS_RE = re.compile(r"\b(remove|delete|cancel)\b", re.IGNORECASE)
_COMPLETE_ORDER_PHRASES_RE = re.compile(
    r"\b(?:complete\s+order|place\s+order|finish\s+order|"
    r"that'?s\s+it|that\s+is\s+it|done\s+ordering|checkout|confirm\s+order|nope|done|no|finish|that'?s\s+all)\b",
    re.IGNORECASE,
)
_ADD_INTENT = "order.add - context: ongoing-order"
_REMOVE_INTENT = "order.remove - context: ongoing-order"


def _is_complete_order_phrase(query_text: str) -> bool:
    return bool(_COMPLETE_ORDER_PHRASES_RE.search(query_text or ""))


def _has_remove_keywords(query_text: str) -> bool:
    return bool(_REMOVE_KEYWORDS_RE.search(query_text or ""))


def _food_name_regex_pattern(food_name: str) -> str:
    """Build a flexible regex for multi-word menu names (e.g. vada pav)."""
    parts = [re.escape(p) for p in (food_name or "").lower().split() if p]
    return r"\s+".join(parts) if parts else ""


def _chatbot_find_remove_qty_in_text(text: str, food_re: str) -> Optional[int]:
    """Extract a quantity tied to a food name within a text fragment."""
    if not text or not food_re:
        return None
    patterns = (
        rf"\b(\d+)\s+(?:\w+\s+)*?{food_re}\b",
        rf"\b{food_re}\s*x\s*(\d+)\b",
        rf"\b{food_re}\s+(\d+)\b",
    )
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return max(1, int(m.group(1)))
    return None


def _chatbot_explicit_remove_qty_for_food(query_text: str, food_name: str) -> Optional[int]:
    """
    Return quantity to subtract when the user explicitly typed a number for this dish.
    Return None when no number is tied to this food → caller must FULL DELETE the line item.
    Uses raw query text only (never Dialogflow number[] defaults).
    """
    q = (query_text or "").lower().strip()
    food_re = _food_name_regex_pattern(food_name)
    if not q or not food_re:
        return None

    if not re.search(r"\b\d+\b", q):
        return None

    q_clean = _REMOVE_KEYWORDS_RE.sub(" ", q).strip()

    for segment in re.split(r"\s+and\s+", q_clean):
        segment = segment.strip()
        if not re.search(food_re, segment) and not re.search(food_re, q_clean):
            continue
        qty = _chatbot_find_remove_qty_in_text(segment, food_re)
        if qty is None:
            qty = _chatbot_find_remove_qty_in_text(q_clean, food_re)
        if qty is not None:
            return qty

    return None


def _chatbot_cart_name_qty_snapshot(cart: dict) -> dict:
    """Compact {canonical_name: qty} view for debug logs."""
    snap = {}
    for it in (cart or {}).values():
        name = (it.get("name") or "").strip()
        if name:
            snap[name] = int(it.get("quantity") or 0)
    return snap


def _chatbot_clean_fulfillment_text(text: str) -> str:
    """
    Strip merged Dialogflow agent + webhook text (e.g. 'SamosaRemoved Samosa'
    or 'Removed SamosaRemoved Samosa') down to a single clean bot message.
    Only runs when duplicate 'removed' fragments are detected.
    """
    text = (text or "").strip()
    if not text:
        return text

    needle = "removed "
    lower = text.lower()
    if lower.count(needle) < 2:
        return text

    first = lower.find(needle)
    last = lower.rfind(needle)
    if last > first:
        return text[last:].strip()

    prefix = text[:first].strip()
    if prefix and not prefix.lower().startswith("removed"):
        return text[first:].strip()

    return text


def _chatbot_fulfillment_response(message: str) -> JSONResponse:
    """Standard Dialogflow webhook payload; fulfillmentMessages override agent text."""
    clean = _chatbot_clean_fulfillment_text(message)
    logger.info("BOT RESPONSE: %s", clean)
    return JSONResponse(
        content={
            "fulfillmentText": clean,
            "fulfillmentMessages": [{"text": {"text": [clean]}}],
        }
    )


def _chatbot_finalize_webhook_response(result) -> JSONResponse:
    """Normalize handler output to a single clean fulfillment payload."""
    raw = ""
    if isinstance(result, JSONResponse):
        try:
            raw = json.loads(result.body.decode("utf-8")).get("fulfillmentText", "")
        except Exception:
            raw = ""
    elif isinstance(result, dict):
        raw = result.get("fulfillmentText", "")
    elif isinstance(result, str):
        raw = result

    clean = _chatbot_clean_fulfillment_text(raw) or (
        "Something went wrong. Please try again."
    )
    return _chatbot_fulfillment_response(clean)


def _chatbot_remove_label_to_message(label: str) -> str:
    """One removal line — never double-prefix 'Removed'."""
    label = (label or "").strip()
    if not label:
        return ""
    if label.lower().startswith("removed "):
        return label
    return f"Removed {label}"


def _chatbot_remove_fulfillment_text(removed_labels: list[str], final_cart: dict) -> str:
    """Build remove response from final persisted cart only."""
    messages = [_chatbot_remove_label_to_message(label) for label in removed_labels]
    messages = [m for m in messages if m]
    if not messages:
        return "I did not catch which dish to remove. Please name the item."
    if len(messages) == 1:
        text = messages[0]
    else:
        text = ". ".join(messages)
    if not final_cart:
        return f"{text}. Your order is empty now."
    return f"{text}. Remaining order: {_chatbot_cart_summary(final_cart)}"


def _chatbot_detect_food_in_text(query_text: str) -> Optional[str]:
    """Return canonical menu name when query_text mentions a dish (DB-backed)."""
    q = re.sub(r"^\d+\s+", "", (query_text or "").lower()).strip()
    if not q:
        return None
    row = chatbot_service.get_food_item_by_name(q)
    if row:
        return row["name"]
    try:
        menu = food_service.get_food_items() or []
    except Exception:
        menu = []
    for item in sorted(menu, key=lambda i: len(i.get("name") or ""), reverse=True):
        name = (item.get("name") or "").strip()
        if name and name.lower() in q:
            return name
    return None


def _chatbot_detect_all_foods_in_text(query_text: str) -> list:
    """Return all menu items mentioned in query_text (longest names first)."""
    q = (query_text or "").lower().strip()
    if not q:
        return []
    try:
        menu = food_service.get_food_items() or []
    except Exception:
        menu = []
    found = []
    seen = set()
    for item in sorted(menu, key=lambda i: len(i.get("name") or ""), reverse=True):
        name = (item.get("name") or "").strip()
        key = name.lower()
        if name and key in q and key not in seen:
            found.append(name)
            seen.add(key)
    return found


_CHATBOT_QTY_ITEMS_CLARIFICATION = (
    "Please specify the quantity for food items. Example: 2 pizzas, 1 mango lassi."
)


def _quantity_clarification_message(food_name: str = None) -> str:
    return _CHATBOT_QTY_ITEMS_CLARIFICATION


def _has_explicit_quantity(parameters: dict, query_text: str = "") -> bool:
    """
    True only when the user message contains an explicit digit.
    Dialogflow number[] is not trusted alone (often defaults to [1]).
    """
    return bool(re.search(r"\b\d+\b", query_text or ""))


def _chatbot_split_order_clauses(query_text: str) -> list:
    """Split multi-item order text on 'and' / commas."""
    q = (query_text or "").lower().strip()
    if not q:
        return []
    q = re.sub(
        r"^(?:please\s+)?(?:add|order|get|i\s+want|i'?d\s+like)\s+",
        "",
        q,
        flags=re.IGNORECASE,
    ).strip()
    if not q:
        return []
    parts = re.split(r"\s+and\s+|,", q)
    return [p.strip() for p in parts if p.strip()]


def _chatbot_qty_for_clause(clause: str) -> Optional[int]:
    """Return explicit quantity from a clause, or None if none stated."""
    m = re.search(r"\b(\d+)\b", clause or "")
    if m:
        return max(1, int(m.group(1)))
    return None


def _chatbot_parse_add_items(query_text: str, parameters: dict) -> list:
    """
    Parse one or more dishes from user text.
    Returns [{"name": canonical_name, "qty": int|None}, ...].
    qty=None means the user did not specify a quantity for that item.
    """
    clauses = _chatbot_split_order_clauses(query_text)
    multi_clause = len(clauses) > 1

    if multi_clause:
        parsed = []
        for clause in clauses:
            food = _chatbot_detect_food_in_text(clause)
            if not food:
                continue
            parsed.append({"name": food, "qty": _chatbot_qty_for_clause(clause)})
        if parsed:
            return parsed

    all_foods = _chatbot_detect_all_foods_in_text(query_text)
    if len(all_foods) > 1:
        parsed = []
        for food in all_foods:
            food_re = _food_name_regex_pattern(food)
            qty = _chatbot_find_remove_qty_in_text(query_text, food_re)
            parsed.append({"name": food, "qty": qty})
        return parsed

    foods = _chatbot_extract_food_names(parameters)
    if not foods:
        detected = _chatbot_detect_food_in_text(query_text)
        if detected:
            foods = [detected]

    if not foods:
        return []

    if len(foods) > 1:
        parsed = []
        for fname in foods:
            row = chatbot_service.get_food_item_by_name(fname)
            canonical = row["name"] if row else fname.strip()
            food_re = _food_name_regex_pattern(canonical)
            qty = _chatbot_find_remove_qty_in_text(query_text, food_re)
            if qty is None:
                qty = _chatbot_find_remove_qty_in_text(
                    query_text, _food_name_regex_pattern(fname)
                )
            if qty is None and _has_explicit_quantity(parameters, query_text):
                qty = _chatbot_extract_quantity(parameters)
            parsed.append({"name": canonical, "qty": qty})
        return parsed

    row = chatbot_service.get_food_item_by_name(foods[0])
    canonical = row["name"] if row else foods[0].strip()
    qty = _chatbot_qty_for_clause(query_text)
    if qty is None and _has_explicit_quantity(parameters, query_text):
        qty = _chatbot_extract_quantity(parameters)
    return [{"name": canonical, "qty": qty}]


def _chatbot_add_parsed_items_to_cart(cart: dict, parsed_items: list) -> tuple:
    """Apply parsed items to cart. Returns (added_labels, unavailable_name)."""
    added = []
    for entry in parsed_items:
        if entry.get("qty") is None:
            continue
        row = chatbot_service.get_food_item_by_name(entry["name"])
        if not row:
            return added, entry["name"]
        qty = max(1, int(entry["qty"]))
        iid = row["item_id"]
        if iid in cart:
            cart[iid]["quantity"] += qty
        else:
            cart[iid] = {
                "item_id": iid,
                "name": row["name"],
                "quantity": qty,
                "price": float(row["price"]),
            }
        added.append(f"{qty} {row['name']}")
    return added, None


def _chatbot_user_from_context(pre_resolved_user_id: int = None, session_id: str = None, parameters: dict = None):
    """
    Use user resolved once at webhook entry. Handlers must not re-run auth checks.
    """
    if pre_resolved_user_id:
        return pre_resolved_user_id, None

    if session_id and parameters:
        contexts = parameters.get("_output_contexts", [])
        has_ongoing_order = any(
            "ongoing-order" in (ctx.get("name", "").lower())
            for ctx in contexts
        )
        if has_ongoing_order:
            logger.info(f"[CHATBOT][AUTH_BYPASS] session_id={session_id} ongoing_order_context=True")
            return None, None

    logger.warning("[CHAT_AUTH] mapped_user=None — all auth checks failed at webhook")
    return None, "Please log in on the website before placing an order through chat."


def save_to_db(session_cart: dict, user_id: int):
    """Create a production order from the chatbot session cart (delegates to chatbot_service)."""
    logger.info(f"[CHATBOT][SAVE_TO_DB] user_id={user_id} cart={session_cart}")
    result = chatbot_service.place_order_from_session_cart(
        user_id, session_cart, RESTAURANT_LAT, RESTAURANT_LNG
    )
    logger.info(f"[CHATBOT][SAVE_TO_DB_RESULT] result={result}")
    return result


# --- Dialogflow Handlers ---



_CHATBOT_START_ORDER_MSG = "Please start a new order first by saying 'New Order'."
_CHATBOT_TRACK_ORDER_ID_MSG = "Please provide your order ID to track your order."


def greeting_handler(parameters, session_id):
    return JSONResponse(
        content={"fulfillmentText": "Hi! You can say 'New Order' or 'Track Order'."}
    )


def fallback_handler(parameters, session_id):
    return JSONResponse(
        content={
            "fulfillmentText": (
                "Sorry, I didn't understand that. You can say 'New Order' or 'Track Order'."
            )
        }
    )

def new_order_handler(parameters, session_id):
    sid = _chatbot_session_key(session_id)
    inprogress_orders[sid] = {}
    pending_orders.pop(sid, None)
    text = (
        "Starting new order. Specify food items and quantities.\n"
        "For example: 'I would like to order 2 pizzas and 1 mango lassi'.\n"
        "Menu: Pav Bhaji, Chole Bhature, Pizza, Mango Lassi, Masala Dosa, Biryani, Vada Pav, Rava Dosa, Samosa."
    )
    return JSONResponse(content={"fulfillmentText": text})

def _chatbot_add_pending_item(cart: dict, food_name: str, qty: int) -> tuple:
    row = chatbot_service.get_food_item_by_name(food_name)
    if not row:
        return None, food_name
    qty = max(1, int(qty))
    iid = row["item_id"]
    if iid in cart:
        cart[iid]["quantity"] += qty
    else:
        cart[iid] = {
            "item_id": iid,
            "name": row["name"],
            "quantity": qty,
            "price": float(row["price"]),
        }
    return f"{qty} {row['name']}", None


def _chatbot_cart_fulfillment_summary(cart: dict) -> str:
    if not cart:
        return "Your order is empty."
    summary = _chatbot_cart_summary(cart)
    return f"So far you have: {summary}. Do you need anything else?"


def add_to_order(parameters, session_id):
    logger.info("[CHATBOT][ADD_TO_ORDER_ENTERED]")
    try:
        logger.info(f"[CHATBOT][ADD_PARAMS] {parameters}")
        blocked = _chatbot_require_ongoing_order(parameters)
        if blocked:
            return blocked

        sid = _chatbot_session_key(session_id)
        if sid not in inprogress_orders:
            logger.info(
                f"[CHATBOT][ONGOING_ORDER_FAIL] "
                f"session_id={session_id} "
                f"contexts={parameters.get('_output_contexts')} "
                f"cart_exists={bool(inprogress_orders.get(sid))}"
            )
            inprogress_orders[sid] = {}

        query_text = parameters.get("_query_text", "")
        cart = inprogress_orders[sid]

        pending = pending_orders.get(sid)
        if pending and pending.get("item"):
            qty = _chatbot_qty_for_clause(query_text)
            if qty is None and _has_explicit_quantity(parameters, query_text):
                qty = _chatbot_extract_quantity(parameters)
            if qty is None:
                return JSONResponse(
                    content={
                        "fulfillmentText": _quantity_clarification_message(pending["item"])
                    }
                )
            label, unavailable = _chatbot_add_pending_item(cart, pending["item"], qty)
            pending_orders.pop(sid, None)
            if unavailable:
                return JSONResponse(
                    content={
                        "fulfillmentText": f"Sorry, {unavailable} is not available right now."
                    }
                )
            return JSONResponse(
                content={
                    "fulfillmentText": f"Added {label}. {_chatbot_cart_fulfillment_summary(cart)}"
                }
            )

        parsed = _chatbot_parse_add_items(query_text, parameters)
        if not parsed:
            return JSONResponse(content={"fulfillmentText": "Please specify a food item."})

        missing_qty = [p for p in parsed if p.get("qty") is None]
        if missing_qty:
            if len(missing_qty) == 1 and len(parsed) == 1:
                pending_orders[sid] = {"item": missing_qty[0]["name"]}
                return JSONResponse(
                    content={
                        "fulfillmentText": _quantity_clarification_message(missing_qty[0]["name"])
                    }
                )
            return JSONResponse(
                content={"fulfillmentText": _quantity_clarification_message()}
            )

        added, unavailable = _chatbot_add_parsed_items_to_cart(cart, parsed)
        if unavailable:
            return JSONResponse(
                content={
                    "fulfillmentText": f"Sorry, {unavailable} is not available right now."
                }
            )
        if not added:
            return JSONResponse(content={"fulfillmentText": "Please specify a food item."})

        return JSONResponse(content={"fulfillmentText": _chatbot_cart_fulfillment_summary(cart)})

    except Exception:
        logger.exception("[CHATBOT] add_to_order")
        return JSONResponse(
            content={
                "fulfillmentText": (
                    "Something went wrong updating your order. Please try again in a moment."
                )
            }
        )

def remove_from_order(parameters, session_id):
    try:
        if not parameters.get("_has_remove_keywords"):
            logger.info(
                "[CHATBOT][REMOVE] blocked — no remove/delete/cancel in user text; routing to add"
            )
            return add_to_order(parameters, session_id)

        blocked = _chatbot_require_ongoing_order(parameters)
        if blocked:
            return blocked

        sid = _chatbot_session_key(session_id)
        cart = inprogress_orders.get(sid)
        if not cart:
            return JSONResponse(content={"fulfillmentText": "Your order is empty."})

        query_text = parameters.get("_query_text", "")
        foods = _chatbot_extract_food_names(parameters)
        if not foods:
            foods = _chatbot_detect_all_foods_in_text(query_text)
        if not foods:
            detected = _chatbot_detect_food_in_text(query_text)
            if detected:
                foods = [detected]

        if not foods:
            return JSONResponse(
                content={
                    "fulfillmentText": "I did not catch which dish to remove. Please name the item."
                }
            )

        removed_labels = []
        for food in foods:
            row = chatbot_service.get_food_item_by_name(food)
            canonical = row["name"] if row else food.strip()
            iid = row["item_id"] if row else None

            if not iid or iid not in cart:
                for k, v in cart.items():
                    if (v.get("name") or "").lower() == food.lower():
                        iid = k
                        canonical = v["name"]
                        break

            if not iid or iid not in cart:
                removed_labels.append(f"{canonical} is not in your current order")
                continue

            qty_remove = _chatbot_explicit_remove_qty_for_food(query_text, canonical)
            logger.info(f"[CHATBOT][REMOVE] item={canonical} qty_remove={qty_remove}")
            if qty_remove is None:
                del cart[iid]
                removed_labels.append(f"{canonical} from your order")
            else:
                cart[iid]["quantity"] -= qty_remove
                if cart[iid]["quantity"] <= 0:
                    del cart[iid]
                    removed_labels.append(f"{qty_remove} {canonical}")
                else:
                    removed_labels.append(f"{qty_remove} {canonical}")

        if not removed_labels:
            return JSONResponse(
                content={
                    "fulfillmentText": "I did not catch which dish to remove. Please name the item."
                }
            )

        if all("is not in your current order" in label for label in removed_labels):
            return {"fulfillmentText": removed_labels[0] + "."}

        success_labels = [
            label for label in removed_labels if "is not in your current order" not in label
        ]
        text = _chatbot_remove_fulfillment_text(success_labels, cart)

        logger.info(
            f"[CHATBOT][REMOVE] session={sid} cart={_chatbot_cart_name_qty_snapshot(cart)}"
        )
        return {"fulfillmentText": text}

    except Exception:
        logger.exception("[CHATBOT] remove_from_order")
        return JSONResponse(
            content={
                "fulfillmentText": (
                    "Something went wrong updating your order. Please try again in a moment."
                )
            }
        )

async def _chatbot_push_order_update_safe(order_id: int) -> None:
    try:
        await ecosystem_socket_manager.push_order_update(order_id)
    except Exception as ws_err:
        logger.warning(
            f"[CHATBOT] push_order_update non-critical failure for order_id={order_id}: {ws_err}"
        )


async def complete_order(parameters, session_id):
    logger.info("[CHATBOT] complete_order ENTERED")
    try:
        blocked = _chatbot_require_ongoing_order(parameters)
        if blocked:
            logger.exception("[CHATBOT][COMPLETE] FAILURE")
            return blocked

        sid = _chatbot_session_key(session_id)
        user_id, login_err = _chatbot_user_from_context(parameters.get("_chatbot_user_id"), session_id, parameters)
        if login_err:
            logger.exception("[CHATBOT][COMPLETE] FAILURE")
            return JSONResponse(content={"fulfillmentText": login_err})

        live_cart = inprogress_orders.get(sid)
        if not live_cart:
            logger.exception("[CHATBOT][COMPLETE] FAILURE")
            return JSONResponse(
                content={
                    "fulfillmentText": "Your order is empty"
                }
            )

        cart_snapshot = {k: dict(v) for k, v in live_cart.items()}
        order_id, err = save_to_db(cart_snapshot, user_id)
        
        logger.info(f"[CHATBOT][COMPLETE] order_id={order_id} err={err}")

        if err or not order_id or order_id == 0:
            logger.exception("[CHATBOT][COMPLETE] FAILURE")
            return JSONResponse(
                content={
                    "fulfillmentText": "Sorry, I couldn't place your order right now. Please try again."
                }
            )

        total = sum(v["quantity"] * v["price"] for v in cart_snapshot.values())

        live_cart.clear()
        pending_orders.pop(sid, None)

        text = (
            f"So far your order was: {_chatbot_cart_summary(cart_snapshot)}.\n\n"
            f"Your order has been placed successfully!\n"
            f"Order ID: #{order_id}\n"
            f"Total Amount: ₹{int(total)}\n\n"
            f"You can pay at delivery.\n"
            f"Use 'Track Order' with your order ID to check status."
        )

        asyncio.create_task(_chatbot_push_order_update_safe(order_id))

        logger.info(f"[CHATBOT][COMPLETE] SUCCESS order_id={order_id}")
        return JSONResponse(content={"fulfillmentText": text})

    except Exception:
        logger.exception("[CHATBOT] complete_order")
        logger.exception("[CHATBOT][COMPLETE] FAILURE")
        return JSONResponse(
            content={
                "fulfillmentText": (
                    "Something went wrong completing your order. Please try again later."
                )
            }
        )


def track_order(parameters, session_id):
    try:
        user_id, login_err = _chatbot_user_from_context(parameters.get("_chatbot_user_id"), session_id, parameters)
        if login_err:
            return JSONResponse(
                content={"fulfillmentText": "Please log in on the website to track your order."}
            )

        query_text = parameters.get("_query_text", "")
        oid = _chatbot_extract_order_id(parameters)
        if oid is None:
            oid = _chatbot_extract_order_id_from_text(query_text)

        if oid is None:
            return JSONResponse(content={"fulfillmentText": _CHATBOT_TRACK_ORDER_ID_MSG})

        status = chatbot_service.get_order_status_for_user(oid, user_id)
        if not status:
            return JSONResponse(
                content={"fulfillmentText": "No order found with this ID for your account."}
            )

        friendly = _chatbot_friendly_track_status(status)
        text = f"Order #{oid} is currently: {friendly}"
        return JSONResponse(content={"fulfillmentText": text})

    except Exception:
        logger.exception("[CHATBOT] track_order")
        return JSONResponse(
            content={
                "fulfillmentText": (
                    "Something went wrong looking up your order. Please try again in a moment."
                )
            }
        )

def cancel_order_handler(parameters, session_id):
    """
    Only reached when Dialogflow sends order.cancel AND no food item was
    detected in query_text (the FORCE_ROUTE guard runs before this handler).
    Cart check lives here — NOT in the global pipeline.
    """
    try:
        sid = _chatbot_session_key(session_id)
        cart = inprogress_orders.get(sid)
        if not cart:
            return JSONResponse(
                content={"fulfillmentText": "You don't have an active order to cancel."}
            )
        cart.clear()
        pending_orders.pop(sid, None)
        logger.info(f"[CHATBOT] cancel_order_handler: cart cleared for session={sid}")
        return JSONResponse(content={"fulfillmentText": "Your order has been cancelled."})
    except Exception:
        logger.exception("[CHATBOT] cancel_order_handler")
        return JSONResponse(content={"fulfillmentText": "Something went wrong. Please try again."})


@app.options("/{rest_of_path:path}")
async def global_options_handler(rest_of_path: str, request: Request):
    """Catch-all OPTIONS so preflight never hits POST-only route validation (400/405)."""
    return _cors_preflight_response(request)


# Registered last so it wraps all routes/middleware (outermost — handles CORS on every response).
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(_CORS_ALLOWED_ORIGINS),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)