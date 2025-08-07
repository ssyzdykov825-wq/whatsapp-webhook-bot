import os
import requests
from flask import Flask, request, jsonify
from openai import OpenAI
from handlers import fsm_healvix_kz

app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY")

HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

# Общее хранилище состояний
USER_STATES = fsm_healvix_kz.USER_STATES

# Базовый system-промпт
BASE_PROMPT = """
Ты — опытный консультант по продукту Healvix — натуральному средству для восстановления зрения.
"""

def send_whatsapp_message(phone, message):
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
    print(f"📤 Ответ от сервера: {response.status_code} {response.text}")
    return response

def get_gpt_response(user_msg, user_phone):
    try:
        history = USER_STATES.get(user_phone, {}).get("history", [])

        messages = [{"role": "system", "content": BASE_PROMPT}]
        for h in history:
            messages.append({"role": "user", "content": h["user"]})
            messages.append({"role": "assistant", "content": h["bot"]})
        messages.append({"role": "user", "content": user_msg})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()

        # Обновляем историю
        USER_STATES[user_phone] = {
            **USER_STATES.get(user_phone, {}),
            "last_message": user_msg,
            "history": history[-4:] + [{"user": user_msg, "bot": reply}]
        }

        return reply
    except Exception as e:
        print(f"❌ GPT ошибка: {e}")
        return "Қателік орын алды / Произошла ошибка. Повторите позже."

# Простая проверка на приветствие
def is_greeting(text):
    text = text.lower()
    greetings = ["сәлем", "привет", "здравствуйте", "салам", "добрый день", "добрый вечер", "hi", "hello"]
    return any(greet in text for greet in greetings)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if messages:
            msg = messages[0]
            user_msg = msg["text"]["body"]
            user_phone = msg["from"]

            print(f"💬 От {user_phone}: {user_msg}")

            if USER_STATES.get(user_phone, {}).get("last_message") == user_msg:
                print("⚠️ Повтор — пропускаем")
                return jsonify({"status": "duplicate"}), 200

            # FSM если приветствие или уже в FSM
            user_data = USER_STATES.get(user_phone, {})
            if is_greeting(user_msg) or user_data.get("step"):
                if not user_data.get("step"):
                    fsm_healvix_kz.init_state(user_phone)
                reply = fsm_healvix_kz.process_fsm(user_phone, user_msg)
                USER_STATES[user_phone]["last_message"] = user_msg
                send_whatsapp_message(user_phone, reply)

            else:
                # GPT
                reply = get_gpt_response(user_msg, user_phone)
                send_whatsapp_message(user_phone, reply)

    except Exception as e:
        print(f"❌ Ошибка обработки запроса: {e}")

    return jsonify({"status": "ok"}), 200

@app.route('/', methods=['GET'])
def home():
    return "Healvix бот активен!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
