from flask import Flask, request
import requests
import threading
import sys

app = Flask(__name__)

# ✅ Cloud API URL от 360dialog
WHATSAPP_API_URL = 'https://waba-v2.360dialog.io/v1/messages'

# ✅ API-ключ 360dialog
HEADERS = {
    'D360-API-KEY': 'ASGoZdyRzzwoTVnk6Q1p4eRAAK',  # <-- свой ключ
    'Content-Type': 'application/json'
}

# ✅ Асинхронная отправка ответа
def handle_message(sender, text):
    print(f"🚀 Обрабатываю сообщение от {sender}: {text}")
    sys.stdout.flush()

    payload = {
        "messaging_product": "whatsapp",
        "to": sender,
        "type": "text",
        "text": {
            "preview_url": False,
            "body": f"Вы сказали: {text}"
        }
    }

    try:
        response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
        print("📤 Ответ от API:", response.status_code, response.text)
        sys.stdout.flush()
    except Exception as e:
        print("🚨 Ошибка при отправке:", str(e))
        sys.stdout.flush()

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)
    sys.stdout.flush()

    if not data:
        return "no data", 400

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
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


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
