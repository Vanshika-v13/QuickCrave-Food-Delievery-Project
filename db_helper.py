import logging
import json
import traceback
import mysql.connector
import os
from datetime import datetime
from dotenv import load_dotenv
from order_states import ACTIVE_STATES, HISTORY_STATES

load_dotenv()

logger = logging.getLogger(__name__)

# 1. Define and initialize the database connection variable `cnx` correctly
# 2. Ensure `cnx` is created before it is used anywhere in the file
# 3. Add required import for database connection (mysql.connector)
cnx = mysql.connector.connect(
    host=os.getenv("DB_HOST", "localhost"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", "vanshiv1303"),
    database=os.getenv("DB_NAME", "pandeyji_eatery")
)

import redis

TOTAL_DELIVERY_MINUTES = 45
FALLBACK_ETA = {
    "remaining_minutes": TOTAL_DELIVERY_MINUTES,
    "remaining_seconds": TOTAL_DELIVERY_MINUTES * 60,
    "eta_text": f"{TOTAL_DELIVERY_MINUTES} min left",
}


def _canonical_eta_status(raw_status):
    """Normalize order.status string for ETA lookup (no datetime logic)."""
    if not raw_status:
        return "ORDER_PLACED"
    s = str(raw_status).strip().upper().replace(" ", "_")
    if s in ("PLACED",):
        return "ORDER_PLACED"
    if s in ("CONFIRMED",):
        return "RESTAURANT_CONFIRMED"
    if s in ("PARTNER_ASSIGNED", "DELIVERY_PARTNER_ASSIGNED", "RIDER_ASSIGNED"):
        return "ASSIGNED"
    if s in ("PICKED", "PICKED_UP",):
        return "ORDER_PICKED_UP"
    if s in ("ON_THE_WAY",):
        return "OUT_FOR_DELIVERY"
    if s in ("NEAR_YOUR_LOCATION",):
        return "NEAR_CUSTOMER_LOCATION"
    return s


# Fixed ETA per lifecycle stage — updates only when backend status changes.
ETA_BY_STATUS_MINUTES = {
    "ORDER_PLACED": 45,
    "RESTAURANT_CONFIRMED": 35,
    "PREPARING_FOOD": 30,
    "FOOD_READY": 25,
    "ASSIGNED": 20,
    "ACCEPTED": 15,
    "ORDER_PICKED_UP": 10,
    "OUT_FOR_DELIVERY": 5,
    "NEAR_CUSTOMER_LOCATION": 5,
}


def calculate_remaining_delivery_time(order):
    """
    Status-only ETA: fixed remaining time per orders.status.
    No elapsed-time or created_at math.
    """
    try:
        status_key = _canonical_eta_status(
            (order or {}).get("status") if isinstance(order, dict) else None
        )
        if status_key in ("DELIVERED", "DELIVERED_SUCCESS"):
            return {
                "remaining_minutes": 0,
                "remaining_seconds": 0,
                "eta_text": "Delivered",
            }
        if status_key == "CANCELLED":
            return {
                "remaining_minutes": 0,
                "remaining_seconds": 0,
                "eta_text": "Cancelled",
            }
        minutes = ETA_BY_STATUS_MINUTES.get(status_key, ETA_BY_STATUS_MINUTES["ORDER_PLACED"])
        sec = minutes * 60
        return {
            "remaining_minutes": minutes,
            "remaining_seconds": sec,
            "eta_text": f"{minutes} min left",
        }
    except Exception as e:
        logger.warning(f"[ETA] calculate_remaining_delivery_time fallback used: {e}")
        return dict(FALLBACK_ETA)

# --- Redis Integration (Hardened Startup) ---
redis_client = None
try:
    # Use a short timeout to prevent blocking startup
    redis_client = redis.Redis(
        host='localhost', port=6379, db=0, 
        decode_responses=True, socket_timeout=0.3, socket_connect_timeout=0.3
    )
    redis_client.ping()
    logger.info("[DB_HELPER] Redis connected.")
except Exception as e:
    logger.warning(f"[DB_HELPER] Redis initialization failed (Degraded Mode): {e}")
    redis_client = None


def get_db_connection():
    global cnx
    if not cnx.is_connected():
        cnx.reconnect(attempts=3, delay=2)
    return cnx

def check_column_exists(table, column):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SHOW COLUMNS FROM {table} LIKE %s", (column,))
        results = cursor.fetchall() # Consume ALL results to prevent "Unread result found"
        cursor.close()
        return len(results) > 0
    except Exception as e:
        logger.error(f"Error checking column {column} in {table}: {e}")
        return False

def check_index_exists(table, index_name):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(f"SHOW INDEX FROM {table} WHERE Key_name = %s", (index_name,))
        results = cursor.fetchall() # Consume ALL results to prevent "Unread result found"
        cursor.close()
        return len(results) > 0
    except Exception as e:
        logger.error(f"Error checking index {index_name} in {table}: {e}")
        return False

def init_db():
    conn = get_db_connection()
    # Use buffered=True to handle multiple queries without "Unread result found" errors
    cursor = conn.cursor(buffered=True)
    # Create users table with google_id and profile_pic
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) UNIQUE NOT NULL,
            password VARCHAR(255),
            google_id VARCHAR(255),
            profile_pic TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Migration for role (Rule: Default to 'customer')
    try:
        if not check_column_exists('users', 'role'):
            print("Migration: Adding 'role' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN role ENUM('customer','admin','rider') DEFAULT 'customer'")
        
        # New Migration: Adding 'roles' JSON column for multi-role support
        if not check_column_exists('users', 'roles'):
            print("Migration: Adding 'roles' JSON column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN roles JSON NULL")
            
            # Migrate existing data safely
            cursor.execute("UPDATE users SET roles = '[\"customer\"]' WHERE role = 'customer'")
            cursor.execute("UPDATE users SET roles = '[\"customer\", \"admin\"]' WHERE role = 'admin'")
            cursor.execute("UPDATE users SET roles = '[\"rider\"]' WHERE role = 'rider'")
            cursor.execute("UPDATE users SET roles = '[\"customer\"]' WHERE role IS NULL")

        # New Migration: Production-grade fields
        if not check_column_exists('users', 'is_active'):
            print("Migration: Adding 'is_active' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN is_active TINYINT DEFAULT 1")

        if not check_column_exists('users', 'phone'):
            print("Migration: Adding 'phone' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN phone VARCHAR(20) NULL")

        if not check_column_exists('users', 'profile_pic'):
            print("Migration: Adding 'profile_pic' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN profile_pic TEXT NULL")

        if not check_column_exists('users', 'vehicle_type'):
            print("Migration: Adding 'vehicle_type' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN vehicle_type VARCHAR(50) NULL")

        if not check_column_exists('users', 'license_number'):
            print("Migration: Adding 'license_number' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN license_number VARCHAR(50) NULL")

        if not check_column_exists('users', 'rider_status'):
            print("Migration: Adding 'rider_status' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN rider_status ENUM('available', 'busy', 'offline') DEFAULT 'offline'")

        if not check_column_exists('users', 'updated_at'):
            print("Migration: Adding 'updated_at' column to users table")
            cursor.execute("ALTER TABLE users ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP")

    except Exception as e:
        print(f"Migration error for users enhancement: {e}")

    # Ensure password is nullable (only if it exists and we need to modify it)
    # Actually, better to just check if we NEED to modify it to avoid unnecessary locks
    try:
        cursor.execute("SELECT IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'users' AND COLUMN_NAME = 'password' AND TABLE_SCHEMA = DATABASE()")
        result = cursor.fetchone()
        if result and result[0] == 'NO':
            print("Migration: Making 'password' column nullable")
            cursor.execute("ALTER TABLE users MODIFY COLUMN password VARCHAR(255) NULL")
    except Exception as e:
        print(f"Migration error for password nullability: {e}")

    # Create user_addresses table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_addresses (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT,
            name VARCHAR(255) NOT NULL,
            phone VARCHAR(20),
            address_line TEXT,
            city VARCHAR(100),
            state VARCHAR(100),
            pincode VARCHAR(20),
            is_default BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)
    
    # Migrations for user_addresses
    try:
        # Check if 'full_name' exists and copy to 'name' then drop
        cursor.execute("SHOW COLUMNS FROM user_addresses LIKE 'full_name'")
        if cursor.fetchone():
            cursor.execute("SHOW COLUMNS FROM user_addresses LIKE 'name'")
            if not cursor.fetchone():
                cursor.execute("ALTER TABLE user_addresses CHANGE COLUMN full_name name VARCHAR(255) NOT NULL")
            else:
                cursor.execute("UPDATE user_addresses SET name = full_name WHERE name IS NULL OR name = ''")
                cursor.execute("ALTER TABLE user_addresses DROP COLUMN full_name")

        cursor.execute("SHOW COLUMNS FROM user_addresses LIKE 'is_default'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE user_addresses ADD COLUMN is_default BOOLEAN DEFAULT FALSE")
            
        cursor.execute("SHOW COLUMNS FROM user_addresses LIKE 'address_line'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE user_addresses ADD COLUMN address_line TEXT")

        if not check_column_exists("user_addresses", "latitude"):
            print("Migration: Adding latitude/longitude to user_addresses")
            cursor.execute("ALTER TABLE user_addresses ADD COLUMN latitude DOUBLE NULL")
            cursor.execute("ALTER TABLE user_addresses ADD COLUMN longitude DOUBLE NULL")

        if not check_index_exists("user_addresses", "idx_user_addresses_one_default"):
            print("Migration: Enforcing one default address per user")
            cursor.execute(
                """
                CREATE UNIQUE INDEX idx_user_addresses_one_default
                ON user_addresses ((IF(is_default, user_id, NULL)))
                """
            )
    except Exception as e:
        print(f"Migration error for user_addresses: {e}")
    # Create cart table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cart (
            id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            item_id INT NOT NULL,
            quantity INT NOT NULL DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY (user_id, item_id),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (item_id) REFERENCES food_items(item_id)
        )
    """)

    # Create orders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id INT AUTO_INCREMENT PRIMARY KEY,
            user_id INT NOT NULL,
            address_id INT,
            subtotal DECIMAL(10, 2) DEFAULT 0,
            delivery_fee DECIMAL(10, 2) DEFAULT 40,
            total_amount DECIMAL(10, 2) DEFAULT 0,
            address TEXT,
            payment_method VARCHAR(50) DEFAULT 'COD',
            payment_status ENUM('PENDING', 'PAID', 'FAILED') DEFAULT 'PENDING',
            status VARCHAR(50) DEFAULT 'ORDER_PLACED',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            restaurant_lat DOUBLE,
            restaurant_lng DOUBLE,
            user_lat DOUBLE,
            user_lng DOUBLE,
            rider_id INT NULL,
            estimated_delivery_time DATETIME NULL,
            delivered_at DATETIME NULL,
            accepted_at DATETIME NULL,
            picked_up_at DATETIME NULL,
            assigned_at TIMESTAMP NULL,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (address_id) REFERENCES user_addresses(id),
            CONSTRAINT fk_orders_rider FOREIGN KEY (rider_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

    # Create order_items table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_items (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL,
            item_id INT NOT NULL,
            quantity INT NOT NULL,
            price DECIMAL(10, 2),
            total_price DECIMAL(10, 2),
            FOREIGN KEY (order_id) REFERENCES orders(order_id),
            FOREIGN KEY (item_id) REFERENCES food_items(item_id)
        )
    """)
    # Migration: add total_price column to order_items if missing
    # NOTE: image_url is intentionally NOT stored in order_items.
    # Images are MASTER DATA and must ALWAYS be resolved via food_items JOIN.
    try:
        cursor.execute("SHOW COLUMNS FROM order_items LIKE 'total_price'")
        if not cursor.fetchone():
            cursor.execute("ALTER TABLE order_items ADD COLUMN total_price DECIMAL(10,2)")
    except Exception as e:
        print(f"Migration error for order_items: {e}")

    # Create order_tracking table (if not exists)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS order_tracking (
            id INT AUTO_INCREMENT PRIMARY KEY,
            order_id INT NOT NULL,
            lat DOUBLE,
            lng DOUBLE,
            status VARCHAR(255),
            old_status VARCHAR(255) NULL,
            actor ENUM('SYSTEM', 'ADMIN', 'RIDER') DEFAULT 'SYSTEM',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id) REFERENCES orders(order_id)
        )
    """)

    # Create rider_locations table (Realtime GPS Cache)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rider_locations (
            rider_id INT PRIMARY KEY,
            lat DECIMAL(10,7),
            lng DECIMAL(10,7),
            heading FLOAT NULL,
            speed FLOAT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rider_id) REFERENCES users(id)
        )
    """)

    # Migrations for orders (Additional columns & constraints)
    try:
        cursor.execute("SHOW COLUMNS FROM orders LIKE 'rider_id'")
        if not cursor.fetchone():
            print("Migration: Adding delivery columns to orders table")
            cursor.execute("ALTER TABLE orders ADD COLUMN rider_id INT NULL")
            cursor.execute("ALTER TABLE orders ADD COLUMN estimated_delivery_time DATETIME NULL")
            cursor.execute("ALTER TABLE orders ADD COLUMN delivered_at DATETIME NULL")
            cursor.execute("ALTER TABLE orders ADD COLUMN accepted_at DATETIME NULL")
            cursor.execute("ALTER TABLE orders ADD COLUMN picked_up_at DATETIME NULL")
        
        # Add Foreign Key if missing
        cursor.execute("SELECT CONSTRAINT_NAME FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = DATABASE() AND CONSTRAINT_NAME = 'fk_orders_rider'")
        if not cursor.fetchone():
            print("Migration: Adding fk_orders_rider to orders table")
            cursor.execute("ALTER TABLE orders ADD CONSTRAINT fk_orders_rider FOREIGN KEY (rider_id) REFERENCES users(id) ON DELETE SET NULL")

        # Add performance indexes
        cursor.execute("SHOW INDEX FROM orders WHERE Key_name = 'idx_orders_rider_id'")
        if not cursor.fetchone():
            cursor.execute("CREATE INDEX idx_orders_rider_id ON orders(rider_id)")
        
        cursor.execute("SHOW INDEX FROM orders WHERE Key_name = 'idx_orders_status'")
        if not cursor.fetchone():
            cursor.execute("CREATE INDEX idx_orders_status ON orders(status)")

        # NEW MIGRATIONS
        if not check_column_exists('orders', 'payment_status'):
            print("Migration: Adding 'payment_status' column to orders table")
            cursor.execute("ALTER TABLE orders ADD COLUMN payment_status ENUM('PENDING','PAID','FAILED') DEFAULT 'PENDING'")
        
        if not check_column_exists('orders', 'payment_method'):
            print("Migration: Adding 'payment_method' column to orders table")
            cursor.execute("ALTER TABLE orders ADD COLUMN payment_method VARCHAR(50) DEFAULT 'COD'")

        if not check_index_exists('orders', 'idx_orders_created_at'):
            print("Migration: Adding index on created_at in orders table")
            cursor.execute("CREATE INDEX idx_orders_created_at ON orders(created_at)")
            
        if not check_index_exists('orders', 'idx_orders_payment_status'):
            print("Migration: Adding index on payment_status in orders table")
            cursor.execute("CREATE INDEX idx_orders_payment_status ON orders(payment_status)")
            
        if not check_column_exists('orders', 'version'):
            print("Migration: Adding 'version' to orders")
            cursor.execute("ALTER TABLE orders ADD COLUMN version INT DEFAULT 1")
    except Exception as e:
        print(f"Migration error for orders enhancement: {e}")

    # Migrations for performance indexes on other tables
    try:
        if not check_index_exists('users', 'idx_users_email'):
            cursor.execute("CREATE INDEX idx_users_email ON users(email)")

        if not check_index_exists('users', 'idx_users_role'):
            cursor.execute("CREATE INDEX idx_users_role ON users(role)")

        if not check_index_exists('users', 'idx_users_rider_selection'):
            print("Migration: Adding composite index for rider selection")
            cursor.execute("CREATE INDEX idx_users_rider_selection ON users(role, rider_status, is_active)")

        if not check_index_exists('order_tracking', 'idx_tracking_order_id'):
            cursor.execute("CREATE INDEX idx_tracking_order_id ON order_tracking(order_id)")
            
        if not check_index_exists('order_tracking', 'idx_tracking_updated_at'):
            cursor.execute("CREATE INDEX idx_tracking_updated_at ON order_tracking(created_at)")
            
        if not check_index_exists('rider_locations', 'idx_rider_loc_updated_at'):
            cursor.execute("CREATE INDEX idx_rider_loc_updated_at ON rider_locations(updated_at)")

        if not check_index_exists('rider_locations', 'idx_rider_locations_rider_id'):
            cursor.execute("CREATE INDEX idx_rider_locations_rider_id ON rider_locations(rider_id)")
            
        # Migrations for order_tracking enhancement
        if not check_column_exists('order_tracking', 'old_status'):
            print("Migration: Adding 'old_status' to order_tracking")
            cursor.execute("ALTER TABLE order_tracking ADD COLUMN old_status VARCHAR(255) NULL")
            
        if not check_column_exists('orders', 'assigned_at'):
            print("Migration: Adding 'assigned_at' to orders")
            cursor.execute("ALTER TABLE orders ADD COLUMN assigned_at TIMESTAMP NULL")

        if not check_column_exists('order_tracking', 'actor'):
            print("Migration: Adding 'actor' to order_tracking")
            cursor.execute("ALTER TABLE order_tracking ADD COLUMN actor ENUM('SYSTEM', 'ADMIN', 'RIDER') DEFAULT 'SYSTEM'")

        # Create admin_audit_log table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                admin_id INT,
                action VARCHAR(255),
                order_id INT NULL,
                details TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (admin_id) REFERENCES users(id)
            )
        """)
    except Exception as e:
        print(f"Migration error for performance indexes: {e}")

    # Migrations for order_tracking
    try:
        cursor.execute("SHOW COLUMNS FROM order_tracking LIKE 'lat'")
        cols = cursor.fetchall()
        if not cols:
            cursor.execute("ALTER TABLE order_tracking ADD COLUMN lat DOUBLE")
            cursor.execute("ALTER TABLE order_tracking ADD COLUMN lng DOUBLE")
    except Exception as e:
        print(f"Migration error for order_tracking: {e}")

    cnx.commit()
    cursor.close()

# Call init_db on import to ensure tables exist
init_db()

# Function to insert a record into the order_tracking table
def insert_order_tracking(order_id, status, actor="SYSTEM", lat=None, lng=None, expected_previous_status=None):
    """
    STRICT BUSINESS RULE: Atomic Status Transition.
    Updates 'orders' table AND 'order_tracking' history in a single transaction.
    """
    # 1. Automation Block (Mandatory Requirement)


    # 1.5 Coordinate Validation (Hardening)
    if lat is not None and lng is not None:
        try:
            lat_f, lng_f = float(lat), float(lng)
            if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
                logger.warning(f"[SECURITY][ORDER:{order_id}] Invalid coordinates rejected: {lat}, {lng}")
                lat, lng = None, None
        except (ValueError, TypeError):
            lat, lng = None, None

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    try:
        # 2. Verify current status for transition validation (Optimistic Locking)
        cursor.execute("SELECT status FROM orders WHERE order_id = %s FOR UPDATE", (order_id,))
        row = cursor.fetchone()
        if not row:
            cursor.close()
            return False
            
        old_status = row['status']
        
        # 3. Duplicate Status Protection
        if old_status == status:
            logger.info(f"[SKIP][ORDER:{order_id}] Status already {status}")
            cursor.close()
            return True

        # 4. Atomic Update
        # Update orders table first (Single Source of Truth)
        query_order = "UPDATE orders SET status = %s, version = version + 1 WHERE order_id = %s"
        cursor.execute(query_order, (status, order_id))
        
        # Log to tracking history
        query_tracking = """
            INSERT INTO order_tracking (order_id, status, old_status, actor, lat, lng)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        cursor.execute(query_tracking, (order_id, status, old_status, actor, lat, lng))
        
        # 5. Payment Logic: If COD and DELIVERED, set payment_status = PAID
        if status.upper() == 'DELIVERED':
            cursor.execute("""
                UPDATE orders 
                SET payment_status = 'PAID', delivered_at = CURRENT_TIMESTAMP
                WHERE order_id = %s AND payment_method = 'COD'
            """, (order_id,))
            
            cursor.execute("""
                UPDATE orders 
                SET delivered_at = CURRENT_TIMESTAMP 
                WHERE order_id = %s AND delivered_at IS NULL
            """, (order_id,))

        # 6. Rider Release Logic: If DELIVERED, DELIVERED_SUCCESS or CANCELLED, set rider_status = 'available'
        if status.upper() in ['DELIVERED', 'CANCELLED', 'DELIVERED_SUCCESS']:
            cursor.execute("SELECT rider_id FROM orders WHERE order_id = %s", (order_id,))
            order_info = cursor.fetchone()
            if order_info and order_info['rider_id']:
                cursor.execute("UPDATE users SET rider_status = 'available' WHERE id = %s", (order_info['rider_id'],))
                if redis_client:
                    redis_client.delete(f"rider_last_known:{order_info['rider_id']}")
                    redis_client.delete(f"rider_throttle:{order_info['rider_id']}")
                logger.info(f"[RESET][RIDER:{order_info['rider_id']}] Released due to {status}")

        conn.commit()
        cursor.close()
        logger.info(f"[STATUS][ORDER:{order_id}] {old_status} -> {status} by {actor}")
        return True
    except Exception as e:
        conn.rollback()
        if cursor: cursor.close()
        logger.error(f"[ERROR][ORDER:{order_id}] insert_order_tracking: {e}")
        return False




def get_latest_tracking(order_id):
    """Fetches the most recent tracking entry for an order."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT lat, lng, status
            FROM order_tracking
            WHERE order_id = %s
            ORDER BY created_at DESC
            LIMIT 1
        """
        cursor.execute(query, (order_id,))
        result = cursor.fetchone()
        cursor.close()
        return result
    except Exception as e:
        print(f"Error in get_latest_tracking: {e}")
        return None

def validate_order_owner(order_id: int, user_id: int) -> str:
    """
    SECURITY: Strict order ownership check.
    Returns:
        "ALLOWED"         — order exists and belongs to user_id
        "ORDER_NOT_FOUND" — no order with that order_id
        "ACCESS_DENIED"   — order exists but belongs to a different user
    Rule: orders.user_id MUST equal user_id. No exceptions for customer role.
    Admins should bypass this check at the API layer, not here.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT user_id FROM orders WHERE order_id = %s", (order_id,))
        result = cursor.fetchone()
        cursor.close()

        if not result:
            return "ORDER_NOT_FOUND"

        if result["user_id"] != user_id:
            logger.warning(
                f"[SECURITY] Order ownership denied: order_id={order_id} "
                f"owned_by={result['user_id']} requested_by={user_id}"
            )
            return "ACCESS_DENIED"

        return "ALLOWED"
    except Exception as e:
        logger.error(f"[SECURITY] validate_order_owner error: {e}")
        return "ORDER_NOT_FOUND"


def _normalize_status_strict(status):
    """Match main.normalize_status_internal for delete eligibility (no circular import)."""
    if not status:
        return "ORDER_PLACED"
    s = str(status).upper().replace(" ", "_")
    if s in ["PLACED", "ORDER_PLACED"]:
        return "ORDER_PLACED"
    if s in ["CONFIRMED", "RESTAURANT_CONFIRMED"]:
        return "RESTAURANT_CONFIRMED"
    if s in ["PREPARING", "PREPARING_FOOD"]:
        return "PREPARING_FOOD"
    if s in ["FOOD_READY", "READY"]:
        return "FOOD_READY"
    if s in ["RIDER_ASSIGNED", "PARTNER_ASSIGNED", "ASSIGNED"]:
        return "ASSIGNED"
    if s in ["ACCEPTED"]:
        return "ACCEPTED"
    if s in ["PICKED", "ORDER_PICKED_UP", "PICKED_UP"]:
        return "ORDER_PICKED_UP"
    if s in ["ON_THE_WAY", "OUT_FOR_DELIVERY"]:
        return "OUT_FOR_DELIVERY"
    if s in ["NEAR_YOUR_LOCATION", "NEAR_CUSTOMER_LOCATION"]:
        return "NEAR_CUSTOMER_LOCATION"
    if s in ["DELIVERED", "DELIVERED_SUCCESS"]:
        return "DELIVERED"
    if s == "CANCELLED":
        return "CANCELLED"
    return s


def delete_customer_order_placed(order_id: int, user_id: int) -> str:
    """
    Hard-delete a fresh customer order: only when status normalizes to ORDER_PLACED and no rider.
    Uses a dedicated connection (autocommit=False) — never start_transaction() on the shared pool.

    Atomic order: verify row → DELETE children → DELETE orders. Single commit.
    Returns: DELETED | NOT_FOUND | FORBIDDEN | NOT_DELETABLE
    """
    conn = None
    cursor = None
    try:
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT user_id, status, rider_id FROM orders WHERE order_id = %s FOR UPDATE",
            (order_id,),
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return "NOT_FOUND"
        if row["user_id"] != user_id:
            conn.rollback()
            logger.warning(
                f"[ORDER_DELETE] Forbidden attempt order_id={order_id} requested_by={user_id}"
            )
            return "FORBIDDEN"
        if _normalize_status_strict(row["status"]) != "ORDER_PLACED":
            conn.rollback()
            logger.info(
                f"[ORDER_DELETE] Rejected order_id={order_id} status={row['status']}"
            )
            return "NOT_DELETABLE"
        if row.get("rider_id") is not None:
            conn.rollback()
            logger.info(f"[ORDER_DELETE] Rejected order_id={order_id} rider_id already set")
            return "NOT_DELETABLE"

        cursor.execute("DELETE FROM order_items WHERE order_id = %s", (order_id,))
        cursor.execute("DELETE FROM order_tracking WHERE order_id = %s", (order_id,))
        cursor.execute("DELETE FROM admin_audit_log WHERE order_id = %s", (order_id,))
        cursor.execute("DELETE FROM orders WHERE order_id = %s", (order_id,))
        conn.commit()
        logger.info(f"[ORDER_DELETE] Hard deleted order_id={order_id} user_id={user_id}")
        return "DELETED"
    except Exception as e:
        if conn:
            try:
                conn.rollback()
            except Exception:
                pass
        logger.error(f"[ORDER_DELETE] Transaction failed order_id={order_id}: {e}")
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def verify_address_ownership(user_id, address_id):
    try:
        cursor = cnx.cursor()
        cursor.execute("SELECT id FROM user_addresses WHERE id = %s AND user_id = %s", (address_id, user_id))
        result = cursor.fetchone()
        cursor.close()
        return result is not None
    except mysql.connector.Error as err:
        print(f"Error verifying address: {err}")
        return False

def place_order_in_db(user_id, address_id, items=None, payment_method='COD', restaurant_lat=None, restaurant_lng=None, clear_cart=True):
    print("==== ORDER DEBUG START ====")
    print("USER:", user_id)
    print("ADDRESS_ID:", address_id)
    
    print(f"[DEBUG] Starting order placement for user {user_id}")
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch Cart Items
        if items is not None:
            print(f"[DEBUG] Processing {len(items)} items from payload for user {user_id}")
            # Even if items are provided, we MUST fetch prices from DB for integrity
            item_ids = [it.get('item_id') or it.get('id') for it in items if (it.get('item_id') or it.get('id'))]
            
            if not item_ids:
                print(f"[DEBUG] No valid item IDs found in payload items: {items}")
                processed_items = []
            else:
                format_strings = ','.join(['%s'] * len(item_ids))
                query_prices = f"SELECT item_id, price FROM food_items WHERE item_id IN ({format_strings})"
                cursor.execute(query_prices, tuple(item_ids))
                db_items = {it['item_id']: it['price'] for it in cursor.fetchall()}
                
                # Reconstruct items with DB prices
                processed_items = []
                for it in items:
                    iid = it.get('item_id') or it.get('id')
                    if iid in db_items:
                        processed_items.append({
                            'item_id': iid,
                            'quantity': it.get('quantity', 1),
                            'price': db_items[iid]
                        })
                    else:
                        print(f"[DEBUG] Item ID {iid} not found in food_items table")
            
            items = processed_items
            print(f"[DEBUG] Successfully processed {len(items)} items from payload")
        else:
            print(f"[DEBUG] Items not in payload, fetching from DB cart for user {user_id}")
            query_cart = """
                SELECT c.item_id, c.quantity, f.price
                FROM cart c 
                JOIN food_items f ON c.item_id = f.item_id 
                WHERE c.user_id = %s
            """
            cursor.execute(query_cart, (user_id,))
            items = cursor.fetchall()
            print(f"[DEBUG] Cart items found in DB: {len(items)}")
        
        if not items:
            print(f"[DEBUG] Order placement failed: Cart is empty for user {user_id}")
            raise Exception("Cannot place order: Cart is empty. Please add items to your cart.")
            
        # 2. Pricing Logic
        subtotal = 0
        for item in items:
            qty = max(1, item['quantity'])
            price = float(item['price'])
            subtotal += qty * price
        
        subtotal = round(subtotal, 2)
        delivery_fee = 40.00
        total_amount = subtotal + delivery_fee
        print(f"[DEBUG] Calculated total: {total_amount}")
        
        # 3. Fetch Address Details
        cursor.execute("SELECT * FROM user_addresses WHERE id = %s AND user_id = %s", (address_id, user_id))
        addr_row = cursor.fetchone()
        if not addr_row:
            print(f"[DEBUG] Address {address_id} not found for user {user_id}")
            raise Exception(f"Address with ID {address_id} not found for user {user_id}")
            
        address_string = f"{addr_row['name']}, {addr_row['address_line']}, {addr_row['city']}, {addr_row['state']} - {addr_row['pincode']}"
        print(f"[DEBUG] Resolved address: {address_string[:30]}...")

        snap_lat = addr_row.get("latitude")
        snap_lng = addr_row.get("longitude")

        user_lat_snap = None
        user_lng_snap = None
        if snap_lat is not None and snap_lng is not None:
            try:
                user_lat_snap = float(snap_lat)
                user_lng_snap = float(snap_lng)
            except (TypeError, ValueError):
                raise Exception(
                    "DELIVERY_COORDS_INVALID: Saved address coordinates are not valid numbers."
                )
            if not (-90.0 <= user_lat_snap <= 90.0 and -180.0 <= user_lng_snap <= 180.0):
                raise Exception(
                    "DELIVERY_COORDS_INVALID: Saved address coordinates are out of valid range."
                )
        
        # 4. Insert into orders table
        # Rule: ONLINE is PAID immediately, COD is PENDING
        initial_payment_status = 'PAID' if payment_method.upper() == 'ONLINE' else 'PENDING'
        
        query_order = """
            INSERT INTO orders (
                user_id, address_id, address, subtotal, delivery_fee, total_amount, 
                payment_method, status, payment_status, restaurant_lat, restaurant_lng, user_lat, user_lng
            ) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'ORDER_PLACED', %s, %s, %s, %s, %s)
        """
        print("[DEBUG] Executing main order insert...")
        cursor.execute(query_order, (
            user_id, address_id, address_string, subtotal, delivery_fee, total_amount, 
            payment_method, initial_payment_status, restaurant_lat, restaurant_lng, user_lat_snap, user_lng_snap
        ))
        
        order_id = cursor.lastrowid
        print(f"[DEBUG] Created order ID: {order_id}")
        
        # 5. Insert into order_items
        query_items = """
            INSERT INTO order_items (order_id, item_id, quantity, price, total_price)
            VALUES (%s, %s, %s, %s, %s)
        """
        for item in items:
            unit_price = float(item['price'])
            qty = max(1, item['quantity'])
            line_total = round(unit_price * qty, 2)
            print(f"[DEBUG] Inserting order item: {item['item_id']} (qty {qty})")
            cursor.execute(query_items, (order_id, item['item_id'], qty, unit_price, line_total))
            
        # 6. Clear Cart (optional — chatbot in-memory carts skip this)
        if clear_cart:
            cursor.execute("DELETE FROM cart WHERE user_id = %s", (user_id,))
        
        print("[DEBUG] Committing transaction...")
        cnx.commit()
        cursor.close()
        return order_id
        
    except Exception as e:
        print("ORDER DB ERROR:", str(e))
        traceback.print_exc()
        cnx.rollback()
        raise e

# --- Rider Tracking Functions ---

def upsert_rider_location(rider_id, lat, lng, heading=0, speed=0):
    """
    STRICT RULE: Updates ONLY the latest live location for a rider.
    No historical GPS data is stored here. Uses UPSERT to prevent duplicates.
    Includes coordinate validation.
    """
    try:
        # GPS Validation (Hardening)
        if lat is not None and lng is not None:
            lat_f, lng_f = float(lat), float(lng)
            if not (-90 <= lat_f <= 90 and -180 <= lng_f <= 180):
                print(f"[SECURITY] Invalid rider GPS rejected: {lat}, {lng}")
                return False

        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO rider_locations (rider_id, lat, lng, heading, speed, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
            lat = VALUES(lat),
            lng = VALUES(lng),
            heading = VALUES(heading),
            speed = VALUES(speed),
            updated_at = CURRENT_TIMESTAMP
        """
        cursor.execute(query, (rider_id, lat, lng, heading, speed))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"Error in upsert_rider_location: {e}")
        return False

def get_active_rider_location_for_order(order_id):
    """
    Logic:
    1. Fetch order.rider_id
    2. Query rider_locations for that rider
    Hardened Fallback: If no live location, query order_tracking for the last recorded GPS.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch order rider_id
        cursor.execute("SELECT rider_id FROM orders WHERE order_id = %s", (order_id,))
        row = cursor.fetchone()
        if not row or not row['rider_id']:
            return {"status": "No rider assigned", "location": None}
        
        active_rider_id = row['rider_id']

        # 2. Query rider_locations (latest row only)
        cursor.execute("""
            SELECT rider_id, lat, lng, heading, speed, updated_at
            FROM rider_locations
            WHERE rider_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
        """, (active_rider_id,))
        loc_row = cursor.fetchone()
        
        if loc_row and loc_row['lat'] is not None:
            cursor.close()
            return {
                "activeRider": {
                    "riderId": active_rider_id,
                    "lat": float(loc_row['lat']),
                    "lng": float(loc_row['lng']),
                    "heading": loc_row['heading'],
                    "speed": loc_row['speed']
                },
                "status": "Online"
            }
        
        # 3. Fallback: Query order_tracking for last known GPS (Rule 6)
        cursor.execute("""
            SELECT lat, lng, created_at 
            FROM order_tracking 
            WHERE order_id = %s AND lat IS NOT NULL 
            ORDER BY created_at DESC LIMIT 1
        """, (order_id,))
        track_row = cursor.fetchone()
        cursor.close()
        
        if track_row:
            return {
                "activeRider": {
                    "riderId": active_rider_id,
                    "lat": float(track_row['lat']),
                    "lng": float(track_row['lng']),
                    "heading": 0,
                    "speed": 0
                },
                "status": "Last Known (Offline)",
                "last_seen": track_row['created_at'].isoformat() if hasattr(track_row['created_at'], 'isoformat') else str(track_row['created_at'])
            }
        
        return {"status": "Rider offline", "location": None}
    except Exception as e:
        print(f"Error in get_active_rider_location_for_order: {e}")
        return {"status": "Error", "location": None}

def get_active_orders_for_rider(rider_id):
    """Fetches all active order IDs for a specific rider."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT order_id FROM orders 
            WHERE rider_id = %s 
            AND status NOT IN ('DELIVERED', 'CANCELLED')
        """
        cursor.execute(query, (rider_id,))
        result = cursor.fetchall()
        cursor.close()
        return [r['order_id'] for r in result]
    except Exception as e:
        print(f"Error in get_active_orders_for_rider: {e}")
        return []

def _get_fresh_db_connection():
    """
    Returns a DEDICATED, fresh MySQL connection with autocommit=False.
    Used exclusively for assignment transactions to avoid sharing the global
    `cnx` connection which may already have an active transaction.
    """
    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "vanshiv1303"),
        database=os.getenv("DB_NAME", "pandeyji_eatery"),
        autocommit=False
    )

def assign_rider_to_order(order_id, rider_id, actor='ADMIN', admin_id=None):
    """
    STRICT ATOMIC ASSIGNMENT (Race Condition Safe).
    Requirement: UPDATE orders SET rider_id = %s, status = 'ASSIGNED', assigned_at = CURRENT_TIMESTAMP 
    WHERE order_id = %s AND rider_id IS NULL.
    """
    conn = None
    cursor = None
    try:
        logger.info(f"[ORDER_ASSIGN][START] order_id={order_id} rider_id={rider_id} actor={actor}")
        
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Safety Check: Is rider already busy?
        cursor.execute("SELECT rider_status FROM users WHERE id = %s FOR UPDATE", (rider_id,))
        rider = cursor.fetchone()
        if rider and rider['rider_status'] == 'busy':
            logger.warning(f"[ORDER_ASSIGN][FAIL] Rider {rider_id} is already BUSY")
            conn.rollback()
            return "rider_busy"

        # 2. Performance Atomic Update
        # Rule: Only assign if rider_id is NULL. This is the ultimate race-condition guard.
        logger.info(f"[ORDER_ASSIGN][DB_UPDATE] Executing for order_id={order_id}")
        
        # Capture status before for logging
        cursor.execute("SELECT status FROM orders WHERE order_id = %s", (order_id,))
        status_row = cursor.fetchone()
        status_before = status_row['status'] if status_row else "UNKNOWN"
        logger.info(f"[ORDER_ASSIGN][STATUS_BEFORE] {status_before}")

        query = """
            UPDATE orders 
            SET rider_id = %s, status = 'ASSIGNED', assigned_at = CURRENT_TIMESTAMP, version = version + 1
            WHERE order_id = %s AND rider_id IS NULL
        """
        cursor.execute(query, (rider_id, order_id))
        
        if cursor.rowcount == 0:
            logger.warning(f"[ORDER_ASSIGN][FAIL] order_id={order_id} already assigned or doesn't exist")
            conn.rollback()
            return "already_assigned"

        logger.info(f"[ORDER_ASSIGN][STATUS_AFTER] ASSIGNED")

        # 3. Audit Log
        cursor.execute("""
            INSERT INTO order_tracking (order_id, status, old_status, actor)
            VALUES (%s, 'ASSIGNED', %s, %s)
        """, (order_id, status_before, actor))

        # 4. Post-assignment: Update Rider Status to busy
        cursor.execute("UPDATE users SET rider_status = 'busy' WHERE id = %s", (rider_id,))

        # 5. Admin Audit Log (Detailed)
        if admin_id:
            details = f"Rider {rider_id} assigned via {actor} assignment"
            cursor.execute("""
                INSERT INTO admin_audit_log (admin_id, action, order_id, details)
                VALUES (%s, 'RIDER_ASSIGNED', %s, %s)
            """, (admin_id, order_id, details))

        conn.commit()
        logger.info(f"[ORDER_ASSIGN][COMMIT] Successful")
        return "assigned"

    except Exception as e:
        logger.error(f"[ORDER_ASSIGN][ERROR] {e}")
        if conn: conn.rollback()
        return "error"
    finally:
        if cursor: cursor.close()
        if conn: conn.close()

def transaction_safe_accept_order(order_id, rider_id):
    """
    Production-grade: Uses MySQL transaction to prevent two riders accepting the same order.
    Standardized to use 'PARTNER_ASSIGNED' and update rider_status.
    """
    conn = None
    cursor = None
    try:
        conn = _get_fresh_db_connection()
        logger.info("[ORDER_ACCEPT][TRANSACTION_START]")
        cursor = conn.cursor(dictionary=True)

        # Select for update to lock the row
        cursor.execute("SELECT rider_id, status FROM orders WHERE order_id = %s FOR UPDATE", (order_id,))
        row = cursor.fetchone()

        if not row:
            conn.rollback()
            return "INVALID_ORDER"

        if row['rider_id'] is not None:
            conn.rollback()
            return "ALREADY_ASSIGNED"

        # Perform assignment (single canonical status)
        cursor.execute(
            "UPDATE orders SET rider_id = %s, status = 'ASSIGNED', version = version + 1 WHERE order_id = %s",
            (rider_id, order_id)
        )

        # Update rider status
        cursor.execute("UPDATE users SET rider_status = 'busy' WHERE id = %s", (rider_id,))

        # Insert tracking
        cursor.execute(
            "INSERT INTO order_tracking (order_id, status, old_status, actor) VALUES (%s, 'ASSIGNED', %s, 'RIDER')",
            (order_id, row['status'])
        )

        conn.commit()
        logger.info("[ORDER_ACCEPT][TRANSACTION_COMMIT]")
        return "SUCCESS"
    except Exception as e:
        logger.error(f"[ORDER_ACCEPT][TRANSACTION_ROLLBACK] Error: {e}")
        if conn: conn.rollback()
        return "ERROR"
    finally:
        if cursor: cursor.close()
        if conn: conn.close()
def get_total_order_price(order_id):
    cursor = cnx.cursor()
    query = "SELECT SUM(price * quantity) FROM order_items WHERE order_id = %s"
    cursor.execute(query, (order_id,))
    result = cursor.fetchone()[0]
    cursor.close()
    return float(result) if result else 0.0

def resolve_order_status(order_id):
    """
    STRICT SYSTEM RULE: Centralized Status Resolver.
    Source of Truth: orders.status column.
    Provides: current_status, status_history, and status-based ETA metadata.
    """
    try:
        # FORCE FRESH FETCH (FIX 1)
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Fetch current order info - THE SOURCE OF TRUTH
        cursor.execute("SELECT status, created_at, payment_status, version FROM orders WHERE order_id = %s", (order_id,))
        order_row = cursor.fetchone()
        if not order_row:
            cursor.close()
            return None
            
        current_status = order_row["status"]
        order_created_at = order_row["created_at"]
        payment_status = order_row["payment_status"]
        version = order_row.get("version", 1)

        # 2. Fetch all tracking entries for history
        query = """
            SELECT status, created_at, lat, lng 
            FROM order_tracking 
            WHERE order_id = %s 
            ORDER BY created_at ASC
        """
        cursor.execute(query, (order_id,))
        history = cursor.fetchall()
        cursor.close()

        try:
            eta_data = calculate_remaining_delivery_time({"status": current_status})
        except Exception as eta_exc:
            logger.warning(f"[ETA] resolve_order_status fallback used for order {order_id}: {eta_exc}")
            eta_data = dict(FALLBACK_ETA)
        
        # Latest tracking entry for coordinates
        latest_tracking = history[-1] if history else {"lat": None, "lng": None, "created_at": order_created_at}

        # Normalize history for response
        normalized_history = [
            {
                "status": h['status'],
                "timestamp": h['created_at'].isoformat() if hasattr(h['created_at'], 'isoformat') else str(h['created_at'])
            }
            for h in history
        ]

        return {
            "current_status": current_status,
            "last_updated": latest_tracking['created_at'].isoformat() if hasattr(latest_tracking['created_at'], 'isoformat') else str(latest_tracking['created_at']),
            "order_created_at": order_created_at.isoformat() if hasattr(order_created_at, 'isoformat') else str(order_created_at),
            "estimated_total_minutes": TOTAL_DELIVERY_MINUTES,
            "remaining_minutes": eta_data["remaining_minutes"],
            "remaining_seconds": eta_data["remaining_seconds"],
            "eta_text": eta_data["eta_text"],
            "status_history": normalized_history,
            "payment_status": payment_status,
            "version": version,
            "lat": latest_tracking.get('lat'),
            "lng": latest_tracking.get('lng')
        }
    except Exception as e:
        logger.error(f"Error in resolve_order_status for order {order_id}: {e}")
        return None
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def get_order_status(order_id):
    """Legacy wrapper for backward compatibility. Use resolve_order_status for full data."""
    res = resolve_order_status(order_id)
    return res["current_status"] if res else None

def get_food_items():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = "SELECT item_id, name, price, description, image_url, rating, tag FROM food_items"
    cursor.execute(query)
    result = cursor.fetchall()
    cursor.close()
    return result

def get_item_id_by_name(name):
    row = get_food_item_by_name(name)
    return row["item_id"] if row else None


def get_food_item_by_name(name):
    """Resolve a food_items row by name (exact match, then substring)."""
    raw = (name or "").strip()
    if not raw:
        return None
    try:
        cursor = cnx.cursor(dictionary=True)
        key = raw.lower()
        cursor.execute(
            "SELECT item_id, name, price FROM food_items WHERE LOWER(TRIM(name)) = %s LIMIT 1",
            (key,),
        )
        row = cursor.fetchone()
        if row:
            cursor.close()
            return row
        cursor.execute(
            """
            SELECT item_id, name, price FROM food_items
            WHERE LOWER(name) LIKE %s
            ORDER BY CHAR_LENGTH(name) ASC
            LIMIT 1
            """,
            (f"%{key}%",),
        )
        row = cursor.fetchone()
        cursor.close()
        return row
    except mysql.connector.Error as err:
        logger.error(f"[CHATBOT] get_food_item_by_name: {err}")
        return None


def get_chatbot_delivery_address(user_id):
    """Default address (is_default=1), otherwise first saved address for the user."""
    try:
        row = get_default_address(user_id)
        if row:
            return row
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM user_addresses WHERE user_id = %s ORDER BY id ASC LIMIT 1",
            (user_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        return row
    except mysql.connector.Error as err:
        logger.error(f"[CHATBOT] get_chatbot_delivery_address: {err}")
        return None


def get_order_status_for_user(order_id, user_id):
    """Return orders.status only when the order belongs to user_id."""
    try:
        oid = int(order_id)
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    try:
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT status FROM orders WHERE order_id = %s AND user_id = %s LIMIT 1",
            (oid, uid),
        )
        row = cursor.fetchone()
        cursor.close()
        return row["status"] if row else None
    except mysql.connector.Error as err:
        logger.error(f"[CHATBOT] get_order_status_for_user: {err}")
        return None

def get_tracking_history(order_id):
    cursor = cnx.cursor(dictionary=True)
    # Use IFNULL for created_at in case older rows lack it
    query = "SELECT status, created_at FROM order_tracking WHERE order_id = %s ORDER BY id ASC"
    cursor.execute(query, (order_id,))
    result = cursor.fetchall()
    cursor.close()
    return result

def cancel_order(order_id, user_id, admin_id=None):
    """
    Cancels order using insert_order_tracking to ensure consistency.
    Ensures rider release and audit logging.
    """
    actor = "ADMIN" if admin_id else "SYSTEM"
    success = insert_order_tracking(order_id, 'CANCELLED', actor=actor)
    
    if success is True and admin_id:
        log_admin_action(admin_id, "CANCEL_ORDER", order_id, f"Cancelled by admin for user_id: {user_id}")
        
    return success is True

def get_item_name_by_id(item_id):
    cursor = cnx.cursor()
    query = "SELECT name FROM food_items WHERE item_id = %s"
    cursor.execute(query, (item_id,))
    result = cursor.fetchone()
    cursor.close()
    if result:
        return result[0]
    return None

def validate_food_item_image(image_url, item_name="unknown"):
    """
    BACKEND VALIDATION RULE (Data Integrity Guard).
    Rejects NULL or empty image_url before any DB insert/update.
    Call this before inserting or updating a food_items row.
    Raises ValueError if image is invalid — never silently accepts bad data.
    """
    if not image_url or not image_url.strip():
        raise ValueError(
            f"[INTEGRITY ERROR] food_items.image_url cannot be NULL or empty "
            f"for item '{item_name}'. Every food item MUST have a unique image."
        )
    return image_url.strip()


def normalize_image_path(image_path):
    """Ensures all image paths follow the /images/filename pattern.
    
    STRICT RULE: image_path must already be a valid filename from food_items.
    A NULL/empty path here means data integrity has already failed upstream.
    This function normalizes the path prefix — it does NOT mask missing data.
    """
    if not image_path or not image_path.strip():
        # Log the integrity violation — do NOT silently serve a wrong image
        print("[INTEGRITY VIOLATION] normalize_image_path received NULL/empty image. "
              "Check food_items table — all rows must have image_url set.")
        return None  # Let frontend handle a missing image visibly, not silently wrong
    
    # 1. Handle full URLs (strip backend prefix)
    if image_path.startswith('http'):
        image_path = image_path.replace("http://localhost:8000", "")
        image_path = image_path.replace("http://127.0.0.1:8000", "")
    
    # 2. Cleanup redundant slashes and folders
    path = image_path.strip().lstrip('/')
    
    # 3. Ensure strictly /images/ prefix
    if path.startswith('images/'):
        return f"/{path}"
    
    return f"/images/{path}"

def _build_delivery_location(order_info, address_info=None):
    """
    Delivery destination for maps: coordinates from order snapshot (user_lat/user_lng at placement),
    plus address text from the linked user_addresses row.
    """
    lat = order_info.get("user_lat")
    lng = order_info.get("user_lng")
    if address_info:
        if lat is None and address_info.get("latitude") is not None:
            lat = address_info.get("latitude")
        if lng is None and address_info.get("longitude") is not None:
            lng = address_info.get("longitude")
    out = {
        "latitude": None,
        "longitude": None,
        "address_line": (address_info or {}).get("address_line"),
        "city": (address_info or {}).get("city"),
        "pincode": (address_info or {}).get("pincode"),
    }
    try:
        if lat is not None and lng is not None:
            out["latitude"] = float(lat)
            out["longitude"] = float(lng)
    except (TypeError, ValueError):
        pass
    return out


def _build_rider_location(rider_dict):
    """Flat lat/lng for API + websocket payloads; only when rider has live coordinates."""
    if not rider_dict:
        return None
    lat, lng = rider_dict.get("lat"), rider_dict.get("lng")
    if lat is None or lng is None:
        return None
    try:
        return {"latitude": float(lat), "longitude": float(lng)}
    except (TypeError, ValueError):
        return None


def normalize_order_data(order_info, items_rows, address_info=None, is_admin_view=False):
    """
    CENTRAL NORMALIZATION LAYER (Source of Truth).
    Enforces rules for Pricing, Status, and Images.
    """
    # 1. Resolve Status (Rule 2 & 8)
    status_obj = resolve_order_status(order_info['order_id'])
    if status_obj is None:
        status_obj = {"current_status": "UNKNOWN", "last_updated": None, "status_history": [], "lat": None, "lng": None}
    try:
        eta_data = calculate_remaining_delivery_time(order_info)
    except Exception as eta_exc:
        logger.warning(f"[ETA] normalize_order_data fallback used for order {order_info.get('order_id')}: {eta_exc}")
        eta_data = dict(FALLBACK_ETA)

    delivery_location = _build_delivery_location(order_info, address_info)
    rider_location = _build_rider_location(order_info.get("rider"))
    
    # 2. Process Items, Pricing, and Images (Rule 1, 5 & 6)
    items_normalized = []
    calculated_subtotal = 0
    
    for item in items_rows:
        # A. Item Level Pricing (Rule 3)
        unit_price = float(item.get('unit_price') or item.get('price') or 0)
        qty = int(item.get('quantity') or 0)
        line_total = round(unit_price * qty, 2)
        calculated_subtotal += line_total
        
        # B. Image Resolution — JOIN-BASED ONLY (food_items is SOLE source of truth)
        # STRICT RULE: image NEVER comes from order_items.
        # It is always fetched via food_id → food_items.image_url at response time.
        raw_image = item.get('food_image')  # Set exclusively by JOIN in get_order_summary()
        image_url = normalize_image_path(raw_image)
        
        items_normalized.append({
            "item_id": item.get('item_id'),
            "name": item.get('name', 'Unknown Item'),
            "quantity": qty,
            "unit_price": unit_price,
            "total_price": line_total,
            "image": image_url  # Always resolved from food_items, never stored in order_items
        })
    
    # 3. Pricing Authority (Rule 1 - Always recalculated on backend)
    delivery_fee = 40.0
    total_amount = calculated_subtotal + delivery_fee
    
    customer_name = (
        order_info.get("customer_name")
        or (address_info.get("name") if address_info else None)
        or "Unknown"
    )
    customer_phone = (
        order_info.get("customer_phone")
        or (address_info.get("phone") if address_info else None)
        or "Unknown"
    )

    # 4. Standardized Response (Rule 7)
    if is_admin_view:
        return {
            "order_id": order_info['order_id'],
            "status": status_obj,
            "customer": {
                "name": customer_name,
                "phone": customer_phone,
                "address": {
                    "address_line": address_info['address_line'] if address_info else "Unknown",
                    "city": address_info['city'] if address_info else "Unknown",
                    "pincode": address_info['pincode'] if address_info else "Unknown",
                },
            },
            "items": items_normalized,
            "rider": order_info.get('rider'),
            # Admin dashboard fields (no duplicated flat customer/address fields).
            "payment_method": order_info.get('payment_method', 'COD'),
            "total_amount": round(total_amount, 2),
            "created_at": (
                order_info['created_at'].isoformat()
                if hasattr(order_info.get('created_at'), 'isoformat')
                else str(order_info.get('created_at')) if order_info.get('created_at') else None
            ),
            "assigned_at": (
                order_info.get('assigned_at').isoformat()
                if hasattr(order_info.get('assigned_at'), 'isoformat')
                else str(order_info.get('assigned_at')) if order_info.get('assigned_at') else None
            ),
            "version": order_info.get('version', 1),
            "estimated_total_minutes": TOTAL_DELIVERY_MINUTES,
            "remaining_minutes": eta_data["remaining_minutes"],
            "remaining_seconds": eta_data["remaining_seconds"],
            "eta_text": eta_data["eta_text"],
            "delivery_location": delivery_location,
            "rider_location": rider_location,
        }

    return {
        "order_id": order_info['order_id'],
        "id": order_info['order_id'],
        "status": status_obj, # Full status object (Rule 2)
        "payment_method": order_info.get('payment_method', 'COD'),
        # Backward compatible fields used by existing dashboards/search.
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        # Canonical nested customer object (admin-friendly).
        "customer": {
            "name": customer_name,
            "phone": customer_phone,
            "address": {
                "address_line": address_info['address_line'] if address_info else "Unknown",
                "city": address_info['city'] if address_info else "Unknown",
                "pincode": address_info['pincode'] if address_info else "Unknown",
            },
        },
        "items": items_normalized,
        "pricing": {
            "subtotal": round(calculated_subtotal, 2),
            "delivery_fee": round(delivery_fee, 2),
            "total": round(total_amount, 2)
        },
        "total_amount": round(total_amount, 2),
        "address": {
            "name": address_info['name'] if address_info else "Unknown",
            "phone": address_info['phone'] if address_info else "Unknown",
            "address_line": address_info['address_line'] if address_info else "Unknown",
            "city": address_info['city'] if address_info else "Unknown",
            "pincode": address_info['pincode'] if address_info else "Unknown"
        },
        # Flat address fields for defensive frontend compatibility.
        "address_line": address_info['address_line'] if address_info else "Unknown",
        "city": address_info['city'] if address_info else "Unknown",
        "pincode": address_info['pincode'] if address_info else "Unknown",
        "delivery_location": delivery_location,
        "rider_location": rider_location,
        "locations": {
            "restaurant": {
                "lat": float(order_info.get('restaurant_lat')) if order_info.get('restaurant_lat') else None,
                "lng": float(order_info.get('restaurant_lng')) if order_info.get('restaurant_lng') else None
            },
            "user": {
                "lat": float(order_info.get('user_lat')) if order_info.get('user_lat') else None,
                "lng": float(order_info.get('user_lng')) if order_info.get('user_lng') else None
            },
            "driver": {
                "lat": float(status_obj['lat']) if status_obj and status_obj.get('lat') is not None else None,
                "lng": float(status_obj['lng']) if status_obj and status_obj.get('lng') is not None else None
            }
        },
        "created_at": order_info['created_at'].isoformat() if hasattr(order_info['created_at'], 'isoformat') else str(order_info['created_at']) if order_info.get('created_at') else None,
        "assigned_at": order_info.get('assigned_at').isoformat() if hasattr(order_info.get('assigned_at'), 'isoformat') else str(order_info.get('assigned_at')) if order_info.get('assigned_at') else None,
        "version": order_info.get('version', 1),
        "rider_id": order_info.get('rider_id'),
        "rider": order_info.get('rider'),
        "order_created_at": order_info['created_at'].isoformat() if hasattr(order_info['created_at'], 'isoformat') else str(order_info['created_at']) if order_info.get('created_at') else None,
        "estimated_total_minutes": TOTAL_DELIVERY_MINUTES,
        "remaining_minutes": eta_data["remaining_minutes"],
        "remaining_seconds": eta_data["remaining_seconds"],
        "eta_text": eta_data["eta_text"],
    }


def get_order_summary(order_id, is_admin_view=False):
    """Aggregates all order data using the shared Normalization Layer."""
    try:
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Fetch Raw Order Info
        cursor.execute("SELECT * FROM orders WHERE order_id = %s", (order_id,))
        order_info = cursor.fetchone()
        if not order_info:
            return None
            
        # 2. Fetch Customer Info (authoritative name/phone from users table)
        cursor.execute(
            "SELECT name, phone FROM users WHERE id = %s",
            (order_info["user_id"],)
        )
        customer_row = cursor.fetchone()
        if customer_row:
            order_info["customer_name"] = customer_row.get("name")
            order_info["customer_phone"] = customer_row.get("phone")

        # 3. Fetch Order Items — image resolved EXCLUSIVELY via JOIN to food_items.
        # STRICT RULE: order_items has NO image column in SELECT.
        # food_image alias carries the ONLY authoritative image source.
        query_items = """
            SELECT oi.id, oi.order_id, oi.item_id, oi.quantity, oi.price, oi.total_price,
                   f.name, f.image_url AS food_image
            FROM order_items oi
            JOIN food_items f ON oi.item_id = f.item_id
            WHERE oi.order_id = %s
        """
        cursor.execute(query_items, (order_id,))
        items = cursor.fetchall()
        
        # 4. Fetch Address Info
        cursor.execute("SELECT * FROM user_addresses WHERE id = %s", (order_info['address_id'],))
        address_info = cursor.fetchone()
        
        # 5. Fetch Rider Info (FULL object + latest location)
        if order_info.get('rider_id'):
            cursor.execute("""
                SELECT id, name, phone, rider_status, updated_at
                FROM users
                WHERE id = %s
            """, (order_info['rider_id'],))
            rider_data = cursor.fetchone()
            if rider_data:
                cursor.execute("""
                    SELECT lat, lng, heading, updated_at
                    FROM rider_locations
                    WHERE rider_id = %s
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (order_info['rider_id'],))
                rider_loc = cursor.fetchone()
                order_info['rider'] = {
                    "id": rider_data['id'],
                    "riderId": rider_data['id'],
                    "name": rider_data['name'],
                    "phone": rider_data['phone'],
                    "status": rider_data.get('rider_status'),
                    "lat": float(rider_loc['lat']) if rider_loc and rider_loc.get('lat') is not None else None,
                    "lng": float(rider_loc['lng']) if rider_loc and rider_loc.get('lng') is not None else None,
                    "heading": float(rider_loc['heading']) if rider_loc and rider_loc.get('heading') is not None else 0.0,
                    "updated_at": (
                        rider_loc.get('updated_at').isoformat()
                        if rider_loc and rider_loc.get('updated_at') and hasattr(rider_loc.get('updated_at'), 'isoformat')
                        else (
                            rider_data.get('updated_at').isoformat()
                            if rider_data.get('updated_at') and hasattr(rider_data.get('updated_at'), 'isoformat')
                            else str(rider_data.get('updated_at')) if rider_data.get('updated_at') else None
                        )
                    )
                }
            else:
                order_info['rider'] = None
        else:
            order_info['rider'] = None
            
        # 6. Use the Normalization Layer (Source of Truth)
        return normalize_order_data(order_info, items, address_info, is_admin_view=is_admin_view)
        
    except Exception as e:
        print(f"Error in get_order_summary for order {order_id}: {e}")
        return None
    finally:
        if 'conn' in locals() and conn:
            conn.close()

def get_order_details(order_id):
    # Keep this for backward compatibility if needed, but summary is preferred
    return get_order_summary(order_id)

def get_order_by_id(order_id):
    """Simple fetcher for a single order row."""
    try:
        # FORCE FRESH FETCH (FIX 1)
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM orders WHERE order_id = %s", (order_id,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Error in get_order_by_id: {e}")
        return None

def create_user(name, email, hashed_password=None, google_id=None, profile_pic=None):
    try:
        cursor = cnx.cursor()
        query = "INSERT INTO users (name, email, password, google_id, profile_pic, roles) VALUES (%s, %s, %s, %s, %s, %s)"
        cursor.execute(query, (name, email, hashed_password, google_id, profile_pic, '["customer"]'))
        cnx.commit()
        user_id = cursor.lastrowid
        cursor.close()
        return user_id
    except mysql.connector.Error as err:
        print(f"Error creating user: {err}")
        return None

def update_user_google_info(user_id, google_id, profile_pic):
    try:
        cursor = cnx.cursor()
        query = "UPDATE users SET google_id = %s, profile_pic = %s WHERE id = %s"
        cursor.execute(query, (google_id, profile_pic, user_id))
        cnx.commit()
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"Error updating user google info: {err}")
        return False

def get_user_by_email(email):
    cursor = cnx.cursor(dictionary=True)
    query = "SELECT * FROM users WHERE email = %s"
    cursor.execute(query, (email,))
    result = cursor.fetchone()
    if result:
        # Resolve roles array
        if result.get('roles'):
            try:
                if isinstance(result['roles'], str):
                    result['roles'] = json.loads(result['roles'])
            except Exception as e:
                print(f"Error parsing roles for {email}: {e}")
                result['roles'] = ["customer"]
        else:
            result['roles'] = ["customer"]
    cursor.close()
    return result

def get_user_by_id(user_id):
    cursor = cnx.cursor(dictionary=True)
    query = "SELECT id, name, email, google_id, profile_pic, role, roles, is_active, created_at FROM users WHERE id = %s"
    cursor.execute(query, (user_id,))
    result = cursor.fetchone()
    if result:
        # Resolve roles array
        if result.get('roles'):
            try:
                if isinstance(result['roles'], str):
                    result['roles'] = json.loads(result['roles'])
            except Exception as e:
                print(f"Error parsing roles for user {user_id}: {e}")
                result['roles'] = ["customer"]
        else:
            result['roles'] = ["customer"]
    cursor.close()
    return result


def get_available_orders(rider_id=None):
    """Fetches orders available for rider acceptance only."""
    try:
        logger.info(f"[AVAILABLE_ORDERS][RIDER_ID] {rider_id}")
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT o.*, u.name as customer_name
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.status = 'ASSIGNED'
            AND o.rider_id = %s
            ORDER BY o.created_at ASC
        """
        cursor.execute(query, (rider_id,))
        rows = cursor.fetchall()
        logger.info(f"[AVAILABLE_ORDERS][COUNT] {len(rows)}")
        cursor.close()
        conn.close()
        normalized = []
        for row in rows:
            summary = get_order_summary(row["order_id"])
            if summary:
                normalized.append(summary)
        return normalized
    except Exception as e:
        logger.error(f"[AVAILABLE_ORDERS][ERROR] {e}")
        return []

def get_rider_assigned_orders(rider_id):
    """
    Fetches active orders already assigned to THIS rider.
    STRICT RULE: Exclude DELIVERED and CANCELLED.
    """
    try:
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        # SOURCE OF TRUTH: Explicit IN() based filtering (Rule 1)
        status_placeholders = ', '.join(['%s'] * len(ACTIVE_STATES))
        query = f"""
            SELECT order_id
            FROM orders
            WHERE rider_id = %s 
            AND status IN ({status_placeholders})
            ORDER BY created_at DESC
        """
        cursor.execute(query, (rider_id, *ACTIVE_STATES))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        normalized = []
        for row in rows:
            summary = get_order_summary(row["order_id"])
            if summary:
                normalized.append(summary)
        return normalized
    except Exception as e:
        logger.error(f"Error in get_rider_assigned_orders: {e}")
        return []

def get_rider_active_orders(rider_id):
    """
    Fetches rider active orders only.
    ACTIVE = ACCEPTED, ORDER_PICKED_UP, OUT_FOR_DELIVERY
    """
    try:
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT order_id
            FROM orders
            WHERE rider_id = %s
            AND status IN ('ACCEPTED', 'ORDER_PICKED_UP', 'OUT_FOR_DELIVERY')
            ORDER BY created_at DESC
        """
        cursor.execute(query, (rider_id,))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        normalized = []
        for row in rows:
            summary = get_order_summary(row["order_id"])
            if summary:
                normalized.append(summary)
        return normalized
    except Exception as e:
        logger.error(f"Error in get_rider_active_orders: {e}")
        return []

def get_rider_completed_orders(rider_id):
    """
    Rider History: Returns orders where rider_id matches.
    Includes active and historical for consistency.
    """
    try:
        logger.info(f"[RIDER_HISTORY][REQUEST] rider_id={rider_id}")
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        # SOURCE OF TRUTH: Explicit IN() based filtering (Rule 1 & 2)
        status_placeholders = ', '.join(['%s'] * len(HISTORY_STATES))
        query = f"""
            SELECT o.*, u.name as customer_name
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.rider_id = %s 
            AND o.status IN ({status_placeholders})
            ORDER BY o.created_at DESC
        """
        cursor.execute(query, (rider_id, *HISTORY_STATES))
        result = cursor.fetchall()
        logger.info(f"[RIDER_HISTORY][RESULT_COUNT] {len(result)}")
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"[RIDER_HISTORY][ERROR] {e}")
        return []

def get_rider_history_orders(rider_id):
    """Fetches rider history orders only (DELIVERED)."""
    try:
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT o.*, u.name as customer_name
            FROM orders o
            JOIN users u ON o.user_id = u.id
            WHERE o.rider_id = %s
            AND o.status = 'DELIVERED'
            ORDER BY o.created_at DESC
        """
        cursor.execute(query, (rider_id,))
        result = cursor.fetchall()
        cursor.close()
        conn.close()
        return result
    except Exception as e:
        logger.error(f"Error in get_rider_history_orders: {e}")
        return []

def accept_assigned_order(order_id, rider_id):
    """
    Transition ASSIGNED -> ACCEPTED for the assigned rider only.
    """
    conn = None
    cursor = None
    try:
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT rider_id, status FROM orders WHERE order_id = %s FOR UPDATE",
            (order_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return "order_not_found"

        if row.get("rider_id") != rider_id:
            conn.rollback()
            return "not_assigned_to_rider"

        if row.get("status") == "ACCEPTED":
            conn.rollback()
            return "already_accepted"

        if row.get("status") != "ASSIGNED":
            conn.rollback()
            return "invalid_order_status"

        cursor.execute(
            """
            UPDATE orders
            SET status = 'ACCEPTED', accepted_at = CURRENT_TIMESTAMP, version = version + 1
            WHERE order_id = %s
            """,
            (order_id,)
        )
        cursor.execute(
            """
            INSERT INTO order_tracking (order_id, status, old_status, actor)
            VALUES (%s, 'ACCEPTED', 'ASSIGNED', 'RIDER')
            """,
            (order_id,)
        )
        conn.commit()
        return "accepted"
    except Exception as e:
        logger.error(f"Error in accept_assigned_order: {e}")
        if conn:
            conn.rollback()
        return "error"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def get_all_riders():
    """
    Fetches all riders for admin management.
    RULE: Returns ALL riders permanently without active/online filtering.
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        # Requirement: SELECT * FROM riders ORDER BY created_at DESC (using users table with rider role)
        # Requirement: Fetch riders with DYNAMIC availability computation
        query = """
            SELECT 
                u.id, u.name, u.email, u.phone, u.vehicle_type, u.license_number, 
                u.rider_status, u.is_active, u.profile_pic, u.created_at,
                (
                    SELECT COUNT(*) FROM orders o 
                    WHERE o.rider_id = u.id 
                    AND o.status NOT IN ('DELIVERED', 'CANCELLED', 'DELIVERED_SUCCESS')
                ) as active_orders_count
            FROM users u 
            WHERE u.role = 'rider' OR JSON_CONTAINS(u.roles, '"rider"')
            ORDER BY u.created_at DESC
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        
        # Safe Nullable Handling & Dynamic Status Mapping
        results = []
        for r in rows:
            # Source of truth for admin assignment dropdown: users.rider_status
            computed_status = (r.get('rider_status') or 'offline').lower()
            if not r['is_active']:
                computed_status = "offline"

            results.append({
                "id": r['id'],
                "name": r['name'] or "Unnamed",
                "email": r['email'],
                "phone": r['phone'] or "N/A",
                "vehicle_type": r['vehicle_type'] or "Not Set",
                "license_number": r['license_number'] or "N/A",
                "rider_status": computed_status,
                "active_orders": r['active_orders_count'],
                "is_active": int(r['is_active'] or 0),
                "profile_pic": r['profile_pic'],
                "created_at": r['created_at'].isoformat() if hasattr(r['created_at'], 'isoformat') else str(r['created_at'])
            })
        return results
    except Exception as e:
        print(f"[DB][RIDERS][ERROR] get_all_riders: {e}")
        return []

def create_rider_by_admin(name, email, phone, password_hash, vehicle_type, license_number, profile_pic=None):
    """Allows admin to create a rider account."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO users (name, email, phone, password, role, roles, vehicle_type, license_number, rider_status, is_active, profile_pic)
            VALUES (%s, %s, %s, %s, 'rider', '["rider"]', %s, %s, 'offline', 1, %s)
        """
        cursor.execute(query, (name, email, phone, password_hash, vehicle_type, license_number, profile_pic))
        conn.commit()
        user_id = cursor.lastrowid
        cursor.close()
        return user_id
    except Exception as e:
        print(f"Error in create_rider_by_admin: {e}")
        return None

def toggle_user_active(user_id, status: int):
    """Soft delete / Disable user."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = %s WHERE id = %s", (status, user_id))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"Error in toggle_user_active: {e}")
        return False

def log_admin_action(admin_id, action, order_id=None, details=None):
    """Logs administrative actions for auditing purposes."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = "INSERT INTO admin_audit_log (admin_id, action, order_id, details) VALUES (%s, %s, %s, %s)"
        cursor.execute(query, (admin_id, action, order_id, details))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"Error in log_admin_action: {e}")
        return False

# Consolidated with main assign_rider_to_order at line 868

def update_rider_location_cache(rider_id, lat, lng, heading=None, speed=None):
    """Updates the high-frequency GPS cache for a rider."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        query = """
            INSERT INTO rider_locations (rider_id, lat, lng, heading, speed, updated_at)
            VALUES (%s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON DUPLICATE KEY UPDATE
            lat = VALUES(lat), lng = VALUES(lng), heading = VALUES(heading), speed = VALUES(speed), updated_at = CURRENT_TIMESTAMP
        """
        cursor.execute(query, (rider_id, lat, lng, heading, speed))
        conn.commit()
        cursor.close()
        return True
    except Exception as e:
        print(f"Error in update_rider_location_cache: {e}")
        return False

def get_rider_stats(rider_id):
    """
    Calculates today's stats for a specific rider.
    Returns: completed_today, earnings_today, active_count
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Today's Completed and Earnings
        query_today = """
            SELECT 
                COUNT(*) as completed_today,
                IFNULL(SUM(delivery_fee), 0) as earnings_today
            FROM orders 
            WHERE rider_id = %s 
            AND status IN ('DELIVERED', 'DELIVERED_SUCCESS')
            AND DATE(delivered_at) = CURDATE()
        """
        cursor.execute(query_today, (rider_id,))
        today_stats = cursor.fetchone()
        
        # 2. Currently Active Orders
        query_active = """
            SELECT COUNT(*) as active_count
            FROM orders
            WHERE rider_id = %s
            AND status NOT IN ('DELIVERED', 'CANCELLED', 'DELIVERED_SUCCESS')
        """
        cursor.execute(query_active, (rider_id,))
        active_count = cursor.fetchone()['active_count']
        
        cursor.close()
        return {
            "completed_today": today_stats['completed_today'],
            "earnings_today": float(today_stats['earnings_today']),
            "active_count": active_count
        }
    except Exception as e:
        logger.error(f"Error in get_rider_stats: {e}")
        return {"completed_today": 0, "earnings_today": 0, "active_count": 0}

def get_rider_location(rider_id):
    """Fetches the latest cached location for a rider."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT rider_id, lat, lng, heading, speed, updated_at
            FROM rider_locations
            WHERE rider_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
        """
        cursor.execute(query, (rider_id,))
        result = cursor.fetchone()
        cursor.close()
        return result
    except Exception as e:
        print(f"Error in get_rider_location: {e}")
        return None

def get_rider_realtime_state(rider_id):
    """Returns authoritative rider status + latest location."""
    try:
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT id, rider_status, updated_at FROM users WHERE id = %s",
            (rider_id,)
        )
        rider_row = cursor.fetchone()
        if not rider_row:
            cursor.close()
            conn.close()
            return None

        cursor.execute(
            """
            SELECT lat, lng, heading, updated_at
            FROM rider_locations
            WHERE rider_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (rider_id,)
        )
        loc = cursor.fetchone()
        cursor.close()
        conn.close()

        updated_at_value = (
            loc.get("updated_at")
            if loc and loc.get("updated_at")
            else rider_row.get("updated_at")
        )
        updated_at_iso = (
            updated_at_value.isoformat()
            if updated_at_value and hasattr(updated_at_value, "isoformat")
            else str(updated_at_value) if updated_at_value else None
        )
        version = int(updated_at_value.timestamp()) if updated_at_value and hasattr(updated_at_value, "timestamp") else 0

        return {
            "rider_id": rider_row["id"],
            "rider_status": rider_row.get("rider_status"),
            "lat": float(loc["lat"]) if loc and loc.get("lat") is not None else None,
            "lng": float(loc["lng"]) if loc and loc.get("lng") is not None else None,
            "heading": float(loc["heading"]) if loc and loc.get("heading") is not None else 0.0,
            "updated_at": updated_at_iso,
            "version": version
        }
    except Exception as e:
        logger.error(f"Error in get_rider_realtime_state: {e}")
        return None

def get_admin_dashboard_stats():
    """Aggregates high-level stats for the admin dashboard."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Total Orders
        cursor.execute("SELECT COUNT(*) as total_orders FROM orders")
        total_orders = cursor.fetchone()['total_orders']
        
        # 2. Active Orders Count (Not Delivered or Cancelled)
        cursor.execute("SELECT COUNT(*) as active_count FROM orders WHERE status NOT IN ('DELIVERED', 'CANCELLED', 'DELIVERED_SUCCESS')")
        active_count = cursor.fetchone()['active_count']
        
        # 3. Total Customers
        cursor.execute("SELECT COUNT(*) as customer_count FROM users WHERE role = 'customer' OR JSON_CONTAINS(roles, '\"customer\"')")
        customer_count = cursor.fetchone()['customer_count']
        
        # 4. Total Riders
        cursor.execute("SELECT COUNT(*) as rider_count FROM users WHERE role = 'rider' OR JSON_CONTAINS(roles, '\"rider\"')")
        rider_count = cursor.fetchone()['rider_count']
        
        # 5. Total Revenue (Sum of all DELIVERED orders)
        cursor.execute("SELECT SUM(total_amount) as total_revenue FROM orders WHERE status IN ('DELIVERED', 'DELIVERED_SUCCESS')")
        total_revenue = cursor.fetchone()['total_revenue'] or 0
        
        # 6. Today's Revenue (DELIVERED today)
        cursor.execute("SELECT SUM(total_amount) as today_revenue FROM orders WHERE DATE(created_at) = CURDATE() AND status IN ('DELIVERED', 'DELIVERED_SUCCESS')")
        today_revenue = cursor.fetchone()['today_revenue'] or 0
        
        cursor.close()
        return {
            "total_orders": total_orders,
            "active_orders": active_count,
            "total_customers": customer_count,
            "total_riders": rider_count,
            "total_revenue": float(total_revenue),
            "today_revenue": float(today_revenue)
        }
    except Exception as e:
        logger.error(f"Error in get_admin_dashboard_stats: {e}")
        return {
            "total_orders": 0, "active_orders": 0, "total_customers": 0, 
            "total_riders": 0, "total_revenue": 0, "today_revenue": 0
        }

def get_admin_orders():
    """Fetches all orders with customer and rider names for admin view."""
    try:
        conn = _get_fresh_db_connection()
        cursor = conn.cursor(dictionary=True)
        query = "SELECT order_id FROM orders ORDER BY created_at DESC"
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        normalized = []
        for row in rows:
            summary = get_order_summary(row["order_id"], is_admin_view=True)
            if summary:
                normalized.append(summary)
        return normalized
    except Exception as e:
        logger.error(f"Error in get_admin_orders: {e}")
        return []

def get_user_orders(user_id):
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    query = """
        SELECT o.order_id, o.status, o.created_at, o.total_amount
        FROM orders o
        WHERE o.user_id = %s
        ORDER BY o.created_at DESC
    """
    cursor.execute(query, (user_id,))
    result = cursor.fetchall()
    cursor.close()
    return result

def get_user_orders_full(user_id):
    """Fetches all orders for a user with detailed items and address info."""
    try:
        orders_basic = get_user_orders(user_id)
        full_orders = []
        for order in orders_basic:
            summary = get_order_summary(order['order_id'])
            if summary:
                full_orders.append(summary)
        return full_orders
    except Exception as e:
        print(f"Error in get_user_orders_full: {e}")
        return []

def add_address(user_id, name, phone, address_line, city, state, pincode, is_default=False, latitude=None, longitude=None):
    try:
        cursor = cnx.cursor()
        
        # Check for duplicate
        cursor.execute("""
            SELECT id FROM user_addresses 
            WHERE user_id = %s AND address_line = %s AND pincode = %s
        """, (user_id, address_line, pincode))
        if cursor.fetchone():
            return "EXISTS"

        # Check if this is the first address
        cursor.execute("SELECT COUNT(*) FROM user_addresses WHERE user_id = %s", (user_id,))
        count = cursor.fetchone()[0]
        if count == 0:
            is_default = True
            
        if is_default:
            # Reset other defaults
            cursor.execute("UPDATE user_addresses SET is_default = FALSE WHERE user_id = %s", (user_id,))

        lat_val = None
        lng_val = None
        if latitude is not None and longitude is not None:
            try:
                lat_val = float(latitude)
                lng_val = float(longitude)
            except (TypeError, ValueError):
                lat_val, lng_val = None, None
            if lat_val is not None and not (-90.0 <= lat_val <= 90.0 and -180.0 <= lng_val <= 180.0):
                lat_val, lng_val = None, None

        has_geo = check_column_exists("user_addresses", "latitude")
        if has_geo:
            query = """
                INSERT INTO user_addresses (user_id, name, phone, address_line, city, state, pincode, is_default, latitude, longitude) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (user_id, name, phone, address_line, city, state, pincode, is_default, lat_val, lng_val))
        else:
            query = """
                INSERT INTO user_addresses (user_id, name, phone, address_line, city, state, pincode, is_default) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(query, (user_id, name, phone, address_line, city, state, pincode, is_default))
        cnx.commit()
        address_id = cursor.lastrowid
        cursor.close()
        return address_id
    except mysql.connector.Error as err:
        print(f"Error adding address: {err}")
        return None

def delete_address(user_id, address_id):
    try:
        cursor = cnx.cursor(dictionary=True)
        
        # Check if it was default
        cursor.execute("SELECT is_default FROM user_addresses WHERE id = %s AND user_id = %s", (address_id, user_id))
        result = cursor.fetchone()
        if not result:
            return False
            
        was_default = result['is_default']
        
        # Delete
        cursor.execute("DELETE FROM user_addresses WHERE id = %s AND user_id = %s", (address_id, user_id))
        
        # If it was default, assign another one
        if was_default:
            cursor.execute("SELECT id FROM user_addresses WHERE user_id = %s LIMIT 1", (user_id,))
            another = cursor.fetchone()
            if another:
                cursor.execute("UPDATE user_addresses SET is_default = TRUE WHERE id = %s", (another['id'],))
        
        cnx.commit()
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"Error deleting address: {err}")
        return False

def set_default_address(address_id, user_id):
    try:
        cursor = cnx.cursor()
        cursor.execute(
            "SELECT id FROM user_addresses WHERE id = %s AND user_id = %s",
            (address_id, user_id),
        )
        if not cursor.fetchone():
            cursor.close()
            return False
        cursor.execute("UPDATE user_addresses SET is_default = FALSE WHERE user_id = %s", (user_id,))
        cursor.execute(
            "UPDATE user_addresses SET is_default = TRUE WHERE id = %s AND user_id = %s",
            (address_id, user_id),
        )
        cnx.commit()
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"Error setting default address: {err}")
        return False

def get_default_address(user_id):
    try:
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM user_addresses WHERE user_id = %s AND is_default = TRUE LIMIT 1",
            (user_id,),
        )
        result = cursor.fetchone()
        if result:
            cursor.close()
            return result
        cursor.execute(
            "SELECT * FROM user_addresses WHERE user_id = %s ORDER BY id ASC LIMIT 1",
            (user_id,),
        )
        result = cursor.fetchone()
        cursor.close()
        return result
    except mysql.connector.Error as err:
        print(f"Error fetching default address: {err}")
        return None

def get_user_addresses(user_id):
    cursor = cnx.cursor(dictionary=True)
    query = "SELECT * FROM user_addresses WHERE user_id = %s ORDER BY created_at DESC"
    cursor.execute(query, (user_id,))
    result = cursor.fetchall()
    cursor.close()
    return result

def add_user_address(user_id, data):
    try:
        cursor = cnx.cursor()
        is_default = bool(data.get("is_default", False))
        if is_default:
            cursor.execute(
                "UPDATE user_addresses SET is_default = FALSE WHERE user_id = %s",
                (user_id,),
            )
        query = """
            INSERT INTO user_addresses (user_id, name, phone, address_line, city, state, pincode, is_default)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        cursor.execute(
            query,
            (
                user_id,
                data.get("name"),
                data.get("phone"),
                data.get("address_line"),
                data.get("city"),
                data.get("state"),
                data.get("pincode"),
                is_default,
            ),
        )
        cnx.commit()
        address_id = cursor.lastrowid
        cursor.close()
        return address_id
    except mysql.connector.Error as err:
        print(f"Error adding user address: {err}")
        return None

def update_user_address(address_id, user_id, data):
    try:
        cursor = cnx.cursor(dictionary=True)
        cursor.execute(
            "SELECT id FROM user_addresses WHERE id = %s AND user_id = %s",
            (address_id, user_id),
        )
        if not cursor.fetchone():
            cursor.close()
            return False

        if data.get("is_default"):
            cursor.execute(
                "UPDATE user_addresses SET is_default = FALSE WHERE user_id = %s",
                (user_id,),
            )

        allowed_fields = ("name", "phone", "address_line", "city", "state", "pincode", "is_default")
        updates = []
        values = []
        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        if not updates:
            cursor.close()
            return True

        values.extend([address_id, user_id])
        cursor.execute(
            f"UPDATE user_addresses SET {', '.join(updates)} WHERE id = %s AND user_id = %s",
            tuple(values),
        )
        cnx.commit()
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"Error updating user address: {err}")
        return False

def delete_user_address(address_id, user_id):
    return delete_address(user_id, address_id)

def get_cart_items(user_id):
    cursor = cnx.cursor(dictionary=True)
    query = """
        SELECT c.item_id, f.name, f.price, f.description, c.quantity, f.image_url 
        FROM cart c 
        JOIN food_items f ON c.item_id = f.item_id 
        WHERE c.user_id = %s
    """
    cursor.execute(query, (user_id,))
    result = cursor.fetchall()
    cursor.close()
    return result

def add_to_cart(user_id, item_id, quantity=1):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        
        # 1. Verify Item Exists
        cursor.execute("SELECT item_id FROM food_items WHERE item_id = %s", (item_id,))
        if not cursor.fetchone():
            print(f"❌ ERROR: Item {item_id} not found in food_items table")
            cursor.close()
            return False

        # 2. Check if item already in cart (Manual Upsert Logic - EXACT CODE)
        cursor.execute("""
            SELECT quantity FROM cart
            WHERE user_id = %s AND item_id = %s
        """, (user_id, item_id))
        
        existing = cursor.fetchone()

        if existing:
            print(f"Item exists. Updating quantity for user {user_id}")
            cursor.execute("""
                UPDATE cart
                SET quantity = quantity + %s
                WHERE user_id = %s AND item_id = %s
            """, (quantity, user_id, item_id))
        else:
            print(f"New item. Inserting for user {user_id}")
            cursor.execute("""
                INSERT INTO cart (user_id, item_id, quantity)
                VALUES (%s, %s, %s)
            """, (user_id, item_id, quantity))

        # 🚨 CRITICAL: Commit Transaction
        conn.commit()
        print("✅ DB TRANSACTION COMMITTED")
        
        # 3. Verify Insert Worked
        cursor.execute("SELECT * FROM cart WHERE user_id = %s", (user_id,))
        print("✅ CART AFTER INSERT:", cursor.fetchall())
        
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"❌ DB ERROR in add_to_cart: {err}")
        return False

def update_cart_quantity(user_id, item_id, quantity):
    try:
        cursor = cnx.cursor()
        if quantity <= 0:
            query = "DELETE FROM cart WHERE user_id = %s AND item_id = %s"
            cursor.execute(query, (user_id, item_id))
        else:
            query = "UPDATE cart SET quantity = %s WHERE user_id = %s AND item_id = %s"
            cursor.execute(query, (quantity, user_id, item_id))
        cnx.commit()
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"Error updating cart: {err}")
        return False

def remove_from_cart(user_id, item_id):
    try:
        cursor = cnx.cursor()
        query = "DELETE FROM cart WHERE user_id = %s AND item_id = %s"
        cursor.execute(query, (user_id, item_id))
        cnx.commit()
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"Error removing from cart: {err}")
        return False

def clear_cart(user_id):
    try:
        cursor = cnx.cursor()
        query = "DELETE FROM cart WHERE user_id = %s"
        cursor.execute(query, (user_id,))
        cnx.commit()
        cursor.close()
        return True
    except mysql.connector.Error as err:
        print(f"Error clearing cart: {err}")
        return False
if __name__ == "__main__":
    pass
