# 💡 Расширенная версия GPT-бота Healvix с рабочим follow-up

import os
import time
import threading
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY")

HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

USER_STATE = {}

FOLLOW_UP_DELAY = 60  # 1 минут
FOLLOW_UP_MESSAGE = (
    "Сізден жауап болмай жатыр 🤔 Көмек керек болса, қазір жазуға болады. "
    "Былай істейік: мен өз атымнан жеңілдік жасап көрейін. Қазір Каспийде 5-10 мың бар ма?"
)

# ... (SALES_SCRIPT_PROMPT и STAGE_PROMPTS оставить без изменений) ...

# --- УЛУЧШЕННАЯ send_whatsapp_message ---
def send_whatsapp_message(phone, message):
    try:
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": message}
        }
        response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
        print(f"\U0001F4E4 WhatsApp жауап: {response.status_code} | {response.text}")
        return response
    except Exception as e:
        print(f"❌ WhatsApp қатесі: {e}")
        return None

# --- follow-up checker С ЛОГАМИ ---
def follow_up_checker():
    print("🚀 Follow-up checker запущен!")
    while True:
        now = time.time()
        for phone, state in list(USER_STATE.items()):
            last_time = state.get("last_time")
            last_stage = state.get("stage", "0")
            followed_up = state.get("followed_up", False)

            if last_time:
                elapsed = now - last_time
                print(f"[⏱️] {phone}: прошло {elapsed:.1f} сек | stage={last_stage} | follow_up={followed_up}")
                if elapsed > FOLLOW_UP_DELAY and not followed_up:
                    print(f"[🔔] Отправка follow-up клиенту {phone}")
                    send_whatsapp_message(phone, "📌 Айдос: " + FOLLOW_UP_MESSAGE)
                    USER_STATE[phone]["followed_up"] = True
            else:
                print(f"[⚠️] {phone} — нет last_time")

        time.sleep(30)

# --- Запуск follow-up потока без условия if __name__ ---
threading.Thread(target=follow_up_checker, daemon=True).start()

# --- Остальной код (get_gpt_response, split_message, webhook и т.д.) ---
# --- оставить без изменений, но можно добавить логгирование внутри get_gpt_response ---

@app.route("/", methods=["GET"])
def home():
    return "Healvix бот іске қосылды!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
