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
FOLLOW_UP_DELAY = int(os.environ.get("FOLLOW_UP_DELAY", 12 * 60 * 60))  # 12 часов
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
        raise ValueError("DATABASE_URL environment variable is not set! Please configure it for PostgreSQL.")
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
        raise # ✨ Это заставит приложение упасть, если создание таблицы не удалось ✨
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
            
            # Логируем запрос на SELECT
            select_query = "SELECT 1 FROM clients WHERE phone = %s"
            # print(f"DEBUG SM: Checking existence for phone: {phone} with query: {select_query}") # Закомментировано, чтобы не загромождать логи

            cursor.execute(select_query, (phone,))
            exists = cursor.fetchone() is not None

            if exists:
                update_query = """
                    UPDATE clients
                    SET name=%s, stage=%s, history=%s, last_message_time=%s, followed_up=%s, in_crm=%s
                    WHERE phone=%s
                """
                cursor.execute(update_query, (
                    state["name"], state["stage"], json.dumps(state["history"], ensure_ascii=False),
                    state["last_time"], state["followed_up"], state["in_crm"], phone
                ))
                print(f"DEBUG SM: Client {phone} state UPDATED in DB. Stage: {state['stage']}.")
            else:
                insert_query = """
                    INSERT INTO clients (phone, name, stage, history, last_message_time, followed_up, in_crm)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(insert_query, (
                    phone, state["name"], state["stage"], json.dumps(state["history"], ensure_ascii=False),
                    state["last_time"], state["followed_up"], state["in_crm"]
                ))
                print(f"DEBUG SM: Client {phone} state INSERTED into DB. Stage: {state['stage']}.")
            conn.commit()
            print(f"DEBUG SM: DB commit successful for {phone}.")
        except Exception as e:
            # Оставим raise для более строгой диагностики
            print(f"❌ ERROR SM: Failed to persist client {phone} to PostgreSQL: {e}")
            import traceback
            traceback.print_exc() # Добавлено для полного стека ошибок
            raise # ✨ Важно: снова выбрасываем ошибку, чтобы увидеть ее полностью в логах ✨
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
            print(f"DEBUG SM: Client {phone} state found in cache.")
            return dict(state)

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
                except Exception as ex_history:
                    history = []
                    print(f"WARNING SM: History for {phone} could not be parsed: {ex_history}. Resetting history to empty.")
                
                state = {
                    "name": name or "Клиент",
                    "stage": stage or "0",
                    "history": history,
                    "last_time": float(last_time) if last_time else time.time(),
                    "followed_up": bool(followed_up),
                    "in_crm": bool(in_crm),
                }
                clients_cache[phone] = dict(state) # Add to cache
                print(f"DEBUG SM: Client {phone} state loaded from DB and added to cache. Stage: {state['stage']}.")
                return dict(state)
            
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
            print(f"DEBUG SM: Client {phone} state created as default (not found in DB/cache).")
            return dict(state)
        except Exception as e:
            print(f"❌ ERROR SM: Failed to get client state for {phone} from DB: {e}")
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
            print(f"DEBUG SM: Client {phone} state created as default due to DB error fallback.")
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
# Background Tasks
# ==============================
def follow_up_checker(send_whatsapp_message_func):
    """Follow-up отключен"""
    while True:
        time.sleep(60)  # просто ждет и ничего не делает

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
