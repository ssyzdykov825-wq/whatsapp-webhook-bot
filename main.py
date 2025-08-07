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

# Хранилище диалогов
USER_STATES = {}

# Базовый system-промпт
BASE_PROMPT = """
Ты умный консультант по продукту Healvix — натуральное средство для восстановления зрения.
Работай как опытный менеджер из колл-центра, следуя структуре AIDA:

1. Attention — Зацепи: зрение ухудшается после 35 лет, особенно с гаджетами.
2. Interest — Расскажи: Healvix — черника, лютеин, таурин. Натуральный состав.
3. Desire — Объясни: безопасен, без побочек, можно с любыми лекарствами.
4. Action — Мягко предложи: "Могу рассказать подробнее", "Хотите попробовать?"

‼️Работай на языке клиента (русский или казахский).
‼️Если есть возражения — отвечай спокойно: про цену, безопасность, эффективность.
‼️Если клиент не готов — оставь открытый вопрос, не дави.

Пример возражений:
- Это безопасно? → Да, без побочных, можно даже с лекарствами.
- А вдруг не поможет? → Уже помог более 10 000+ людям, эффект через 1 курс.
- А это не реклама? → Мы работаем официально, с отзывами и сертификацией.

Не используй кнопки. Общайся живо, как человек. Веди к диалогу, но не навязывайся.
"""

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
        # Получаем историю (если есть)
        history = USER_STATES.get(user_phone, {}).get("history", [])

        # Формируем сообщения для GPT
        messages = [{"role": "system", "content": BASE_PROMPT}]
        for h in history:
            messages.append({"role": "user", "content": h["user"]})
            messages.append({"role": "assistant", "content": h["bot"]})
        messages.append({"role": "user", "content": user_msg})

        # GPT-4o ответ
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()

        # Обновляем историю
        USER_STATES[user_phone] = {
            "last_message": user_msg,
            "history": history[-4:] + [{"user": user_msg, "bot": reply}]
        }

        return reply
    except Exception as e:
        print(f"❌ GPT ошибка: {e}")
        return "Қателік орын алды / Произошла ошибка. Повторите позже."

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if messages:
            msg = messages[0]
            user_msg = msg["text"]["body"]
            user_phone = msg["from"]

            print(f"💬 От {user_phone}: {user_msg}")

            # Игнор если дублируется
            if USER_STATES.get(user_phone, {}).get("last_message") == user_msg:
                print("⚠️ Повтор — пропускаем")
                return jsonify({"status": "duplicate"}), 200

            # GPT ответ
            reply = get_gpt_response(user_msg, user_phone)
            send_whatsapp_message(user_phone, reply)

            # 🔗 CRM интеграция (отправка данных)
            # crm_payload = {"phone": user_phone, "text": user_msg}
            # requests.post("https://ваш_crm_webhook_url", json=crm_payload)

    except Exception as e:
        print(f"❌ Ошибка обработки запроса: {e}")

    return jsonify({"status": "ok"}), 200

@app.route('/', methods=['GET'])
def home():
    return "Healvix бот активен!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
