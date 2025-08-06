from flask import Flask, request
import requests
import threading
import sys
import os
from dotenv import load_dotenv

# Загрузка переменных из .env
load_dotenv()

app = Flask(__name__)

# 📡 URL 360dialog API
WHATSAPP_API_URL = 'https://waba-v2.360dialog.io/v1/messages'

# 🔐 API-ключ из .env
D360_API_KEY = os.getenv("D360_API_KEY")

# Заголовки запроса
HEADERS = {
    'D360-API-KEY': D360_API_KEY,
    'Content-Type': 'application/json'
}

# ✅ Функция обработки и ответа на сообщение
def handle_message(sender, text):
    print(f"🚀 Обрабатываю сообщение от {sender}: {text}")
    sys.stdout.flush()

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": sender,
        "type": "text",
        "text": {
            "body": f"Вы сказали: {text}"
        }
    }

    try:
        response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
        if response.status_code != 200:
            print("❌ Ошибка отправки:", response.status_code, response.text)
        else:
            print("📤 Успешно отправлено:", response.status_code)
        sys.stdout.flush()
    except Exception as e:
        print("🚨 Ошибка при отправке:", str(e))
        sys.stdout.flush()


# 📥 Webhook-обработчик входящих сообщений
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)
    sys.stdout.flush()

    if not data:
        return "no data", 400

    try:
        for change in data.get("entry", [])[0].get("changes", []):
            value = change.get("value", {})
            messages = value.get("messages", [])
            for message in messages:
                if message.get("type") == "text":
                    sender = message["from"]
                    text = message["text"]["body"]
                    print(f"💬 Получено сообщение от {sender}: {text}")
                    sys.stdout.flush()
                    threading.Thread(target=handle_message, args=(sender, text)).start()
    except Exception as e:
        print("⚠️ Ошибка обработки JSON:", str(e))
        sys.stdout.flush()

    return "ok", 200


# 🏁 Точка входа (если запускаешь локально)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
