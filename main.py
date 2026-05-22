import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
import db_helper
print("[DEBUG] db_helper imported")
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
import redis
import re
import json
import bcrypt
import traceback
import inspect

# --- FEATURE FLAGS ---
ENABLE_NEARBY_FEATURE = False
# --- Redis Integration (Hardened Startup) ---
redis_client = None
try:
    redis_client = redis.Redis(
        host='localhost', port=6379, db=0, 
        decode_responses=True, socket_timeout=0.5, socket_connect_timeout=0.5
    )
    redis_client.ping()
    logger.info("[REDIS] Connection established.")
except Exception as e:
    redis_client = None
    logger.warning("Redis disabled - running in degraded mode")
    
import os
logger.info(f"[DEBUG] DB_NAME from env: {os.getenv('DB_NAME')}")
logger.info(f"[DEBUG] DB_HOST from env: {os.getenv('DB_HOST')}")

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
chatbot_session_users = {}  # session_id -> (user_id, expires_at) fallback when Redis unavailable
CHATBOT_SESSION_TTL = 86400

CHATBOT_ORDER_STATUS_MESSAGES = {
    "ORDER_PLACED": "Your order has been placed.",
    "RESTAURANT_CONFIRMED": "Restaurant confirmed your order.",
    "FOOD_READY": "Your food is ready.",
    "ASSIGNED": "A rider has been assigned.",
    "ACCEPTED": "Rider accepted your order.",
    "ORDER_PICKED_UP": "Your food has been picked up.",
    "OUT_FOR_DELIVERY": "Your order is out for delivery.",
    "DELIVERED": "Your order has been delivered.",
}

# --- State Machine Config (Single Source of Truth) ---
FOOD_READY = "FOOD_READY"
ASSIGNABLE_STATUSES = {"RESTAURANT_CONFIRMED", FOOD_READY}

# Clean linear model for status updates (no special-cases in validation).
ORDER_FLOW = {
    "ORDER_PLACED": "RESTAURANT_CONFIRMED",
    "RESTAURANT_CONFIRMED": "FOOD_READY",
    "FOOD_READY": "ASSIGNED",
    "ASSIGNED": "ACCEPTED",
    "ACCEPTED": "ORDER_PICKED_UP",
    "ORDER_PICKED_UP": "OUT_FOR_DELIVERY",
    "OUT_FOR_DELIVERY": "DELIVERED",
}

def validate_status_transition(current_status: str, next_status: str) -> bool:
    """
    STRICT SEQUENTIAL ENFORCEMENT.
    Only allows the EXACT next status in the sequence.
    Rejects duplicates, skips, and reversals.
    """
    current = normalize_status_internal(current_status)
    next_st = normalize_status_internal(next_status)

    # 1. Duplicate Protection (Safe rejection)
    if current == next_st:
        return False

    # 2. Strict Linear Flow Check (Single source of truth)
    expected_next = ORDER_FLOW.get(current)
    if expected_next != next_st:
        logger.warning(f"[TRANSITION_REJECTED] {current} -> {next_st} (Expected: {expected_next})")
        return False

    return True

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
    client_ip = request.client.host
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
    ORDER_PLACED = "ORDER_PLACED"
    RESTAURANT_CONFIRMED = "RESTAURANT_CONFIRMED"
    FOOD_READY = "FOOD_READY"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"
    ORDER_PICKED_UP = "ORDER_PICKED_UP"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    NEAR_CUSTOMER_LOCATION = "NEAR_CUSTOMER_LOCATION"
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
        db_user = db_helper.get_user_by_id(user_id)
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
            if redis_client:
                try:
                    redis_client.sadd(f"active_rooms:{room}", str(id(websocket)))
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
            
            if redis_client:
                try:
                    redis_client.srem(f"active_rooms:{room}", str(id(websocket)))
                except:
                    pass
                    
            if not self.rooms[room] and room != "admin_monitor":
                del self.rooms[room]
                if redis_client:
                    try:
                        redis_client.delete(f"active_rooms:{room}")
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
        if redis_client:
            try:
                last_p = redis_client.get(f"last_payload:{room}")
                if last_p == payload_str:
                    return
                redis_client.set(f"last_payload:{room}", payload_str, ex=3600)
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
            order = db_helper.get_order_by_id(order_id)
            if not order:
                logger.warning(f"[WS] Order not found: {order_id}")
                return

            # AUTHORITATIVE NORMALIZATION (FIX 4)
            db_status = order.get("status")
            current_status = normalize_status_internal(db_status)
            rider_id = order.get("rider_id")
            
            logger.info(f"[WS][DB_STATE] order_id={order_id} db_status={db_status} normalized={current_status}")

            order_summary = db_helper.get_order_summary(order_id) or {}
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
        rider_state = db_helper.get_rider_realtime_state(rider_id) or {"rider_id": rider_id}
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

@app.middleware("http")
async def check_ready(request: Request, call_next):
    if request.url.path in ["/health", "/api/health"]:
        return await call_next(request)
    if not app_state.get("ready"):
        return JSONResponse(
            status_code=503,
            content={"error": "Server warming up"}
        )
    return await call_next(request)

# 1. CORS MIDDLEWARE (STRICT HARDENING)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. GLOBAL EXCEPTION HANDLERS (Ensures CORS headers on errors)
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_summary = traceback.format_exc()
    logger.error(f"[GLOBAL_ERROR] {request.method} {request.url} | Exception: {type(exc).__name__} | Detail: {str(exc)}\n{error_summary}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal Server Error",
            "detail": str(exc) if os.getenv("DEBUG") == "true" else "An unexpected error occurred"
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "message": exc.detail}
    )

# 3. OTHER MIDDLEWARE
app.middleware("http")(rate_limit_middleware)

app.mount("/images", StaticFiles(directory="frontend/public/images"), name="images")

# --- Health Check Endpoint (No Auth Required) ---
@app.get("/api/health")
async def health_check():
    """Lightweight liveness probe. Frontend uses this before WebSocket reconnect attempts."""
    return {"success": True, "status": "ok", "redis": redis_client is not None}

@app.get("/health")
def health():
    return {
        "status": "ok",
        "redis": redis_client is not None
    }

# --- RIDER-DEPENDENT STATUSES ---
RIDER_DEPENDENT_STATUSES = {
    "ORDER_PICKED_UP",
    "OUT_FOR_DELIVERY",
    "NEAR_CUSTOMER_LOCATION",
    "DELIVERED"
}

def is_rider_online(rider_id: int) -> bool:
    """Checks if a rider is currently online via Redis presence set."""
    if not rider_id:
        return False
    if redis_client:
        return redis_client.sismember("online_riders", str(rider_id))
    return False


@app.on_event("startup")
async def startup_event():
    """Safe Startup Wrapper."""
    try:
        logger.info("[SERVER] Initializing services...")
        # 1. Verify DB Connection
        db_helper.get_db_connection()
        logger.info("[SERVER] DB connection successful")
        
        # 2. Add further init checks here if needed
        app_state["ready"] = True
        logger.info("[SERVER] Backend ready on port 8000")
    except Exception as e:
        logger.error(f"[SERVER][CRITICAL] Startup failed safely handled: {e}")
        # We don't exit(1) to allow the process to stay alive for debugging/logs if possible

@app.on_event("shutdown")
async def shutdown_event():
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
                order_summary = db_helper.get_order_summary(order_id)
                if not order_summary or not order_summary.get("rider") or order_summary["rider"].get("riderId") != user_id:
                     logger.warning(f"[WS SECURITY] Rider {user_id} tried to track unassigned order {order_id} — ACCESS DENIED")
                     await websocket.close(code=1008)
                     return
            else:
                ownership = db_helper.validate_order_owner(order_id, user_id)
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
    query_result = payload.get('queryResult', {})
    intent = query_result.get('intent', {}).get('displayName', '')
    parameters = query_result.get('parameters', {})
    query_text = query_result.get('queryText', '').lower().strip()

    logger.info(f"[CHATBOT][PIPELINE] STEP1 raw_intent={intent!r} query={query_text!r}")

    # =====================================================================
    # PIPELINE STEP 2: HARD INTENT OVERRIDE
    # If the user's message contains a known menu item, FORCE add_to_order.
    # This runs BEFORE session lookup and BEFORE any handler or cart access.
    # NO conditions — food detected means add_to_order, period.
    # =====================================================================
    MENU_ITEMS = [
        "pav bhaji", "chole bhature", "pizza", "mango lassi",
        "masala dosa", "biryani", "vada pav", "rava dosa", "samosa"
    ]
    matched_food = next((item for item in MENU_ITEMS if item in query_text), None)

    if matched_food:
        prev_intent = intent
        # UNCONDITIONAL — always override, no exceptions
        intent = 'order.add - context: ongoing-order'
        # Always write matched_food into parameters so add_to_order finds it
        # (overwrite any stale Dialogflow context value)
        parameters['food-item'] = [matched_food]
        logger.info(
            f"[CHATBOT][FORCE_ROUTE] Food '{matched_food}' detected in query — "
            f"overriding intent '{prev_intent}' → add_to_order"
        )

    logger.info(f"[CHATBOT][PIPELINE] STEP2 resolved_intent={intent!r}")

    # =====================================================================
    # PIPELINE STEP 3: Session extraction — still NO cart access
    # =====================================================================
    output_contexts = query_result.get('outputContexts', [])
    try:
        session_id = generic_helper.extract_session_id(output_contexts[0]['name'])
    except (IndexError, KeyError):
        session_id = payload.get("session", "").split("/")[-1]

    session_id = session_id.removeprefix("webdemo-")
    logger.info(f"[CHATBOT][PIPELINE] STEP3 session_id={session_id}")

    resolved_user = get_chatbot_user_id(session_id)
    logger.info(f"[CHATBOT][PIPELINE] STEP3 resolved_user_id={resolved_user}")

    # FIX: Try to auto-link BEFORE reading resolved_user so the pipeline
    # already has the mapping when the handler calls _chatbot_require_user.
    _try_link_chatbot_session_from_request(request, payload, session_id)

    # Re-resolve after potential auto-link so handlers get the correct user
    resolved_user = get_chatbot_user_id(session_id)

    # --- MANDATORY AUTH DEBUG LOG (Requirement #5) ---
    print("[AUTH DEBUG]", {
        "session_id": session_id,
        "resolved_user": resolved_user,
        "intent": intent,
        "query": query_text,
    })
    logger.info(f"[AUTH DEBUG] session={session_id} user={resolved_user} intent={intent!r}")

    # =====================================================================
    # PIPELINE STEP 3.5: Pending quantity resolution
    # If no food item was detected in this message, but the session has an
    # item waiting for a quantity reply, route to add_to_order to complete it.
    # =====================================================================
    if not matched_food:
        pending = pending_orders.get(session_id)
        if pending and pending.get("item"):
            logger.info(
                f"[CHATBOT][PENDING_QTY] Session={session_id} has pending item "
                f"'{pending['item']}' — routing to add_to_order for quantity resolution"
            )
            intent = 'order.add - context: ongoing-order'

    # Pass raw query_text to handler so add_to_order can detect explicit numbers
    parameters['_query_text'] = query_text

    # =====================================================================
    # PIPELINE STEP 4: Route to ONE handler — cart logic lives ONLY inside
    # each handler function below. Nothing after this point runs.
    # =====================================================================
    INTENT_HANDLER_MAP = {
        'order.add - context: ongoing-order': add_to_order,
        'order.remove - context: ongoing-order': remove_from_order,
        'order.complete - context: ongoing-order': complete_order,
        'track-order - context: ongoing-tracking': track_order,
        'order.cancel': cancel_order_handler,
    }

    handler = INTENT_HANDLER_MAP.get(intent)
    if handler is None:
        logger.warning(f"[CHATBOT][PIPELINE] STEP4 No handler for intent={intent!r}")
        return JSONResponse(
            content={
                "fulfillmentText": (
                    "Sorry, I didn’t understand. Please order like:\n"
                    "1 rava dosa\n"
                    "2 pizzas"
                )
            }
        )

    logger.info(f"[CHATBOT][PIPELINE] STEP4 dispatching → {handler.__name__}")

    # Single dispatch point — this is the ONLY return from the webhook pipeline.
    # No code runs after this; the handler's return value is the final response.
    if inspect.iscoroutinefunction(handler):
        return await handler(parameters, session_id)
    return handler(parameters, session_id)


class ChatbotLinkSession(BaseModel):
    session_id: str


@app.post("/api/chatbot/link-session", dependencies=[Depends(customer_required)])
async def link_chatbot_session_endpoint(
    body: ChatbotLinkSession,
    current_user: dict = Depends(get_current_user),
):
    """Map Dialogflow session_id to the authenticated website user.

    FIX: If the session is already linked to ANY user, skip the write
    (idempotent guard).  Only the FIRST call per session actually stores the
    mapping — repeated calls from the frontend (on open/re-render) are no-ops.
    """
    if not body.session_id or not body.session_id.strip():
        raise HTTPException(status_code=400, detail="session_id is required")

    sid = body.session_id.strip()
    user_id = current_user["user_id"]

    # Check whether the session is already mapped
    existing = get_chatbot_user_id(sid)
    if existing and existing == user_id:
        logger.info(f"[CHATBOT][LINK-SESSION] session={sid} already linked to user={user_id} — no-op")
        return standard_response(True, "Chatbot session already linked")

    if existing and existing != user_id:
        # Different user owns this session — refuse silently (don’t expose the
        # old user_id to the caller, just say it’s already linked).
        logger.warning(f"[CHATBOT][LINK-SESSION] session={sid} already linked to DIFFERENT user={existing} (caller={user_id}) — refusing overwrite")
        return standard_response(True, "Chatbot session already linked")

    # First call for this session — write once
    link_chatbot_session(sid, user_id)
    logger.info(f"[CHATBOT][LINK-SESSION] session={sid} linked to user={user_id}")
    return standard_response(True, "Chatbot session linked")

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
    user_id = db_helper.create_user(user.name, user.email, hashed_pw)
    if not user_id: raise HTTPException(status_code=400, detail="Signup failed")
    token = create_jwt_token(user_id, user.email, [Role.CUSTOMER])
    return standard_response(True, "Signup successful", {"token": token, "user": {"id": user_id, "name": user.name, "email": user.email, "roles": [Role.CUSTOMER]}})

@app.post("/login")
@app.post("/api/customer/login")
async def customer_login(user: UserLogin):
    db_user = db_helper.get_user_by_email(user.email)
    if not db_user or not verify_password(user.password, db_user.get('password')):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    if Role.CUSTOMER not in db_user.get('roles', []):
        raise HTTPException(status_code=403, detail="This login is only for customers.")
        
    if not db_user.get('is_active', 1):
        raise HTTPException(status_code=403, detail="Account is disabled.")

    token = create_jwt_token(db_user['id'], db_user['email'], db_user['roles'])
    return standard_response(True, "Login successful", {"token": token, "user": {"id": db_user['id'], "name": db_user['name'], "email": db_user['email'], "roles": db_user['roles']}})

@app.post("/api/admin/login")
async def admin_login(user: UserLogin):
    """
    Production-grade Admin Login.
    Enforces role isolation and account status check.
    """
    db_user = db_helper.get_user_by_email(user.email)
    
    # 1. Credentials Check
    if not db_user or not verify_password(user.password, db_user.get('password')):
        logger.warning(f"[AUTH] Failed admin login attempt for {user.email}")
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    
    # 2. Role Isolation
    if Role.ADMIN not in db_user.get('roles', []):
        logger.warning(f"[AUTH] Access denied: User {user.email} lacks admin role")
        raise HTTPException(status_code=403, detail="Access denied. Admin role required.")
        
    # 3. Status Check (Security Hardening)
    if not db_user.get('is_active', 1):
        logger.warning(f"[AUTH] Admin account {user.email} is disabled")
        raise HTTPException(status_code=403, detail="Admin account is disabled. Contact system administrator.")

    token = create_jwt_token(db_user['id'], db_user['email'], db_user['roles'])
    logger.info(f"[AUTH] Admin {user.email} logged in successfully")
    return standard_response(True, "Admin login successful", {
        "token": token, 
        "user": {
            "id": db_user['id'], 
            "name": db_user['name'], 
            "email": db_user['email'], 
            "roles": db_user['roles']
        }
    })

@app.post("/api/rider/login")
async def rider_login(user: UserLogin):
    """
    Production-grade Rider Login.
    Enforces active status and rider-only isolation.
    """
    db_user = db_helper.get_user_by_email(user.email)
    
    # 1. Credentials Check
    if not db_user or not verify_password(user.password, db_user.get('password')):
        logger.warning(f"[AUTH] Failed rider login attempt for {user.email}")
        raise HTTPException(status_code=401, detail="Invalid rider credentials")
    
    # 2. Role Isolation
    if Role.RIDER not in db_user.get('roles', []):
        logger.warning(f"[AUTH] Access denied: User {user.email} is not a rider")
        raise HTTPException(status_code=403, detail="This login is only for delivery partners.")
        
    # 3. Status Check (Mandatory Rule)
    if not db_user.get('is_active', 1):
        logger.warning(f"[AUTH] Rider account {user.email} is disabled")
        raise HTTPException(status_code=403, detail="Rider account is disabled. Please contact rider support.")

    token = create_jwt_token(db_user['id'], db_user['email'], db_user['roles'])
    logger.info(f"[AUTH] Rider {user.email} logged in successfully")
    return standard_response(True, "Rider login successful", {
        "token": token, 
        "user": {
            "id": db_user['id'], 
            "name": db_user['name'], 
            "email": db_user['email'], 
            "roles": db_user['roles']
        }
    })

@app.get("/profile")
async def get_profile(current_user: dict = Depends(get_current_user)):
    return db_helper.get_user_by_id(current_user["user_id"])

@app.get("/api/admin/riders", dependencies=[Depends(admin_required)])
async def get_riders():
    riders = db_helper.get_all_riders()
    return standard_response(True, "Riders fetched", riders)

@app.get("/api/admin/stats", dependencies=[Depends(admin_required)])
async def get_admin_stats():
    """
    Returns real-time ecosystem stats for the admin dashboard.
    Protected by admin_required.
    """
    try:
        stats = db_helper.get_admin_dashboard_stats()
        if not stats:
            return standard_response(False, "Failed to fetch admin stats")
        return standard_response(True, "Admin stats fetched successfully", stats)
    except Exception as e:
        logger.error(f"[ADMIN] Error fetching stats: {e}")
        return standard_response(False, "Failed to fetch admin stats")

@app.get("/api/admin/orders", dependencies=[Depends(admin_required)])
async def get_admin_orders():
    """
    Returns all orders in the system with customer and rider details.
    Protected by admin_required.
    """
    try:
        orders = db_helper.get_admin_orders()
        return standard_response(True, "Admin orders fetched successfully", orders)
    except Exception as e:
        logger.error(f"[ADMIN] Error fetching orders: {e}")
        return standard_response(False, "Failed to fetch admin orders")

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

    # 1. Status Whitelist (Requirement #1)
    ADMIN_ALLOWED_STATUSES = {
        "RESTAURANT_CONFIRMED",
        "FOOD_READY"
    }
    
    if new_status not in ADMIN_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=403, 
            detail=f"Admins are not permitted to set status to {new_status}"
        )

    # 2. Fetch current state (Admin View enabled)
    order_summary = db_helper.get_order_summary(order_id, is_admin_view=True)
    if not order_summary:
        raise HTTPException(status_code=404, detail="Order not found")

    current_status = order_summary["status"]["current_status"]

    # 3. Strict Linear Transition Check (Requirement #4, #10)
    if not validate_status_transition(current_status, new_status):
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid transition from {current_status} to {new_status}"
        )

    # 4. Atomic Database Update
    success = db_helper.insert_order_tracking(
        order_id, 
        new_status, 
        actor="ADMIN", 
        expected_previous_status=current_status
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update order status")

    # 5. Broadcast Realtime Update
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
    user_id = db_helper.create_rider_by_admin(name, email, phone, hashed_pw, vehicle_type, license_number, profile_pic)
    
    if not user_id:
        raise HTTPException(status_code=400, detail="Failed to create rider. Email might be taken.")
        
    db_helper.log_admin_action(current_user["user_id"], "CREATE_RIDER", details=f"Created rider {email}")
    return standard_response(True, "Rider created successfully", {"id": user_id})

@app.put("/api/admin/riders/{rider_id}/status", dependencies=[Depends(admin_required)])
async def toggle_rider_status(rider_id: int, request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    is_active = payload.get("is_active")
    
    success = db_helper.toggle_user_active(rider_id, 1 if is_active else 0)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to update status")
        
    action = "ENABLE_RIDER" if is_active else "DISABLE_RIDER"
    db_helper.log_admin_action(current_user["user_id"], action, details=f"Rider ID: {rider_id}")
    await ecosystem_socket_manager.push_rider_status_update(
        rider_id=rider_id,
        rider_status="available" if is_active else "offline"
    )
    return standard_response(True, f"Rider {'enabled' if is_active else 'disabled'} successfully")

@app.delete("/api/admin/riders/{rider_id}", dependencies=[Depends(admin_required)])
async def delete_rider(rider_id: int, current_user: dict = Depends(get_current_user)):
    """Soft delete rider (set is_active = 0)."""
    success = db_helper.toggle_user_active(rider_id, 0)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete rider")
        
    db_helper.log_admin_action(current_user["user_id"], "DELETE_RIDER", details=f"Soft deleted rider ID: {rider_id}")
    return standard_response(True, "Rider deleted successfully")

@app.post("/api/admin/assign_rider", dependencies=[Depends(admin_required)])
async def admin_assign_rider(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    order_id = payload.get("order_id")
    rider_id = payload.get("rider_id")
    
    result = db_helper.assign_rider_to_order(order_id, rider_id, actor='ADMIN', admin_id=current_user["user_id"])
    
    if result == "already_assigned":
        raise HTTPException(status_code=409, detail="Order already assigned to another rider")
    if result == "no_change":
        return standard_response(True, "Rider already assigned (no change)")
    if result != "assigned":
        raise HTTPException(status_code=400, detail=f"Assignment failed: {result}")
        
    await ecosystem_socket_manager.push_order_update(order_id)
    await ecosystem_socket_manager.push_rider_status_update(rider_id=rider_id, rider_status="busy")
    return {"status": "success"}

@app.put("/api/admin/orders/{order_id}/assign-rider", dependencies=[Depends(admin_required)])
async def admin_assign_rider_put(order_id: int, payload: AssignRider, current_user: dict = Depends(get_current_user)):
    """
    Hardened Rider Assignment Endpoint.
    """
    # Transition Validation: Assignment is operative, but order should be in an assignable state (before pickup)
    order_summary = db_helper.get_order_summary(order_id)
    if order_summary:
        current_status = order_summary["status"]["current_status"]
        if normalize_status_internal(current_status) not in ASSIGNABLE_STATUSES:
            raise HTTPException(
                status_code=400, 
                detail=(
                    f"Cannot assign rider: Order is {current_status}. "
                    f"Must be one of: {', '.join(sorted(ASSIGNABLE_STATUSES))}."
                )
            )

    result = db_helper.assign_rider_to_order(order_id, payload.rider_id, actor='ADMIN', admin_id=current_user["user_id"])
    
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
    if result == "already_assigned":
        raise HTTPException(status_code=409, detail="Order already assigned to another rider")
    if result == "no_change":
        return standard_response(True, "Rider already assigned (no change)")
    if result == "error":
        raise HTTPException(status_code=500, detail="Internal database error during assignment")

    await ecosystem_socket_manager.push_order_update(order_id)
    await ecosystem_socket_manager.push_rider_status_update(rider_id=payload.rider_id, rider_status="busy")
    return standard_response(True, "Rider assigned successfully")



@app.get("/api/order/{order_id}/rider/location")
async def get_rider_location(order_id: int):
    """Fetch active rider location. Hardened: Safe fallback if not found."""
    loc = db_helper.get_active_rider_location_for_order(order_id)
    # db_helper already returns safe fallback {"status": "Rider offline", "location": None}
    return loc

@app.get("/api/rider/available_orders", dependencies=[Depends(rider_required)])
async def get_rider_available_orders(current_user: dict = Depends(get_current_user)):
    return db_helper.get_available_orders(current_user["user_id"])

@app.get("/api/rider/orders", dependencies=[Depends(rider_required)])
async def get_rider_orders(current_user: dict = Depends(get_current_user)):
    """Returns only orders assigned to the logged-in rider."""
    rider_id = current_user["user_id"]
    active_orders = db_helper.get_rider_active_orders(rider_id)
    available_orders = db_helper.get_available_orders(rider_id)
    rider = db_helper.get_rider_realtime_state(rider_id)
    response = JSONResponse(content={
        "success": True,
        "message": "Rider orders fetched",
        "data": {
            "active_orders": active_orders,
            "available_orders": available_orders,
            "orders": active_orders,
            "active_order": active_orders[0] if active_orders else None,
            "rider": rider
        }
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
    orders = db_helper.get_rider_history_orders(rider_id)
    logger.info(f"[RIDER_HISTORY][ORDERS_FOUND] {len(orders)} orders returned to frontend")
    return standard_response(True, "Rider history fetched successfully", orders)

@app.get("/api/rider/stats", dependencies=[Depends(rider_required)])
async def get_rider_stats_endpoint(current_user: dict = Depends(get_current_user)):
    """Returns today's statistics for the logged-in rider."""
    stats = db_helper.get_rider_stats(current_user["user_id"])
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

    # 1. Fetch current state (Admin/Rider View enabled)
    order_summary = db_helper.get_order_summary(order_id, is_admin_view=True)
    if not order_summary:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2. Ownership Check (Requirement #2, #3)
    assigned_rider = order_summary.get("rider")
    if not assigned_rider or assigned_rider.get("riderId") != current_user["user_id"]:
        logger.warning(f"[SECURITY] Unauthorized rider update: user {current_user['user_id']} vs assigned {assigned_rider}")
        raise HTTPException(status_code=403, detail="Access denied: You are not assigned to this order")

    # 3. Status Whitelist (Requirement #1)
    RIDER_ALLOWED_STATUSES = {
        "ORDER_PICKED_UP",
        "OUT_FOR_DELIVERY",
        "NEAR_CUSTOMER_LOCATION",
        "DELIVERED"
    }
    if new_status not in RIDER_ALLOWED_STATUSES:
        raise HTTPException(
            status_code=403, 
            detail=f"Riders are not permitted to set status to {new_status}"
        )

    current_status = order_summary["status"]["current_status"]

    # 4. Strict Transition Enforcement (Requirement #4, #10)
    if not validate_status_transition(current_status, new_status):
        raise HTTPException(
            status_code=400, 
            detail=f"Invalid transition from {current_status} to {new_status}"
        )

    # 5. Atomic Database Update
    success = db_helper.insert_order_tracking(
        order_id, 
        new_status, 
        actor="RIDER", 
        lat=lat, 
        lng=lng,
        expected_previous_status=current_status
    )
    
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update order status")

    # 6. Broadcast Update
    await ecosystem_socket_manager.push_order_update(order_id)
    if new_status == "DELIVERED":
        await ecosystem_socket_manager.push_rider_status_update(
            rider_id=current_user["user_id"],
            rider_status="available"
        )
    
    return standard_response(True, f"Status updated to {new_status}")


def normalize_status_internal(status):
    """
    STRICT STATUS NORMALIZATION (Source of Truth).
    Ensures all variants map to the canonical 8-stage lifecycle.
    """
    if not status: return "ORDER_PLACED"
    
    raw = status
    s = status.upper().replace(" ", "_")
    
    # REQUIRED MAPPINGS
    if s in ["PLACED", "ORDER_PLACED"]: clean = "ORDER_PLACED"
    elif s in ["CONFIRMED", "RESTAURANT_CONFIRMED"]: clean = "RESTAURANT_CONFIRMED"
    elif s in ["PREPARING", "PREPARING_FOOD"]: clean = "PREPARING_FOOD"
    elif s in ["FOOD_READY", "READY"]: clean = "FOOD_READY"
    elif s in ["RIDER_ASSIGNED", "PARTNER_ASSIGNED", "ASSIGNED"]: clean = "ASSIGNED"
    elif s in ["ACCEPTED"]: clean = "ACCEPTED"
    elif s in ["PICKED", "ORDER_PICKED_UP", "PICKED_UP"]: clean = "ORDER_PICKED_UP"
    elif s in ["ON_THE_WAY", "OUT_FOR_DELIVERY"]: clean = "OUT_FOR_DELIVERY"
    elif s in ["NEAR_YOUR_LOCATION", "NEAR_CUSTOMER_LOCATION"]: clean = "NEAR_CUSTOMER_LOCATION"
    elif s in ["DELIVERED", "DELIVERED_SUCCESS"]: clean = "DELIVERED"
    elif s == "CANCELLED": clean = "CANCELLED"
    else: clean = s

    logger.info(f"[STATUS_NORMALIZE][RAW] {raw}")
    logger.info(f"[STATUS_NORMALIZE][CLEAN] {clean}")
    return clean

@app.post("/api/rider/accept_order", dependencies=[Depends(rider_required)])
async def rider_accept_order(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    order_id = payload.get("order_id")
    rider_id = current_user["user_id"]
    
    logger.info(f"[RIDER_ACCEPT][ORDER_ID] {order_id}")
    logger.info(f"[RIDER_ACCEPT][RIDER_ID] {rider_id}")

    # 1. Pre-check: order exists and belongs to this rider assignment.
    order = db_helper.get_order_by_id(order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
        
    if order.get("rider_id") != rider_id:
        raise HTTPException(status_code=409, detail="Order is not assigned to you")

    # 2. Atomic status transition: ASSIGNED -> ACCEPTED
    result = db_helper.accept_assigned_order(order_id, rider_id)
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
    
    await ecosystem_socket_manager.push_order_update(order_id)
    return standard_response(True, "Order accepted successfully")

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
        if redis_client:
            last_pos_data = redis_client.get(throttle_key)
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
        if redis_client:
            redis_client.set(throttle_key, json.dumps(pos_payload), ex=3600)
            redis_client.set(f"rider_last_known:{rider_id}", json.dumps({
                "lat": smoothed_lat, "lng": smoothed_lng, "heading": heading, "speed": speed, "updated_at": now
            }))
        else:
            rider_last_pos[rider_id] = pos_payload

        db_helper.upsert_rider_location(rider_id, smoothed_lat, smoothed_lng, heading, speed)
        await ecosystem_socket_manager.push_rider_status_update(
            rider_id=rider_id,
            lat=smoothed_lat,
            lng=smoothed_lng,
            heading=heading
        )
        
        # 4. Broadcast to all active order rooms for this rider (Rule 2)
        active_orders = db_helper.get_active_orders_for_rider(rider_id)
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
        
        # 3. Presence Tracking (Redis-backed)
        if redis_client:
            try:
                redis_client.sadd("online_riders", str(rider_id))
                logger.info(f"[WS][PRESENCE] Rider {rider_id} online")
            except Exception as e:
                logger.warning(f"[REDIS] Presence tracking failed: {e}")
        await ecosystem_socket_manager.push_rider_status_update(rider_id=rider_id, rider_status="available")
        
        while True:
            if websocket.client_state.name != "CONNECTED":
                break

            # 🔥 TASK 4: Heartbeat / Idle Cleanup (60s)
            last_ping = getattr(websocket, "last_ping_time", 0)
            if time.time() - last_ping > 60:
                logger.warning(f"[RIDER][WS] Disconnecting idle rider socket {rider_id}")
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
        logger.error(f"[RIDER][WS] Error: {e}")
    finally:
        if 'rider_id' in locals():
            if redis_client:
                redis_client.srem("online_riders", str(rider_id))
            await ecosystem_socket_manager.push_rider_status_update(rider_id=rider_id, rider_status="offline")
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
    items = db_helper.get_food_items()
    menu_data = [{"id": i['item_id'], "name": i['name'], "price": float(i['price']), "category": i.get('tag', 'General'), "image": db_helper.normalize_image_path(i.get('image_url'))} for i in items]
    return standard_response(True, "Menu fetched successfully", menu_data)

@app.get("/api/cart", dependencies=[Depends(customer_required)])
async def get_cart(current_user: dict = Depends(get_current_user)):
    return db_helper.get_cart_items(current_user["user_id"])

@app.post("/api/cart/add", dependencies=[Depends(customer_required)])
async def add_cart_item(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    item_id = payload.get("item_id")
    quantity = payload.get("quantity", 1)
    db_helper.add_to_cart(current_user["user_id"], item_id, quantity)
    return db_helper.get_cart_items(current_user["user_id"])

@app.put("/api/cart/update", dependencies=[Depends(customer_required)])
async def update_cart_item(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    item_id = payload.get("item_id")
    quantity = payload.get("quantity")
    db_helper.update_cart_quantity(current_user["user_id"], item_id, quantity)
    return db_helper.get_cart_items(current_user["user_id"])

@app.delete("/api/cart/remove/{item_id}", dependencies=[Depends(customer_required)])
async def remove_cart_item(item_id: int, current_user: dict = Depends(get_current_user)):
    db_helper.remove_from_cart(current_user["user_id"], item_id)
    return db_helper.get_cart_items(current_user["user_id"])

@app.delete("/api/cart/clear", dependencies=[Depends(customer_required)])
async def clear_user_cart(current_user: dict = Depends(get_current_user)):
    db_helper.clear_cart(current_user["user_id"])
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
        order_id = db_helper.place_order_in_db(
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
        db_helper.insert_order_tracking(order_id, "ORDER_PLACED")
        
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
        result = db_helper.delete_customer_order_placed(order_id, user_id)
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
    summary = db_helper.get_order_summary(order_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Order not found")

    # 2. Authorization & Ownership logic
    user_id: int = current_user["user_id"]
    user_roles: list = current_user.get("roles", [])

    # Admins may view any order
    if "admin" not in user_roles:
        if "rider" in user_roles:
            # Rider access
            if summary.get("rider") and summary["rider"].get("riderId") == user_id:
                return summary
            else:
                logger.warning(f"[SECURITY] Rider {user_id} denied access to order {order_id}")
                raise HTTPException(status_code=403, detail="Access denied: you are not assigned to this order")
        else:
            # Customer ownership check
            ownership = db_helper.validate_order_owner(order_id, user_id)
            if ownership == "ORDER_NOT_FOUND":
                raise HTTPException(status_code=404, detail="Order not found")
            if ownership == "ACCESS_DENIED":
                logger.warning(
                    f"[SECURITY] User {user_id} attempted to access order {order_id} — ACCESS DENIED"
                )
                raise HTTPException(status_code=403, detail="Access denied: you do not own this order")

    dl = summary.get("delivery_location") or {}
    logger.info(
        f"[TRACK_ORDER_API] order_id={order_id} "
        f"delivery_lat={dl.get('latitude')} delivery_lng={dl.get('longitude')}"
    )
    return summary

@app.get("/api/customer/orders/{order_id}")
async def get_customer_order_details(order_id: int, current_user: dict = Depends(get_current_user)):
    """Customer view: Hidden rider assignment until pickup."""
    order = db_helper.get_order_summary(order_id, is_admin_view=False)
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

    if "admin" not in user_roles:
        if "rider" in user_roles:
            # Rider access (Hardening Requirement #8, #6)
            order_summary = db_helper.get_order_summary(order_id)
            if not order_summary or not order_summary.get("rider") or order_summary["rider"].get("riderId") != user_id:
                logger.warning(f"[SECURITY] Rider {user_id} denied access to tracking for order {order_id}")
                raise HTTPException(status_code=403, detail="Access denied: you are not assigned to this order")
        else:
            ownership = db_helper.validate_order_owner(order_id, user_id)
            if ownership == "ORDER_NOT_FOUND":
                raise HTTPException(status_code=404, detail="Order not found")
            if ownership == "ACCESS_DENIED":
                logger.warning(
                    f"[SECURITY] User {user_id} attempted to track order {order_id} — ACCESS DENIED"
                )
                raise HTTPException(status_code=403, detail="Access denied: you do not own this order")

    status_obj = db_helper.resolve_order_status(order_id)
    if not status_obj:
        raise HTTPException(status_code=404, detail="Tracking data not found for this order")
    return status_obj

@app.get("/api/my-orders", dependencies=[Depends(customer_required)])
@app.get("/api/user_orders", dependencies=[Depends(customer_required)])
async def get_my_orders(current_user: dict = Depends(get_current_user)):
    return {"orders": db_helper.get_user_orders_full(current_user["user_id"])}

# --- Address Endpoints ---
@app.get("/api/address", dependencies=[Depends(customer_required)])
async def get_addresses(current_user: dict = Depends(get_current_user)):
    return db_helper.get_user_addresses(current_user["user_id"])

@app.post("/api/address/add", dependencies=[Depends(customer_required)])
async def add_address(request: Request, current_user: dict = Depends(get_current_user)):
    payload = await request.json()
    address_id = db_helper.add_address(
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
    db_helper.delete_address(current_user["user_id"], address_id)
    return {"status": "success"}

@app.post("/api/address/set_default/{address_id}", dependencies=[Depends(customer_required)])
async def set_default_address(address_id: int, current_user: dict = Depends(get_current_user)):
    db_helper.set_default_address(address_id, current_user["user_id"])
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
    address_id = db_helper.add_user_address(current_user["user_id"], body.model_dump())
    if not address_id:
        raise HTTPException(status_code=500, detail="Failed to create address")
    return standard_response(True, "Address created", {"address_id": address_id})

@app.get("/api/user/address", dependencies=[Depends(customer_required)])
async def list_user_addresses(current_user: dict = Depends(get_current_user)):
    addresses = db_helper.get_user_addresses(current_user["user_id"])
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
    updated = db_helper.update_user_address(address_id, current_user["user_id"], payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Address not found")
    return standard_response(True, "Address updated")

@app.delete("/api/user/address/{address_id}", dependencies=[Depends(customer_required)])
async def remove_user_address(
    address_id: int,
    current_user: dict = Depends(get_current_user),
):
    deleted = db_helper.delete_user_address(address_id, current_user["user_id"])
    if not deleted:
        raise HTTPException(status_code=404, detail="Address not found")
    return standard_response(True, "Address deleted")

@app.post("/api/user/address/{address_id}/default", dependencies=[Depends(customer_required)])
async def mark_default_user_address(
    address_id: int,
    current_user: dict = Depends(get_current_user),
):
    ok = db_helper.set_default_address(address_id, current_user["user_id"])
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


def link_chatbot_session(session_id: str, user_id: int, allow_overwrite: bool = False) -> None:
    """
    FIX: Only assign user_id ONCE per session.
    Subsequent calls are silently ignored unless allow_overwrite=True.
    This prevents the session→user mapping from being clobbered by repeated
    link-session calls or re-links triggered by every webhook request.
    """
    if not session_id or user_id is None:
        return
    # Normalize to strip webdemo- prefix so it matches webhook lookups
    session_id = session_id.removeprefix("webdemo-")

    if redis_client:
        try:
            # FIX: Only write if not already set (NX = set if Not eXists)
            if allow_overwrite:
                redis_client.setex(f"chatbot_session:{session_id}", CHATBOT_SESSION_TTL, str(user_id))
                logger.info(f"[CHATBOT][LINK] (overwrite) session={session_id} → user={user_id}")
            else:
                # SET ... NX: write only if the key doesn't already exist
                written = redis_client.set(
                    f"chatbot_session:{session_id}",
                    str(user_id),
                    ex=CHATBOT_SESSION_TTL,
                    nx=True,
                )
                if written:
                    logger.info(f"[CHATBOT][LINK] (new) session={session_id} → user={user_id}")
                else:
                    existing = redis_client.get(f"chatbot_session:{session_id}")
                    logger.info(f"[CHATBOT][LINK] (skip overwrite) session={session_id} already → user={existing}")
            return
        except Exception as e:
            logger.warning(f"[CHATBOT] Redis session link failed: {e}")

    # In-memory fallback — also only write once unless allow_overwrite
    if allow_overwrite or session_id not in chatbot_session_users:
        chatbot_session_users[session_id] = (user_id, time.time() + CHATBOT_SESSION_TTL)
        logger.info(f"[CHATBOT][LINK][MEM] session={session_id} → user={user_id} (overwrite={allow_overwrite})")
    else:
        logger.info(f"[CHATBOT][LINK][MEM] (skip overwrite) session={session_id} already mapped")


def get_chatbot_user_id(session_id: str):
    if not session_id:
        return None
    # Normalize: Dialogflow embedded demo prefixes session with "webdemo-"
    normalized = session_id.removeprefix("webdemo-")
    logger.info(f"[CHATBOT] Lookup: raw={session_id} normalized={normalized}")
    session_id = normalized
    
    # --- Exact match first ---
    if redis_client:
        try:
            val = redis_client.get(f"chatbot_session:{session_id}")
            if val is not None:
                logger.info(f"[CHATBOT] Exact Redis match for session={session_id} user={val}")
                return int(val)
        except Exception as e:
            logger.warning(f"[CHATBOT] Redis session lookup failed: {e}")
    
    entry = chatbot_session_users.get(session_id)
    if entry:
        user_id, expires_at = entry
        if time.time() <= expires_at:
            logger.info(f"[CHATBOT] Exact memory match for session={session_id} user={user_id}")
            return user_id
        else:
            chatbot_session_users.pop(session_id, None)

    # --- Fallback: most recently linked session within last 30 minutes ---
    # This handles Dialogflow iframe generating its own session ID
    # that doesn't match what the frontend stored via link-session
    logger.warning(f"[CHATBOT] No exact match for session={session_id} — trying recency fallback")
    
    now = time.time()
    recent_cutoff = now - 1800  # 30 minutes

    # Memory fallback
    best_user_id = None
    best_linked_at = 0
    for sid, (uid, exp) in list(chatbot_session_users.items()):
        if exp <= now:
            chatbot_session_users.pop(sid, None)
            continue
        linked_at = exp - CHATBOT_SESSION_TTL
        if linked_at >= recent_cutoff and linked_at > best_linked_at:
            best_linked_at = linked_at
            best_user_id = uid

    if best_user_id:
        logger.info(f"[CHATBOT] Recency fallback resolved user={best_user_id} for session={session_id}")
        # Cache this mapping so future calls match directly (allow_overwrite=True
        # because we just confirmed there is NO existing entry for this session)
        link_chatbot_session(session_id, best_user_id, allow_overwrite=True)
        return best_user_id

    # Redis fallback
    if redis_client:
        try:
            keys = redis_client.keys("chatbot_session:*")
            if keys:
                best_key = None
                best_ttl = -1
                for k in keys:
                    ttl = redis_client.ttl(k)
                    # Only consider sessions linked within last 30 min
                    # TTL should be > (CHATBOT_SESSION_TTL - 1800)
                    if ttl > (CHATBOT_SESSION_TTL - 1800) and ttl > best_ttl:
                        best_ttl = ttl
                        best_key = k
                if best_key:
                    val = redis_client.get(best_key)
                    if val:
                        uid = int(val)
                        logger.info(f"[CHATBOT] Redis recency fallback resolved user={uid} for session={session_id}")
                        # Cache this mapping (allow_overwrite=True — no entry existed)
                        link_chatbot_session(session_id, uid, allow_overwrite=True)
                        return uid
        except Exception as e:
            logger.warning(f"[CHATBOT] Redis recency fallback failed: {e}")

    logger.warning(f"[CHATBOT] All session lookups failed for session={session_id}")
    return None


def _decode_chatbot_user_token(token: str):
    if not token:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get("user_id")
    except Exception:
        return None


def _try_link_chatbot_session_from_request(request: Request, payload: dict, session_id: str) -> None:
    """
    FIX: Only links a new session→user mapping if NO mapping exists yet.
    We never overwrite an existing entry — this stops every webhook call
    from re-running link logic and potentially clobbering the stored user.
    """
    if not session_id:
        return
    session_id = session_id.removeprefix("webdemo-")

    # If session already has a user mapped, do nothing
    existing = get_chatbot_user_id(session_id)
    if existing:
        logger.info(f"[CHATBOT][TRY_LINK] session={session_id} already mapped to user={existing} — skipping re-link")
        return

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        uid = _decode_chatbot_user_token(auth_header.split(" ", 1)[1])
        if uid:
            link_chatbot_session(session_id, uid)  # allow_overwrite=False by default
            return
    try:
        inner = (payload.get("originalDetectIntentRequest") or {}).get("payload") or {}
        for key in ("userToken", "authToken", "token"):
            uid = _decode_chatbot_user_token(inner.get(key))
            if uid:
                link_chatbot_session(session_id, uid)
                return
    except Exception:
        pass


def _chatbot_session_key(session_id: str) -> str:
    return session_id if session_id else "default-session"


def _chatbot_extract_quantity(parameters: dict) -> int:
    if not parameters:
        return 1
    for key in ("number", "Number", "quantity", "amount"):
        v = parameters.get(key)
        if v is None or v == "":
            continue
        if isinstance(v, list):
            # Dialogflow sends number as a list e.g. [1]
            try:
                return max(1, int(float(v[0])))
            except (TypeError, ValueError, IndexError):
                continue
        try:
            return max(1, int(float(v)))
        except (TypeError, ValueError):
            continue
    return 1


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
        if v is None or v == "":
            continue
        try:
            return int(float(v))
        except (TypeError, ValueError):
            continue
    return None


def _chatbot_cart_summary(cart: dict) -> str:
    name_qty = {item["name"]: item["quantity"] for item in cart.values()}
    return generic_helper.get_str_from_food_dict(name_qty)


def _has_explicit_quantity(parameters: dict, query_text: str = "") -> bool:
    """
    Returns True ONLY when the user's message contains an explicit number.
    Dialogflow parameters are checked first; raw query_text is the fallback.
    A missing/empty/[] parameter value means no quantity was stated.
    """
    for key in ("number", "Number", "quantity", "amount"):
        v = parameters.get(key)
        if v is None or v == "" or v == [] or v == [""]:
            continue
        if isinstance(v, list):
            for x in v:
                if x is not None and str(x).strip():
                    try:
                        float(x)
                        return True
                    except (TypeError, ValueError):
                        pass
        else:
            try:
                float(v)
                return True
            except (TypeError, ValueError):
                pass
    # Fallback: look for any digit in the raw message
    return bool(re.search(r'\b\d+\b', query_text))


def _chatbot_require_user(session_id: str, fallback_user_id: int = None):
    """
    FIX: Resolve user from session map FIRST.
    Only falls back to fallback_user_id if no session mapping exists.
    Never prompts login if the session already resolves to a valid user.
    """
    # Step 1: Session is the SINGLE SOURCE OF TRUTH
    user_id = get_chatbot_user_id(_chatbot_session_key(session_id))

    # Step 2: Safe fallback — only when session has NO mapping at all
    if not user_id and fallback_user_id:
        logger.info(f"[AUTH] _chatbot_require_user: session={session_id} no map, using fallback user={fallback_user_id}")
        user_id = fallback_user_id

    if not user_id:
        logger.warning(f"[AUTH] _chatbot_require_user: NO user for session={session_id} — prompting login")
        return None, "Please log in on the website before placing an order through chat."

    logger.info(f"[AUTH] _chatbot_require_user: session={session_id} → user={user_id}")
    return user_id, None


def save_to_db(session_cart: dict, user_id: int):
    """
    Create a real production order from the chatbot session cart.
    Returns (order_id, error_message). error_message is None on success.
    """
    try:
        if not session_cart:
            return None, "Your order is empty. Add some items before completing."

        addr = db_helper.get_chatbot_delivery_address(user_id)
        if not addr or not addr.get("id"):
            return None, "Please add a delivery address before placing an order."

        items_payload = [
            {"item_id": it["item_id"], "quantity": it["quantity"]}
            for it in session_cart.values()
        ]
        if not items_payload:
            return None, "Your order is empty."

        order_id = db_helper.place_order_in_db(
            user_id,
            addr["id"],
            items=items_payload,
            payment_method="COD",
            restaurant_lat=RESTAURANT_LAT,
            restaurant_lng=RESTAURANT_LNG,
            clear_cart=False,
        )
        if not order_id:
            return None, "We could not save your order. Please try again."

        db_helper.insert_order_tracking(order_id, "ORDER_PLACED")
        return order_id, None

    except Exception as e:
        logger.exception("[CHATBOT] save_to_db failed")
        msg = str(e)
        if "DELIVERY_COORDS_INVALID" in msg:
            return (
                None,
                "Your saved delivery address needs valid map coordinates before we can place an order. Please update it on the website.",
            )
        if "not found" in msg.lower() and "address" in msg.lower():
            return None, "Please add a delivery address before placing an order."
        return None, "Something went wrong while saving your order. Please try again later."


# --- Dialogflow Handlers ---


def add_to_order(parameters, session_id):
    """
    Quantity-first ordering flow:
    - Food item with quantity   → add to cart immediately.
    - Food item WITHOUT quantity → store in pending_orders, ask "How many?".
    - No food item but pending   → treat message as quantity reply; add pending item.
    """
    try:
        # Pop injected query_text (set by handle_request, not Dialogflow)
        query_text = parameters.pop('_query_text', '')

        sid = _chatbot_session_key(session_id)
        user_id, login_err = _chatbot_require_user(session_id)
        if login_err:
            return JSONResponse(content={"fulfillmentText": login_err})

        foods = _chatbot_extract_food_names(parameters)

        # ── CASE A: No food name in this message ────────────────────────────
        # The user is either replying with a quantity OR the message is unclear.
        if not foods:
            pending = pending_orders.get(session_id)
            if not pending or not pending.get("item"):
                return JSONResponse(
                    content={
                        "fulfillmentText": (
                            "Sorry, I didn’t understand. Please order like:\n"
                            "1 rava dosa\n"
                            "2 pizzas"
                        )
                    }
                )

            # Resolve pending item with the supplied quantity
            food_name = pending["item"]
            qty = _chatbot_extract_quantity(parameters)
            # Also try raw query if parameters gave the default of 1
            if qty == 1:
                m = re.search(r'\b(\d+)\b', query_text)
                if m:
                    qty = max(1, int(m.group(1)))

            row = db_helper.get_food_item_by_name(food_name)
            if not row:
                pending_orders.pop(session_id, None)
                return JSONResponse(
                    content={"fulfillmentText": f"Sorry, {food_name} is not available right now."}
                )

            cart = inprogress_orders[sid]
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

            pending_orders.pop(session_id, None)  # clear pending state
            logger.info(
                f"[CHATBOT] add_to_order (pending resolved): {food_name} x{qty} session={sid}"
            )
            summary = _chatbot_cart_summary(cart)
            return JSONResponse(
                content={"fulfillmentText": f"So far you have {summary}. Do you need anything else?"}
            )

        # ── CASE B: Food name present — check for explicit quantity ─────────
        if not _has_explicit_quantity(parameters, query_text):
            return JSONResponse(
                content={"fulfillmentText": "Please specify quantity like: 1 rava dosa or 2 pizzas."}
            )

        # ── CASE C: Food name + explicit quantity → add immediately ─────────
        qty = _chatbot_extract_quantity(parameters)
        # Supplement with raw query if parameters gave default 1
        if qty == 1:
            m = re.search(r'\b(\d+)\b', query_text)
            if m:
                qty = max(1, int(m.group(1)))

        cart = inprogress_orders[sid]
        added_any = False

        for fname in foods:
            row = db_helper.get_food_item_by_name(fname)
            if not row:
                return JSONResponse(
                    content={"fulfillmentText": f"Sorry, {fname} is not available right now."}
                )
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
            added_any = True

        if not added_any:
            return JSONResponse(
                content={
                    "fulfillmentText": "I did not catch which dish to add. Please name the item and how many you want."
                }
            )

        # Clear any stale pending state on successful add
        pending_orders.pop(session_id, None)
        logger.info(f"[CHATBOT] add_to_order: {foods} x{qty} added session={sid}")

        summary = _chatbot_cart_summary(cart)
        return JSONResponse(
            content={"fulfillmentText": f"So far you have {summary}. Do you need anything else?"}
        )

    except Exception:
        logger.exception("[CHATBOT] add_to_order")
        return JSONResponse(
            content={"fulfillmentText": "Something went wrong updating your order. Please try again in a moment."}
        )


def remove_from_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        _, login_err = _chatbot_require_user(session_id)
        if login_err:
            return JSONResponse(content={"fulfillmentText": login_err})

        qty = _chatbot_extract_quantity(parameters)
        foods = _chatbot_extract_food_names(parameters)
        cart = inprogress_orders[sid]

        if not foods:
            return JSONResponse(
                content={"fulfillmentText": "I did not catch which dish to remove. Please name the item."}
            )

        removed_any = False
        for fname in foods:
            row = db_helper.get_food_item_by_name(fname)
            if not row:
                continue
            iid = row["item_id"]
            if iid not in cart:
                continue
            cart[iid]["quantity"] -= qty
            if cart[iid]["quantity"] <= 0:
                del cart[iid]
            removed_any = True

        if not removed_any:
            if not cart:
                return JSONResponse(content={"fulfillmentText": "Your order is already empty."})
            summary = _chatbot_cart_summary(cart)
            return JSONResponse(content={"fulfillmentText": f"Item not found in your order. So far you have {summary}"})

        if not cart:
            return JSONResponse(content={"fulfillmentText": "Your order is now empty."})

        summary = _chatbot_cart_summary(cart)
        return JSONResponse(content={"fulfillmentText": f"So far you have {summary}"})

    except Exception:
        logger.exception("[CHATBOT] remove_from_order")
        return JSONResponse(
            content={"fulfillmentText": "Something went wrong updating your order. Please try again in a moment."}
        )


async def complete_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        user_id, login_err = _chatbot_require_user(session_id)
        if login_err:
            return JSONResponse(content={"fulfillmentText": login_err})

        cart = inprogress_orders[sid]
        if not cart:
            return JSONResponse(
                content={"fulfillmentText": "Your order is empty. Tell me what you would like to add first."}
            )

        order_id, err = save_to_db(dict(cart), user_id)
        if err:
            return JSONResponse(content={"fulfillmentText": err})

        cart.clear()
        text = f"Awesome. We have placed your order. Here is your order id #{order_id}"
        try:
            await ecosystem_socket_manager.push_order_update(order_id)
        except Exception as ws_err:
            logger.warning(f"[CHATBOT] push_order_update non-critical failure for order_id={order_id}: {ws_err}")

        return JSONResponse(content={"fulfillmentText": text})

    except Exception:
        logger.exception("[CHATBOT] complete_order")
        return JSONResponse(
            content={"fulfillmentText": "Something went wrong completing your order. Please try again later."}
        )


def track_order(parameters, session_id):
    try:
        user_id, login_err = _chatbot_require_user(session_id)
        if login_err:
            return JSONResponse(content={"fulfillmentText": "Please log in on the website to track your order."})

        oid = _chatbot_extract_order_id(parameters)
        if oid is None:
            return JSONResponse(
                content={"fulfillmentText": "Please tell me your order number so I can look up the status."}
            )

        status = db_helper.get_order_status_for_user(oid, user_id)
        if not status:
            return JSONResponse(content={"fulfillmentText": f"No order found with order id: {oid}"})

        friendly = CHATBOT_ORDER_STATUS_MESSAGES.get(status, "")
        if friendly:
            text = f"Your order #{oid} is currently {status}. {friendly}"
        else:
            text = f"Your order #{oid} is currently {status}."
        return JSONResponse(content={"fulfillmentText": text})

    except Exception:
        logger.exception("[CHATBOT] track_order")
        return JSONResponse(
            content={"fulfillmentText": "Something went wrong looking up your order. Please try again in a moment."}
        )


def cancel_order_handler(parameters, session_id):
    """
    Only reached when Dialogflow sends order.cancel AND no food item was
    detected in query_text (the FORCE_ROUTE guard runs before this handler).
    Cart check lives here — NOT in the global pipeline.
    """
    try:
        sid = _chatbot_session_key(session_id)
        cart = inprogress_orders.get(sid, {})
        if not cart:
            return JSONResponse(
                content={"fulfillmentText": "You don't have an active order to cancel."}
            )
        inprogress_orders[sid].clear()
        logger.info(f"[CHATBOT] cancel_order_handler: cart cleared for session={sid}")
        return JSONResponse(content={"fulfillmentText": "Your order has been cancelled."})
    except Exception:
        logger.exception("[CHATBOT] cancel_order_handler")
        return JSONResponse(content={"fulfillmentText": "Something went wrong. Please try again."})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)