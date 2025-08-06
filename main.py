from flask import Flask, request
import requests
import threading
import sys

app = Flask(__app__)

# ✅ Cloud API URL (через 360dialog)
WHATSAPP_API_URL = 'https://waba-v2.360dialog.io/v1/messages'

# ✅ Подставь свой API-ключ
# ВАЖНО: Убедитесь, что это ваш АКТИВНЫЙ API-ключ от 360dialog.
# Неверный или просроченный ключ - частая причина ошибки 400.
HEADERS = {
    'D360-API-KEY': 'ASGoZdyRzzwoTVnk6Q1p4eRAAK',  # ← твой ключ
    'Content-Type': 'application/json'
}

# ✅ Асинхронная обработка сообщений
def handle_message(sender, text):
    print(f"🚀 Обрабатываю сообщение от {sender}: {text}")
    sys.stdout.flush()

    payload = {
        # "messaging_product": "whatsapp", # Это поле обычно не требуется при ОТПРАВКЕ сообщений в API
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
        # Проверяем структуру JSON перед доступом к элементам
        entry = data.get("entry", [])
        if not entry:
            print("⚠️ JSON не содержит 'entry' или он пуст.")
            return "invalid json structure", 400

        changes = entry[0].get("changes", [])
        if not changes:
            print("⚠️ JSON не содержит 'changes' или он пуст.")
            return "invalid json structure", 400

        value = changes[0].get("value", {})
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
    # Используйте порт 10000, как указано в вашем примере
    app.run(host='0.0.0.0', port=10000)
