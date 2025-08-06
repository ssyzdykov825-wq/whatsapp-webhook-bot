from flask import Flask, request
import requests
import threading

app = Flask(__name__)

# ✅ Используем Cloud API (НЕ on-premise)
WHATSAPP_API_URL = 'https://waba-v2.360dialog.io/v1/messages'

# ✅ Правильный заголовок — D360-API-KEY
HEADERS = {
    'D360-API-KEY': 'ASGoZdyRzzwoTVnk6Q1p4eRAAK',  # 🔁 Подставь свой API-ключ!
    'Content-Type': 'application/json'
}

# ✅ Асинхронная обработка сообщений
def handle_message(sender, text):
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
    except Exception as e:
        print("🚨 Ошибка при отправке:", str(e))


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    if not data:
        return "no data", 400

    if 'messages' in data:
        for message in data['messages']:
            if message.get('type') == 'text':
                sender = message['from']
                text = message['text']['body']

                # ✅ Запускаем обработку в фоновом потоке, чтобы не задерживать ответ
                threading.Thread(target=handle_message, args=(sender, text)).start()

            else:
                print("⚠️ Необрабатываемый тип сообщения:", message.get('type'))

    if 'statuses' in data:
        for status in data['statuses']:
            print("📦 Статус доставки:", status)

    # ✅ Немедленно возвращаем 200 OK (в течение <250 мс)
    return "ok", 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
