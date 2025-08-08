# app.py
import os
import time
import threading
import requests
import logging
from flask import Flask, request, jsonify
from openai import OpenAI
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Настройки (установи переменные окружения)
WHATSAPP_API_URL = os.environ.get("WHATSAPP_API_URL", "https://waba-v2.360dialog.io/messages")
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY", "")
HEADERS = {"Content-Type": "application/json", "D360-API-KEY": WHATSAPP_API_KEY}

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")  # если надо верифицировать GET challenge
PORT = int(os.environ.get("PORT", 5000))

# state
USER_STATE = {}
last_sent = {}
processed_messages = {}  # msg_id -> timestamp

# (вставь сюда свой SALES_SCRIPT_PROMPT и STAGE_PROMPTS из вашего кода)
SALES_SCRIPT_PROMPT = """...вставь полный SALES_SCRIPT_PROMPT тут..."""
STAGE_PROMPTS = {
    "0": "Сәлеметсіз бе! 👋 ...",
    "1": "...",
    # и т.д. (вставь свои)
}

# утилиты
def split_message(text, max_length=1000):
    parts = []
    while len(text) > max_length:
        split_index = text[:max_length].rfind(". ")
        if split_index == -1:
            split_index = max_length
        parts.append(text[:split_index+1].strip())
        text = text[split_index+1:].strip()
    if text:
        parts.append(text)
    return parts

def send_whatsapp_message(phone, message):
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }
    try:
        r = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload, timeout=10)
        log.info(f"WhatsApp send -> {r.status_code} {r.text}")
        return r
    except Exception as e:
        log.exception("Ошибка отправки в WhatsApp")
        return None

def get_gpt_response(user_msg, user_phone):
    try:
        user_data = USER_STATE.get(user_phone, {})
        history = user_data.get("history", [])
        stage = user_data.get("stage", "0")
        prompt = SALES_SCRIPT_PROMPT + "\n\n" + STAGE_PROMPTS.get(stage, "")
        messages = [{"role": "system", "content": prompt}]
        for item in history:
            messages.append({"role": "user", "content": item["user"]})
            messages.append({"role": "assistant", "content": item["bot"]})
        messages.append({"role": "user", "content": user_msg})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()
        next_stage = str(int(stage) + 1) if int(stage) < 6 else "6"
        USER_STATE[user_phone] = {
            "history": history[-5:] + [{"user": user_msg, "bot": reply}],
            "last_message": user_msg,
            "stage": next_stage,
            "last_time": time.time(),
            "followed_up": False
        }
        return reply
    except Exception as e:
        log.exception("GPT error")
        return "Кешіріңіз, қазір жауап бере алмаймын. Кейінірек көріңіз."

# обработка входящих 360dialog
def extract_messages(payload):
    # Поддержка нескольких форматов: simple {messages: [...] } и meta-style entry/changes/value/messages
    if not payload:
        return []
    if isinstance(payload.get("messages"), list):
        return payload.get("messages")
    msgs = []
    for entry in payload.get("entry", []) or []:
        for ch in entry.get("changes", []) or []:
            val = ch.get("value", {}) or {}
            if isinstance(val.get("messages"), list):
                msgs.extend(val.get("messages"))
    return msgs

def prune_processed(max_age_seconds=24*3600):
    now = time.time()
    keys = [k for k, ts in processed_messages.items() if now - ts > max_age_seconds]
    for k in keys:
        processed_messages.pop(k, None)

def handle_incoming(payload):
    try:
        log.info("handle_incoming started")
        msgs = extract_messages(payload)
        if not msgs:
            log.info("No messages found in payload")
            return
        prune_processed()
        for m in msgs:
            msg_id = m.get("id") or m.get("message_id") or m.get("mid")
            phone = m.get("from") or m.get("wa_id")
            if not phone:
                # try contacts
                if isinstance(m.get("contacts"), list) and m["contacts"]:
                    phone = m["contacts"][0].get("wa_id") or m["contacts"][0].get("phone")
            if not phone:
                log.warning("No phone for message: %s", m)
                continue
            if msg_id and msg_id in processed_messages:
                log.info("Duplicate message id, skipping: %s", msg_id)
                continue
            if msg_id:
                processed_messages[msg_id] = time.time()

            # extract text
            user_text = ""
            if m.get("type") == "text":
                user_text = m.get("text", {}).get("body", "")
            elif m.get("type") == "interactive":
                user_text = (m.get("interactive", {}).get("button_reply", {}).get("title")
                             or m.get("interactive", {}).get("list_reply", {}).get("title") or "")
            else:
                # другие типы можно пропустить
                user_text = m.get("text", {}).get("body", "") or ""
            if not user_text:
                log.info("Empty text, skipping")
                continue

            log.info("Getting GPT reply for %s: %s", phone, user_text[:80])
            reply = get_gpt_response(user_text, phone)
            for part in split_message(reply, 1000):
                send_whatsapp_message(phone, part)
    except Exception as e:
        log.exception("handle_incoming error")

# CRM hook processing (как у тебя было, но в фоне)
def process_salesrender(data):
    try:
        log.info("processing salesrender data")
        orders = (data.get("data", {}).get("orders") or data.get("orders") or [])
        if not orders:
            log.warning("No orders in CRM payload")
            return
        order = orders[0]
        first_name = order.get("customer", {}).get("name", {}).get("firstName", "").strip()
        last_name = order.get("customer", {}).get("name", {}).get("lastName", "").strip()
        name = f"{first_name} {last_name}".strip()
        phone = order.get("customer", {}).get("phone", {}).get("raw", "").strip()
        if not phone:
            log.warning("CRM order has no phone")
            return
        now = datetime.utcnow()
        if phone in last_sent and now - last_sent[phone] < timedelta(hours=6):
            log.info("Duplicate recent send, skipping %s", phone)
            return

        now_kz = now + timedelta(hours=6)
        hour = now_kz.hour
        greeting = "Қайырлы таң" if 5 <= hour < 12 else ("Сәлеметсіз бе" if 12 <= hour < 18 else "Қайырлы кеш")

        if name:
            prompt = f"{greeting}! Клиенттің аты {name}. Оған қоңырау шалдық, бірақ байланыс болмады..."
        else:
            prompt = f"{greeting}! Біз клиентке қоңырау шалдық, бірақ байланыс болмады..."

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            message_text = response.choices[0].message.content.strip()
        except Exception:
            log.exception("GPT failed in CRM flow")
            message_text = f"{greeting}! Біз сізге қоңырау шалдық, бірақ байланыс болмады. Уақытыңыз болса, хабарласыңыз."

        send_whatsapp_message(phone, message_text)
        last_sent[phone] = now
        log.info("CRM message sent to %s", phone)
    except Exception:
        log.exception("process_salesrender error")

# Flask routes
@app.route("/", methods=["GET"])
def index():
    return "OK", 200

@app.route("/webhook", methods=["GET", "POST"])
def whatsapp_webhook():
    if request.method == "GET":
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        if mode and token and challenge:
            if VERIFY_TOKEN is None or token == VERIFY_TOKEN:
                return challenge, 200
            return "Forbidden", 403
        return "OK", 200

    # POST
    try:
        payload = request.get_json(force=True)
    except Exception as e:
        log.exception("invalid json")
        return jsonify({"error": "invalid json"}), 400

    log.info("Received webhook (quick ack)")
    threading.Thread(target=handle_incoming, args=(payload,), daemon=True).start()
    return jsonify({"status": "received"}), 200

@app.route("/salesrender-hook", methods=["POST"])
def salesrender_hook():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        log.exception("invalid crm json")
        return jsonify({"error": "invalid json"}), 400
    threading.Thread(target=process_salesrender, args=(data,), daemon=True).start()
    return jsonify({"status": "accepted"}), 200

# follow-up checker из твоего кода
FOLLOW_UP_DELAY = 60
FOLLOW_UP_MESSAGE = "Сізден жауап болмай жатыр 🤔 Сұрақтарыңыз болса, жауап беруге дайынмын."

def follow_up_checker():
    while True:
        now_ts = time.time()
        for phone, state in list(USER_STATE.items()):
            last_time = state.get("last_time")
            if not last_time:
                continue
            elapsed = now_ts - last_time
            if elapsed > FOLLOW_UP_DELAY and not state.get("followed_up"):
                log.info("Sending follow-up to %s", phone)
                send_whatsapp_message(phone, "📌 Айдос: " + FOLLOW_UP_MESSAGE)
                USER_STATE[phone]["followed_up"] = True
        time.sleep(30)

@app.before_first_request
def start_background_threads():
    # followup
    if not getattr(app, "followup_started", False):
        app.followup_started = True
        t = threading.Thread(target=follow_up_checker, daemon=True)
        t.start()
        log.info("Started followup checker")

if __name__ == "__main__":
    log.info("Starting app on port %s", PORT)
    app.run(host="0.0.0.0", port=PORT)
