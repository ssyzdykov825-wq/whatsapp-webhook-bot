import os
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

# Инициализация Flask и OpenAI клиента
app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Настройки 360dialog
WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY")

# Хедеры для запроса в 360dialog
HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

# Отправка сообщения в WhatsApp
def send_whatsapp_message(recipient_phone, message_text):
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {
            "body": message_text
        }
    }
    response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
    print(f"📤 Ответ от сервера: {response.status_code} {response.text}")
    return response

# Получение ответа от ChatGPT
def get_gpt_response(user_message):
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Ты эксперт по улучшению зрения. Ты помогаешь людям после неудачного звонка узнать о натуральном средстве Healvix, которое восстанавливает зрение. Продукт безопасен, без побочек, подходит людям 35+. В основе — экстракт черники, лютеин, таурин. Можно принимать с любыми лекарствами. Не вызывает зависимости."},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()
        return reply
    except Exception as e:
        print(f"❌ GPT ошибка: {e}")
        return "Произошла ошибка. Попробуйте позже."

# Вебхук для приёма сообщений от WhatsApp
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if messages:
            user_message = messages[0]["text"]["body"]
            user_phone = messages[0]["from"]

            print(f"💬 Получено сообщение от {user_phone}: {user_message}")
            print(f"🚀 Обрабатываю сообщение от {user_phone}: {user_message}")

            gpt_reply = get_gpt_response(user_message)
            send_whatsapp_message(user_phone, gpt_reply)
    except Exception as e:
        print(f"❌ Ошибка обработки входящего запроса: {e}")

    return jsonify({"status": "ok"}), 200

# Проверка доступности сервера
@app.route('/', methods=['GET'])
def home():
    return "Бот запущен!", 200

# Для запуска в Render
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
