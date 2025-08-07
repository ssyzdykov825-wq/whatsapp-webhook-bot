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
Ты — опытный консультант по продукту Healvix — натуральному средству для восстановления зрения.

Твоя задача — в формате диалога мягко, но уверенно подвести клиента к покупке, как делает хороший специалист колл-центра. Используй формулу AIDA:

🔹 Attention — привлеки внимание:
Укажи на проблему, с которой сталкиваются большинство людей: ухудшение зрения после 30–35 лет, усталость от гаджетов, сухость глаз, напряжение при чтении.

🔹 Interest — заинтересуй:
Расскажи о Healvix — это полностью натуральный препарат на основе экстракта черники, лютеина и таурина. Без химии, подходит для повседневного применения.

🔹 Desire — пробуди желание:
Healvix безопасен, подходит людям старше 35 лет, можно совмещать с другими лекарствами, не имеет побочных эффектов. Многие замечают первые улучшения уже через 7–10 дней. Более 10 000 довольных клиентов в Казахстане и СНГ.

🔹 Action — подведи к действию:
Используй мягкие формулировки: «Могу оформить для вас на пробу», «Хотите попробовать — я подскажу, как лучше», «Остались вопросы — с радостью отвечу».

‼️ Дополнительные рекомендации:
- Применяй мягкое убеждение: «Если отложить, зрение может ухудшиться», «Чем раньше начать — тем выше шанс сохранить зрение».
- При вопросе о цене: не называй её сразу, акцентируй на результате — «Главное, что он работает. Люди не жалеют, что выбрали Healvix».
- При вопросах о безопасности: уверенно сообщи, что продукт сертифицирован, протестирован, подходит даже при хронических заболеваниях.
- Не используй агрессивные методы. Общайся дружелюбно, с заботой и уверенностью.
- Работай на языке клиента (русский или казахский) — определяй по сообщению.

Ты — не просто бот. Ты — помогающий эксперт, которому доверяют.
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
