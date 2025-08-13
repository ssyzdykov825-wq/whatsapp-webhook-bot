import psycopg2 # Changed from sqlite3
import json
import time
import threading
from datetime import datetime, timedelta
import os

# ==============================
# Configuration for State Manager
# ==============================
# Use DATABASE_URL for PostgreSQL, typically from environment variables
DATABASE_URL = os.environ.get("DATABASE_URL")

# Global structures (in-memory cache)
clients_cache = {}  # phone -> state

# One re-entrant lock for all operations to avoid deadlocks
state_lock = threading.RLock()

# Bot behavior settings (moved from main app to state manager as they relate to state)
FOLLOW_UP_DELAY = int(os.environ.get("FOLLOW_UP_DELAY", 60))  # seconds
FOLLOW_UP_MESSAGE = os.environ.get(
    "FOLLOW_UP_MESSAGE",
    "Сізден жауап болмай жатыр 🤔 Сұрақтарыңыз болса, жауап беруге дайынмын."
)
MAX_HISTORY_FOR_GPT = int(os.environ.get("MAX_HISTORY_FOR_GPT", 10))
CLEANUP_DAYS = int(os.environ.get("CLEANUP_DAYS", 30))

# ==============================
# PostgreSQL Connection Helper
# ==============================
def get_db_connection():
    """Establishes a connection to the PostgreSQL database."""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is not set!")
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"❌ Error connecting to PostgreSQL: {e}")
        raise # Re-raise the exception to propagate it

# ==============================
# Database Initialization
# ==============================
def init_db():
    """Initializes the PostgreSQL database, creating the clients table if it doesn't exist."""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Using BOOLEAN for in_crm and followed_up, DOUBLE PRECISION for time
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            phone TEXT PRIMARY KEY,
            name TEXT,
            in_crm BOOLEAN DEFAULT FALSE,
            stage TEXT DEFAULT '0',
            history TEXT DEFAULT '[]',
            last_message_time DOUBLE PRECISION,
            followed_up BOOLEAN DEFAULT FALSE
        )
        """)
        conn.commit()
        print("PostgreSQL database initialized.")
    except Exception as e:
        print(f"❌ Error during PostgreSQL DB initialization: {e}")
        # Depending on severity, you might want to raise, exit, or just log
    finally:
        if conn:
            conn.close()

def load_cache_from_db():
    """Loads all client records from the database into in-memory cache at startup."""
    with state_lock:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT phone, name, in_crm, stage, history, last_message_time, followed_up FROM clients")
            rows = cursor.fetchall()
            
            clients_cache.clear() # Clear existing cache before loading
            for phone, name, in_crm, stage, history_json, last_time, followed_up in rows:
                try:
                    history = json.loads(history_json) if history_json else []
                except Exception:
                    history = [] # Fallback for corrupted history
                clients_cache[phone] = {
                    "name": name or "Клиент",
                    "stage": stage or "0",
                    "history": history,
                    "last_time": float(last_time) if last_time else time.time(),
                    "followed_up": bool(followed_up),
                    "in_crm": bool(in_crm),
                }
            print(f"Cache loaded: {len(clients_cache)} clients.")
        except Exception as e:
            print(f"❌ Error loading cache from PostgreSQL: {e}")
        finally:
            if conn:
                conn.close()

def persist_client_to_db(phone, state):
    """Saves a single client's state to the database (upsert operation)."""
    with state_lock:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if record exists (PostgreSQL doesn't have a direct UPSERT via INSERT OR REPLACE like SQLite)
            cursor.execute("SELECT 1 FROM clients WHERE phone = %s", (phone,))
            exists = cursor.fetchone() is not None

            if exists:
                cursor.execute("""
                    UPDATE clients
                    SET name=%s, stage=%s, history=%s, last_message_time=%s, followed_up=%s, in_crm=%s
                    WHERE phone=%s
                """, (
                    state["name"],
                    state["stage"],
                    json.dumps(state["history"], ensure_ascii=False), # Serialize history to JSON string
                    state["last_time"],
                    state["followed_up"], # psycopg2 handles Python bools to PostgreSQL BOOLEAN
                    state["in_crm"],    # psycopg2 handles Python bools to PostgreSQL BOOLEAN
                    phone
                ))
            else:
                cursor.execute("""
                    INSERT INTO clients (phone, name, stage, history, last_message_time, followed_up, in_crm)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    phone,
                    state["name"],
                    state["stage"],
                    json.dumps(state["history"], ensure_ascii=False),
                    state["last_time"],
                    state["followed_up"],
                    state["in_crm"]
                ))
            conn.commit()
        except Exception as e:
            print(f"❌ Error persisting client {phone} to PostgreSQL: {e}")
        finally:
            if conn:
                conn.close()

def delete_client_from_db(phone):
    """Deletes a client record from the database."""
    with state_lock:
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM clients WHERE phone = %s", (phone,))
            conn.commit()
            print(f"Client {phone} deleted from PostgreSQL DB.")
        except Exception as e:
            print(f"❌ Error deleting client {phone} from PostgreSQL: {e}")
        finally:
            if conn:
                conn.close()

# ==============================
# State Helper Functions (RAM <-> DB interaction)
# ==============================
def client_in_db_or_cache(phone):
    """Checks if a client exists in the cache or database."""
    with state_lock:
        if phone in clients_cache:
            return True
        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM clients WHERE phone = %s", (phone,))
            exists = cursor.fetchone() is not None
            return exists
        except Exception as e:
            print(f"❌ Error checking client existence in PostgreSQL: {e}")
            return False # Assume not exists on error
        finally:
            if conn:
                conn.close()

def get_client_state(phone):
    """
    Retrieves client state from cache. If not found, loads from DB and caches it.
    If not in DB, creates a default state, caches it, and persists to DB.
    Returns a copy of the state to prevent accidental global modification.
    """
    with state_lock:
        state = clients_cache.get(phone)
        if state:
            return dict(state) # Return a copy

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT name, in_crm, stage, history, last_message_time, followed_up FROM clients WHERE phone = %s", (phone,))
            row = cursor.fetchone()
            
            if row:
                name, in_crm, stage, history_json, last_time, followed_up = row
                try:
                    history = json.loads(history_json) if history_json else []
                except Exception:
                    history = []
                state = {
                    "name": name or "Клиент",
                    "stage": stage or "0",
                    "history": history,
                    "last_time": float(last_time) if last_time else time.time(),
                    "followed_up": bool(followed_up),
                    "in_crm": bool(in_crm),
                }
                clients_cache[phone] = dict(state) # Add to cache
                return dict(state) # Return a copy
            
            # If not in DB, create default state
            state = {
                "name": "Клиент",
                "stage": "0",
                "history": [],
                "last_time": time.time(),
                "followed_up": False,
                "in_crm": False,
            }
            clients_cache[phone] = dict(state) # Add to cache
            persist_client_to_db(phone, state) # Persist new default state
            return dict(state) # Return a copy
        except Exception as e:
            print(f"❌ Error getting client state from PostgreSQL: {e}")
            # Fallback to creating a new default state if DB access fails
            state = {
                "name": "Клиент",
                "stage": "0",
                "history": [],
                "last_time": time.time(),
                "followed_up": False,
                "in_crm": False,
            }
            clients_cache[phone] = dict(state)
            return dict(state)
        finally:
            if conn:
                conn.close()

def save_client_state(phone, **kwargs):
    """
    Updates client state in cache and DB. Only specified fields are changed.
    Ensures 'last_time' is updated unless explicitly set to None.
    """
    with state_lock:
        current_state = clients_cache.get(phone)
        if not current_state:
            # If not in cache, get it (will load from DB or create default)
            current_state = get_client_state(phone)
            # get_client_state returns a copy, we need the actual cached object to modify
            current_state = clients_cache[phone] 

        # Update fields from kwargs
        for key, value in kwargs.items():
            if key == "history" and value is not None:
                current_state["history"] = value
            elif value is not None:
                current_state[key] = value
        
        # Always update last_time unless explicitly told not to (e.g., last_time=None)
        if "last_time" not in kwargs or kwargs["last_time"] is not None:
            current_state["last_time"] = time.time()

        # Save to cache
        clients_cache[phone] = dict(current_state) # Store a fresh copy
        # Save to DB
        persist_client_to_db(phone, current_state)

# ==============================
# Background Tasks (no changes here, they use save_client_state)
# ==============================
def follow_up_checker(send_whatsapp_message_func):
    """Periodically checks for clients needing a follow-up message."""
    while True:
        try:
            now = time.time()
            with state_lock:
                # Create a copy of items to iterate safely
                items = list(clients_cache.items())

            for phone, st in items:
                last_time = st.get("last_time")
                followed_up = st.get("followed_up", False)
                if last_time and (now - last_time > FOLLOW_UP_DELAY) and not followed_up:
                    print(f"[🔔] Отправка follow-up клиенту {phone}")
                    send_whatsapp_message_func(phone, "📌 Айдос: " + FOLLOW_UP_MESSAGE)
                    save_client_state(phone, followed_up=True) # Update state in DB and cache
        except Exception as e:
            print(f"❌ Follow-up error: {e}")
        time.sleep(30) # Check every 30 seconds

def cleanup_old_clients():
    """Periodically removes old client records from cache and database."""
    while True:
        try:
            cutoff_time = time.time() - CLEANUP_DAYS * 24 * 60 * 60
            removed_count = 0
            with state_lock:
                # Identify clients to delete from cache
                to_delete = [p for p, st in clients_cache.items() if st.get("last_time", 0) < cutoff_time]
                for phone in to_delete:
                    delete_client_from_db(phone) # Delete from DB
                    clients_cache.pop(phone, None) # Remove from cache
                    removed_count += 1
            if removed_count:
                print(f"🧹 Database/cache cleanup: removed {removed_count} clients (inactive for {CLEANUP_DAYS}+ days).")
        except Exception as e:
            print(f"❌ Database cleanup error: {e}")
        time.sleep(24 * 60 * 60) # Run once every 24 hours
