from flask import Flask, request
import requests
import threading
import sys

app = Flask(__name__)

# ✅ Cloud API URL от 360dialog
WHATSAPP_API_URL = 'https://waba-v2.360dialog.io/v1/messages'

# ✅ Твой API-ключ от 360dialog (замени на свой!)
HEADERS = {
    'D360-API-KEY': 'ASGoZdyRzzwoTVnk6Q1p4eRAAK',  # <-- вставь свой!
    'Content-Type': 'application/json'
}


# ✅ Асинхронная отправка сообщения
def handle_message(sender, text):
    print(f"🚀 Обрабатываю сообщение от {sender}: {text}")
    sys.stdout.flush()

    payload = {
        'messaging_product': 'whatsapp',
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


# ✅ Обработка входящих вебхуков от 360dialog
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)
    sys.stdout.flush()

    if not data or 'entry' not in data:
        print("⛔ Пустой или неверный JSON")
        return "no data", 400

    for entry in data['entry']:
        for change in entry.get('changes', []):
            value = change.get('value', {})

            # ✅ Обработка сообщений
            if 'messages' in value:
                for message in value['messages']:
                    if message.get('type') == 'text':
                        sender = message['from']
                        text = message['text']['body']
                        print(f"💬 Получено сообщение от {sender}: {text}")
                        sys.stdout.flush()

                        # Асинхронная отправка ответа
                        threading.Thread(target=handle_message, args=(sender, text)).start()
                    else:
                        print("⚠️ Тип сообщения не поддерживается:", message.get('type'))
                        sys.stdout.flush()

            # ✅ Обработка статусов доставки
            if 'statuses' in value:
                for status in value['statuses']:
                    print("📦 Статус доставки:", status)
                    sys.stdout.flush()

    # ⚡️ Возвращаем 200 сразу — важно для 360dialog!
    return "ok", 200


# ✅ Запуск сервера
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
