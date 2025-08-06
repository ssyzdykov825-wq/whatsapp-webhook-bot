from flask import Flask, request
import requests
import threading
import sys

app = Flask(__name__)

# ✅ URL Cloud API 360dialog
WHATSAPP_API_URL = 'https://waba-v2.360dialog.io/v1/messages'

# ✅ Укажи свой API-ключ от 360dialog
HEADERS = {
    'D360-API-KEY': 'ASGoZdyRzzwoTVnk6Q1p4eRAAK',  # ⬅️ Замени на свой, если надо
    'Content-Type': 'application/json'
}

# ✅ Асинхронная отправка сообщения
def handle_message(sender, text):
    print(f"🚀 Обрабатываю сообщение от {sender}: {text}")
    sys.stdout.flush()

    payload = {
        'recipient_type': 'individual',  # ✅ обязательно!
        'to': sender,
        'type': 'text',
        'text': {
            'body': f"Вы сказали: {text}"
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

# ✅ Обработка входящего вебхука
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

                # Сообщение от пользователя
                if "messages" in value:
                    for message in value["messages"]:
                        if message.get("type") == "text":
                            sender = message["from"]
                            text = message["text"]["body"]
                            print(f"💬 Получено сообщение от {sender}: {text}")
                            sys.stdout.flush()
                            threading.Thread(target=handle_message, args=(sender, text)).start()
                        else:
                            print("⚠️ Необрабатываемый тип сообщения:", message.get("type"))
                            sys.stdout.flush()

                # Статусы доставки
                if "statuses" in value:
                    for status in value["statuses"]:
                        print("📦 Статус доставки:", status)
                        sys.stdout.flush()

                # Эхо-сообщения (ваши же ответы)
                if "message_echoes" in value:
                    print("↩️ Эхо-сообщение от системы (можно игнорировать)")
                    sys.stdout.flush()

    except Exception as e:
        print("❌ Ошибка при разборе вебхука:", str(e))
        sys.stdout.flush()

    return "ok", 200

# ✅ Запуск сервера
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
