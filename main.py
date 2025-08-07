import os
import requests
from flask import Flask, request, jsonify
from openai import OpenAI

app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY")

HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

# Простейшее хранилище состояний (вместо базы)
USER_STATES = {}

# AIDA промпт
BASE_PROMPT = (
    "Ты эксперт по улучшению зрения. Следуй модели AIDA:\n"
    "1. Attention: заинтересуй пользователя (зрение ухудшается после 35 лет).\n"
    "2. Interest: расскажи про Healvix (черника, лютеин, таурин).\n"
    "3. Desire: объясни, почему безопасно, нет побочек, можно с лекарствами.\n"
    "4. Action: мягко предложи купить или узнать подробнее.\n"
    "Работай и на русском и на казахском, определяя язык по сообщению пользователя.\n"
    "Работай с возражениями. Не будь навязчивым, но веди к покупке.\n"
)

def send_whatsapp_message(phone, message):
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }
    response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
    print(f"📤 Ответ от сервера: {response.status_code} {response.text}")
    return response

def get_gpt_response(user_msg, user_phone):
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": BASE_PROMPT},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()
        
        # Обновим состояние диалога
        USER_STATES[user_phone] = {"last_message": user_msg}
        
        return reply
    except Exception as e:
        print(f"❌ GPT ошибка: {e}")
        return "Извините, произошла ошибка. Повторите позже."

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if messages:
            message = messages[0]
            user_msg = message["text"]["body"]
            user_phone = message["from"]

            print(f"💬 Получено сообщение от {user_phone}: {user_msg}")

            # Проверка — если сообщение такое же, не отвечаем снова
            if USER_STATES.get(user_phone, {}).get("last_message") == user_msg:
                print("⚠️ Повторное сообщение, пропускаем.")
                return jsonify({"status": "duplicate"}), 200

            reply = get_gpt_response(user_msg, user_phone)
            send_whatsapp_message(user_phone, reply)

            # TODO: сюда можно вставить интеграцию с CRM webhook

    except Exception as e:
        print(f"❌ Ошибка обработки входящего запроса: {e}")

    return jsonify({"status": "ok"}), 200

@app.route('/', methods=['GET'])
def home():
    return "Бот Healvix активен!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
