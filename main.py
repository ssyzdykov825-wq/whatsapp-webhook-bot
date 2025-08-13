import os
import time
import threading
import requests
import json
import re
from flask import Flask, request, jsonify
from openai import OpenAI
from datetime import datetime, timedelta

# Import the new state management functions
from state_manager import (
    init_db, load_cache_from_db,
    get_client_state, save_client_state, client_in_db_or_cache,
    follow_up_checker, cleanup_old_clients,
    MAX_HISTORY_FOR_GPT
)

# ✨ IMPORTING YOUR ACTUAL SALESRENDER API FUNCTIONS - ASSUMED TO BE WORKING ✨
# This means your salesrender_api.py should contain these functions and handle API calls correctly.
from salesrender_api import create_order, client_exists 


# ==============================
# Configuration
# ==============================
app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY") # Ensure this is set as an env var

HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

# In-memory set for message ID deduplication (volatile, resets on app restart)
PROCESSED_MESSAGES = set()

# SalesRender CRM Config (used within salesrender_api.py as well, but kept here for completeness if needed elsewhere)
# Ensure your salesrender_api.py uses these or its own method for config.
SALESRENDER_URL = os.environ.get("SALESRENDER_URL", "https://de.backend.salesrender.com/companies/1123/CRM")
SALESRENDER_TOKEN = os.environ.get("SALESRENDER_TOKEN", "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6iuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc")

# ==============================
# Phone Number Normalization
# ==============================
def normalize_phone_number(phone_raw):
    """
    Нормализует номер телефона к международному формату с '+'.
    Пример: '77071234567' -> '+77071234567'
            '87071234567' -> '+77071234567'
            '+77071234567' -> '+77071234567'
    """
    if not phone_raw:
        return ""
    
    # Удаляем все нецифровые символы
    phone_digits = re.sub(r'\D', '', phone_raw)

    if not phone_digits:
        return ""

    # Если начинается с 8, меняем на 7
    if phone_digits.startswith('8'):
        phone_digits = '7' + phone_digits[1:]
    
    # Если не начинается с 7, и имеет длину, подходящую для Казахстана (предполагаем 10 цифр после '7')
    if not phone_digits.startswith('7') and len(phone_digits) == 10: 
        phone_digits = '7' + phone_digits
    
    # Добавляем '+' в начало, если его нет
    if not phone_digits.startswith('+'):
        return '+' + phone_digits
    
    return phone_digits

# ==============================
# SalesRender Utilities
# ==============================
# Note: create_order and client_exists are now imported from salesrender_api.py
# Make sure your salesrender_api.py correctly implements fetch_order_from_crm if needed there.

def fetch_order_from_crm(order_id):
    """Fetches order details from SalesRender CRM using GraphQL."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": SALESRENDER_TOKEN
    }
    query = {
        "query": f"""
        query {{
            ordersFetcher(filters: {{ include: {{ ids: ["{order_id}"] }} }}) {{
                orders {{
                    id
                    data {{
                        humanNameFields {{ value {{ firstName lastName }} }}
                        phoneFields {{ value {{ international raw national }} }}
                    }}
                }}
            }}
        }}
        """
    }
    try:
        response = requests.post(SALESRENDER_URL, headers=headers, json=query, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
        return data[0] if data else None
    except Exception as e:
        print(f"❌ CRM fetch error: {e}")
        return None

def process_new_lead(name, phone):
    """
    Registers a new lead in bot's internal DB and creates order in CRM if needed.
    This function is primarily for the *initial* creation of a client record in the bot's DB
    and CRM order if the client is not in CRM. It assumes the CRM existence check is done by the caller.
    """
    # Check if client is already in bot's DB/cache.
    # If yes, no need to create a new record or order via this path.
    if client_in_db_or_cache(phone):
        print(f"⚠️ Клиент {phone} уже в базе/кэше (в process_new_lead), пропускаем создание/обновление.")
        return None 

    # If we reach here, client is new to bot's DB.
    # Now, check CRM again to decide if we need to create an order.
    # Note: This is an important check because client_exists might have been True earlier
    # leading to a reply, but client still needs to be added to bot's DB.
    crm_exists_status = client_exists(phone) # Call the real client_exists here

    if crm_exists_status:
        # Client exists in CRM, but is new to bot's DB. Just add to bot's DB, don't create new order.
        print(f"DEBUG: Client {phone} found in CRM, but new to bot's DB. Saving to bot's DB with in_crm=True.")
        save_client_state(phone, name=name, in_crm=True)
        return None # No new order created
    else:
        # Client does NOT exist in CRM (and is new to bot's DB). Create order.
        print(f"DEBUG: Client {phone} NOT found in CRM. Creating order and saving to bot's DB.")
        order_id = create_order(name, phone) # Call the real create_order

        if order_id:
            print(f"✅ Заказ {order_id} создан для {name}, {phone}. Обновляем состояние в боте.")
            save_client_state(phone, name=name, in_crm=True)
            return order_id
        else:
            print(f"❌ Не удалось создать заказ для {name}, {phone}. Создаем запись клиента без CRM связи в боте.")
            save_client_state(phone, name=name, in_crm=False)
            return None


def process_salesrender_order(order):
    """
    Processes a SalesRender order webhook. Updates client state and sends manager message.
    Adapted from your old code, integrated with new state management.
    """
    try:
        if not order.get("customer") and "id" in order:
            print(f"⚠ customer пуст, подтягиваю из CRM по ID {order['id']}")
            full_order = fetch_order_from_crm(order["id"])
            if full_order:
                order = full_order
            else:
                print("❌ CRM не вернул данные — пропуск")
                return

        first_name, last_name, phone = "", "", ""
        if "customer" in order:
            first_name = order.get("customer", {}).get("name", {}).get("firstName", "").strip()
            last_name = order.get("customer", {}).get("name", {}).get("lastName", "").strip()
            # Normalize phone directly from CRM data
            phone = normalize_phone_number(order.get("customer", {}).get("phone", {}).get("raw", "").strip())
        else:
            human_fields = order.get("data", {}).get("humanNameFields", [])
            phone_fields = order.get("data", {}).get("phoneFields", [])
            if human_fields:
                first_name = human_fields[0].get("value", {}).get("firstName", "").strip()
                last_name = human_fields[0].get("value", {}).get("lastName", "").strip()
            if phone_fields:
                # Normalize phone directly from CRM data
                phone = normalize_phone_number(phone_fields[0].get("value", {}).get("international", "").strip())

        name = f"{first_name} {last_name}".strip() or "Клиент"

        if not phone:
            print("❌ Телефон отсутствует — пропуск")
            return

        # If client is already in the system, no need to process as new lead
        # This prevents duplicate initial processing from SalesRender if client already messaged bot.
        if client_in_db_or_cache(phone): # Phone is already normalized here
            print(f"ℹ️ Клиент {phone} уже известен, обновляем его CRM статус.")
            save_client_state(phone, name=name, in_crm=True) # Ensure CRM status is true
            # We don't send manager message here assuming it's handled by CRM's own notifications
            return

        # For new leads from CRM, ensure they are added to our state system
        # This will add them to DB/cache and set in_crm=True (and potentially create order if client_exists is False)
        # Note: process_new_lead implicitly calls create_order (the imported one).
        process_new_lead(name, phone)


        # Manager message logic (from old code)
        now = datetime.utcnow()
        # last_sent is still in-memory for this specific rate-limiting purpose
        if phone in last_sent and now - last_sent[phone] < timedelta(minutes=3):
            print(f"⚠ Повторный недозвон по {phone} — пропускаем отправку менеджеру.")
            return

        # Determine greeting (UTC+6)
        now_kz = now + timedelta(hours=6)
        if 5 <= now_kz.hour < 12:
            greeting = "Қайырлы таң"
        elif 12 <= now_kz.hour < 18:
            greeting = "Сәлеметсіз бе"
        else:
            greeting = "Қайырлы кеш"

        # Generate message via GPT
        try:
            if name and name != "Клиент":
                prompt = (
                    f"{greeting}! Клиенттің аты {name}. "
                    f"Оған қоңырау шалдық, бірақ байланыс болмады. "
                    f"Клиентке WhatsApp-та қысқа, жылы, достық хабарлама жазыңыз. "
                    f"Хабарламаны Айдос атынан Healvix орталығынан жазыңыз."
                )
            else:
                prompt = (
                    f"{greeting}! Біз клиентке қоңырау шалдық, бірақ байланыс болмады. "
                    f"Клиентке WhatsApp-та қысқа, жылы, достық хабарлама жазыңыз. "
                    f"Хабарламаны Айдос атынан Healvix орталығынан жазыңыз. "
                    f"Есімін қолданбаңыз."
                )

            gpt_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            message_text = gpt_response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ GPT error: {e}")
            message_text = f"{greeting}! Біз сізге қоңырау шалдық, бірақ байланыс болмады. Уақытыңыз болса, хабарласыңыз."

        # Send to WhatsApp
        send_whatsapp_message(phone, message_text) # Re-using the main send_whatsapp_message

        # Remember dispatch
        last_sent[phone] = now
        print(f"✅ Message sent to {phone}")

    except Exception as e:
        print(f"❌ Error processing order: {e}")

# In-memory dict for rate-limiting manager messages (resets on app restart)
last_sent = {}

# ==============================
# GPT Prompts (refined)
# ==============================
SALES_SCRIPT_PROMPT = """
Сен — Айдос есімді Healvix көз емдеу орталығының тәжірибелі кеңесшісісің. Клиентпен жылы сөйлесіп, есімін сұрап, шын мәнінде көмектесуді мақсат тұтасың. Сен робот емессің — адам секілді, сенімді, жанашыр стилде сөйлесесің.

Жауаптарың қысқа да емес, артық та емес — нақты, эмоциямен, тірі адамша.

Егер клиент тақырыпты өзгертіп жіберсе немесе сұрағын ертерек қойса — икемдел, жауап бер.

Сөйлесу досыңызбен, жақыныңызбен сөйлескендей болсын. Артық пафос, шаблон жоқ. Сенім мен қарапайым тіл болсын.

Сөйлесуді бағыттауға көмектесетін мына қадамдар бар, бірақ сен еркін сөйлесе аласың:
"""

STAGE_PROMPTS = {
    "0": "Сәлеметсіз бе! 👋 Менің атым Айдос 😊, Healvix көз емдеу орталығынан жазып отырмын. Қалыңыз қалай? Есіміңіз кім, қай қаладансыз? Көзіңізге байланысты проблема бар ма?",
    "1": "Қазір нақтылап сұрайын: көруіңізде қандай өзгеріс бар? Бұлдырлау ма, қызару ма, ауырсыну ма, әлде катаракта белгілері ме? 👁️",
    "2": "Бұл жағдай қашан басталды? Бұрын дәрігерге қаралдыңыз ба? Капля қолдандыңыз ба, қандай ем жасап көрдіңіз? ⏳🩺",
    "3": "Көз — өте нәзік мүше. Егер уақытында қолға алмасаңыз, асқынып операцияға апаруы мүмкін. Бұл жағдай көру сапасына әсер етеді.",
    "4": "Сізге нақты көмектесетін өнімді ұсынам: Healvix — 100% табиғи кешен. Құрамында қаражидек, лютеин, кальций, E витамині бар. Бұл жай капля емес, көз ішіндегі қан айналымды қалпына келтіреді. 🌿💊",
    "5": "Біздің емдік курсымыз: 3 ай — 85 000₸, 6 ай — 180 000₸, 12 ай — 300 000₸. Бөліп төлеу де бар: айына 18 750₸ немесе 9 375₸. Сізге қайсысы ыңғайлы болады? 💰🎁",
    "6": "Қандай да бір күмән туындаса — нақты түсіндіріп берем. Сенімсіздік, баға, отбасы мәселесі — бәріне жауап дайын. Мысалы: 'Каспийіңізде 5-10 мың бар ма? Бүгін жазсақ, ертең бастап кетесіз.' 📲💸"
}

def build_messages_for_gpt(state, user_msg):
    """Builds messages for GPT, using the last N messages from history + current stage."""
    prompt = SALES_SCRIPT_PROMPT + "\n\n" + STAGE_PROMPTS.get(state["stage"], "")
    messages = [{"role": "system", "content": prompt}]

    recent_history = state["history"][-MAX_HISTORY_FOR_GPT:] 
    for item in recent_history:
        u = item.get("user", "")
        b = item.get("bot", "")
        if u:
            messages.append({"role": "user", "content": u})
        if b:
            messages.append({"role": "assistant", "content": b})

    messages.append({"role": "user", "content": user_msg})
    return messages


def split_message(text, max_length=1000):
    """Splits long texts by sentences or newlines for WhatsApp."""
    parts = []
    text = text.strip()
    while len(text) > max_length:
        split_index = max(text[:max_length].rfind("\n"), text[:max_length].rfind(". "))
        if split_index == -1 or split_index < max_length * 0.5:
            split_index = max_length
        parts.append(text[:split_index].strip())
        text = text[split_index:].lstrip()
    if text:
        parts.append(text)
    return parts


def send_whatsapp_message(phone, message):
    """Sends a message to WhatsApp via 360dialog API."""
    payload = {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": message}}
    try:
        response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload, timeout=15)
        print(f"📤 WhatsApp response: {getattr(response, 'status_code', 'no_response')}")
        return response
    except Exception as e:
        print(f"❌ WhatsApp request error: {e}")
        return None


def get_gpt_response(user_msg, phone):
    """Gets a response from GPT and updates client state."""
    state = get_client_state(phone)
    messages = build_messages_for_gpt(state, user_msg)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ GPT error: {e}")
        return "Кешіріңіз, қазір жауап бере алмаймын."

    try:
        next_stage_int = min(6, max(0, int(state["stage"])) + 1)
    except Exception:
        next_stage_int = 0
    next_stage = str(next_stage_int)

    new_history = list(state["history"]) + [{"user": user_msg, "bot": reply}]
    save_client_state(
        phone,
        stage=next_stage,
        history=new_history,
        last_time=time.time(),
        followed_up=False
    )
    return reply


# ==============================
# Flask Routes
# ==============================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(silent=True) or {}
    print("📩 Incoming JSON:", data)

    try:
        entry = (data.get("entry") or [{}])[0]
        changes = (entry.get("changes") or [{}])[0]
        value = changes.get("value") or {}
        messages = value.get("messages")
        contacts = value.get("contacts", [])

        if not messages:
            print("INFO: No messages in webhook payload.")
            return jsonify({"status": "no_message"}), 200

        msg = messages[0]
        msg_id = msg["id"]

        if msg_id in PROCESSED_MESSAGES:
            print(f"⏩ Message {msg_id} already processed — skipping")
            return jsonify({"status": "duplicate"}), 200
        PROCESSED_MESSAGES.add(msg_id)

        user_phone = normalize_phone_number(msg.get("from")) 
        user_msg = (msg.get("text") or {}).get("body", "")

        print(f"DEBUG: Processing message from normalized phone: {user_phone}, message: {user_msg}")

        if not (user_phone and isinstance(user_msg, str) and user_msg.strip()):
            print(f"INFO: Ignored message from {user_phone} due to empty content or invalid format.")
            return jsonify({"status": "ignored"}), 200

        # --- NEW LOGIC FOR CRM CHECK AND SILENT REGISTRATION ---
        should_send_bot_reply = False # Default to NOT replying initially for first contact

        # Get name from contacts if available (used for CRM registration if client is new)
        name = "Клиент" 
        if contacts and isinstance(contacts, list):
            profile = (contacts[0] or {}).get("profile") or {}
            name = profile.get("name", "Клиент")

        # 1. Check if client exists in our bot's internal DB/cache (prioritize fast lookup)
        client_in_bot_db = client_in_db_or_cache(user_phone)

        if client_in_bot_db:
            # Client is known to our bot's internal DB (either from previous interaction or SalesRender hook).
            # Always reply.
            print(f"DEBUG: Client {user_phone} found in bot's DB. Continuing conversation.")
            should_send_bot_reply = True
        else:
            # Client is NOT known to our bot's internal DB. This is a potential first-time interaction for the bot.
            # Now, check SalesRender CRM using YOUR working client_exists.
            crm_already_exists = client_exists(user_phone) 

            if crm_already_exists:
                # Client found in CRM, but is NEW to bot's internal DB.
                # Add to bot's DB and then reply.
                print(f"DEBUG: Client {user_phone} FOUND in CRM but NEW to bot's DB. Adding to bot's DB and replying.")
                # We don't need to call create_order here as client already exists in CRM.
                save_client_state(user_phone, name=name, in_crm=True) # Ensure 'in_crm' is set to True
                should_send_bot_reply = True
            else:
                # Client NOT found in CRM, and is NEW to bot's internal DB.
                # Silently register in CRM (via process_new_lead) and bot's DB.
                print(f"DEBUG: Client {user_phone} NOT found in CRM and NEW to bot's DB. Silently registering lead.")
                process_new_lead(name, user_phone) # This calls your create_order and saves to bot's DB.
                should_send_bot_reply = False # Bot remains silent for this first interaction

        # Final decision to send reply
        if should_send_bot_reply:
            reply = get_gpt_response(user_msg.strip(), user_phone)
            for part in split_message(reply):
                send_whatsapp_message(user_phone, part)
        else:
            print(f"DEBUG: Silently processed new client {user_phone}. No immediate bot reply sent.")

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/salesrender-hook', methods=['POST'])
def salesrender_hook():
    print("=== Incoming request to /salesrender-hook ===")
    try:
        data = request.get_json(silent=True) or {}
        print("Payload:", json.dumps(data, indent=2, ensure_ascii=False))

        orders = (
            data.get("data", {}).get("orders")
            or data.get("orders")
            or [data]
        )

        if not orders or not isinstance(orders, list):
            return jsonify({"error": "No orders found or invalid format"}), 400

        threading.Thread(
            target=process_salesrender_order,
            args=(orders[0],),
            daemon=True
        ).start()

        return jsonify({"status": "accepted"}), 200
    except Exception as e:
        print(f"❌ Webhook parsing error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/', methods=['GET'])
def home():
    return "Healvix бот іске қосылды!", 200

# ==============================
# Application Startup - Moved outside if __name__ == "__main__" for Gunicorn
# ==============================

print("DEBUG: Starting application initialization (outside if __name__).")
init_db() # Initialize the database
print("DEBUG: Database init_db() completed (outside if __name__).")
load_cache_from_db() # Load all existing clients into cache
print("DEBUG: Cache loaded from DB (outside if __name__).")

threading.Thread(target=follow_up_checker, args=(send_whatsapp_message,), daemon=True).start()
print("DEBUG: Follow-up checker thread started.")
threading.Thread(target=cleanup_old_clients, daemon=True).start()
print("DEBUG: Cleanup old clients thread started.")

if __name__ == "__main__":
    print("DEBUG: Running app in local development mode via 'python app.py'.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
