from flask import Flask, request
import requests
import threading
import sys

app = Flask(__name__)

# ✅ Cloud API URL (360dialog)
WHATSAPP_API_URL = 'https://waba-v2.360dialog.io/v1/messages'

# ✅ Подставь свой API-ключ
HEADERS = {
    'D360-API-KEY': 'ASGoZdyRzzwoTVnk6Q1p4eRAAK',  # ← твой ключ
    'Content-Type': 'application/json'
}

# ✅ Асинхронная отправка
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
    except Exception as e:
        print("🚨 Ошибка при отправке:", str(e))

    sys.stdout.flush()

# ✅ Вебхук от WhatsApp
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
                    threading.Thread(target=handle_message, args=(sender, text)).start()
    except Exception as e:
        print("⚠️ Ошибка обработки JSON:", str(e))

    return "ok", 200
