from flask import Flask, request
import requests
import threading
import sys

app = Flask(__name__)

WHATSAPP_API_URL = 'https://waba-v2.360dialog.io/v1/messages'

HEADERS = {
    'D360-API-KEY': 'ASGoZdyRzzwoTVnk6Q1p4eRAAK',  # 🔁 Подставь свой ключ!
    'Content-Type': 'application/json'
}

def handle_message(sender, text):
    print("🔧 Старт обработки сообщения")
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
        print("📤 Ответ от WhatsApp API:", response.status_code, response.text)
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

    if 'messages' in data:
        for message in data['messages']:
            if message.get('type') == 'text':
                sender = message['from']
                text = message['text']['body']
                print(f"💬 Сообщение от {sender}: {text}")
                sys.stdout.flush()

                threading.Thread(target=handle_message, args=(sender, text)).start()
            else:
                print("⚠️ Необрабатываемый тип:", message.get('type'))
                sys.stdout.flush()

    if 'statuses' in data:
        for status in data['statuses']:
            print("📦 Статус доставки:", status)
            sys.stdout.flush()

    if 'messages' not in data and 'statuses' not in data:
        print("🤷‍♂️ Ничего полезного не пришло:", data)
        sys.stdout.flush()

    return "ok", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
