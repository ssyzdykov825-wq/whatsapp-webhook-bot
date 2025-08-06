from flask import Flask, request
import requests
import threading
import sys

app = Flask(__name__)

# ✅ Cloud API от 360dialog
WHATSAPP_API_URL = "https://api.360dialog.io/v1/messages"

# ✅ Ключ из 360dialog
D360_API_KEY = "ASGoZdyRzzwoTVnk6Q1p4eRAAK"

HEADERS = {
    "D360-API-KEY": D360_API_KEY,
    "Content-Type": "application/json"
}


def handle_message(sender, text):
    print(f"🚀 Обрабатываю сообщение от {sender}: {text}")
    sys.stdout.flush()

    # Подготовка ответа
    payload = {
        "to": sender,
        "type": "text",
        "text": {
            "body": f"Вы сказали: {text}"
        }
    }

    try:
        response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
        print("📤 Ответ от API:", response.status_code, response.text)
        sys.stdout.flush()
    except Exception as e:
        print("❌ Ошибка отправки:", str(e))
        sys.stdout.flush()


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)
    sys.stdout.flush()

    # 🔁 Сразу отправляем 200 OK — это важно!
    threading.Thread(target=process_webhook, args=(data,)).start()
    return "ok", 200


def process_webhook(data):
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
                        handle_message(sender, text)
    except Exception as e:
        print("⚠️ Ошибка обработки JSON:", str(e))
        sys.stdout.flush()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
