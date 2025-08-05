from flask import Flask, request
import requests
import json

app = Flask(__name__)

WHATSAPP_API_URL = 'https://waba.360dialog.io/v1/messages'
HEADERS = {
    'D-API-KEY': 'ASGoZdyRzzwoTVnk6Q1p4eRAAK',  # <== Подставь сюда настоящий ключ!
    'Content-Type': 'application/json'
}

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 JSON:", data)

    if not data:
        print("❌ Пустой JSON")
        return "no data", 400

    if 'messages' in data:
        for message in data['messages']:
            if message.get('type') == 'text':
                text = message['text']['body']
                sender = message['from']

                payload = {
                    'messaging_product': 'whatsapp',
                    'to': sender,
                    'type': 'text',
                    'text': {
                        'body': f"Вы сказали: {text}"
                    }
                }

                response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)

                if response.status_code != 200:
                    print("❌ Ошибка отправки:", response.status_code, response.text)
                else:
                    print("📤 Успешно отправлено:", response.status_code)

            else:
                print("⚠️ Необрабатываемый тип сообщения:", message.get('type'))

    if 'statuses' in data:
        for status in data['statuses']:
            print("📦 Статус доставки:", status)

    return "ok", 200
