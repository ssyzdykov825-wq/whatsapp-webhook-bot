import os
import requests
import threading
import sys
from flask import Flask, request

app = Flask(__name__)

# ✅ Получаем API-ключ из переменных окружения
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY")

# ✅ URL для Cloud API (через 360dialog)
WHATSAPP_API_URL = "https://waba-v2.360dialog.io/v1/messages"

# ✅ Заголовки с API-ключом
HEADERS = {
    "D360-API-KEY": WHATSAPP_API_KEY,
    "Content-Type": "application/json"
}

# ✅ Обработка входящих сообщений
def handle_message(sender, text):
    print(f"🚀 Обрабатываю сообщение от {sender}: {text}")
    sys.stdout.flush()

    payload = {
        "messaging_product": "whatsapp",  # ← ОБЯЗАТЕЛЬНО!
        "recipient_type": "individual",
        "to": sender,
        "type": "text",
        "text": {
            "body": f"Вы сказали: {text}"
        }
    }

    print("📦 Payload:", payload)

    try:
        response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
        print("📤 Ответ от сервера:", response.status_code, response.text)

        if response.status_code != 200:
            print("❌ Ошибка отправки:", response.status_code, response.text)
        else:
            print("✅ Успешно отправлено!")
        sys.stdout.flush()
    except Exception as e:
        print("🚨 Ошибка при отправке:", str(e))
        sys.stdout.flush()

# ✅ Обработка вебхука
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

# ✅ Запуск локально или на сервере
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
