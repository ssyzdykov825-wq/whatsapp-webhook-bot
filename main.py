from flask import Flask, request
import requests
import os

app = Flask(__name__)

WHATSAPP_API_URL = 'https://waba.360dialog.io/v1/messages'
HEADERS = {
    'D-API-KEY': os.environ.get('ASGoZdyRzzwoTVnk6Q1p4eRAAK'),  # Подставляется из Render Dashboard
    'Content-Type': 'application/json'
}

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 JSON:", data)

    if not data:
        print("❌ Пустой JSON")
        return "no data", 400

    try:
        if 'messages' in data:
            for message in data['messages']:
                if message.get('type') == 'text' and 'text' in message:
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

    except Exception as e:
        print("💥 Ошибка обработки:", str(e))

    return "ok", 200


@app.route('/', methods=['GET'])
def health():
    return "✅ WhatsApp бот работает!", 200


# Render запускает сам, но можно оставить на всякий случай
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
