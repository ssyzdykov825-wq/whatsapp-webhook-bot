import os
import requests
import openai
from flask import Flask, request, jsonify

# Инициализация Flask
app = Flask(__name__)

# Установка API ключа OpenAI
openai.api_key = os.environ.get("OPENAI_API_KEY")

# Настройки 360dialog
WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY")

HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

# Хранение диалогов по пользователям
user_histories = {}

# Отправка сообщения в WhatsApp
def send_whatsapp_message(recipient_phone, message_text):
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": message_text}
    }
    response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
    print(f"📤 Ответ от сервера: {response.status_code} {response.text}")
    return response

# Получение ответа от GPT
def get_gpt_response(user_phone, user_message):
    # Инициализируем историю пользователя, если её ещё нет
    if user_phone not in user_histories:
        user_histories[user_phone] = []

    # История диалога
    history = user_histories[user_phone]

    # Системная инструкция с пошаговым скриптом и свободой
    system_prompt = (
        "Сен Healvix компаниясының маманысың. Сенің мақсатың — жылы түрде көзге арналған табиғи кешенді ұсыну. "
        "Төмендегі скриптті қолдан, бірақ жауапты адамға бейімде. Скрипт қадамдары:\n"
        "1. Сәлемдесу: «Сәлеметсіз бе, [аты]? Мен Healvix компаниясынан Айдоспын. Сіз өтінім қалдырған едіңіз — 1-2 минут сөйлесуге ыңғайлы ма?»\n"
        "2. Мәселені анықтау\n3. Қауіп туралы ескерту\n4. Шешім ретінде Healvix ұсыну\n"
        "5. Сатуға шақыру\n6. Күмәндарға жұмыс істеу\n7. Тапсырыс қабылдау\n\n"
        "Егер клиент нақты сұрақ қойса (құрамы, тиімділігі, баға), оған жеке жауап бер. "
        "Бірақ негізгі мақсат — скрипт бойынша клиентті тапсырысқа бағыттау. "
        "Сөйлесу стилі — жылы, сенімді, қысқа. Сен сатушы емессің — сен көмектесуші мамансың."
    )

    # Формируем список сообщений для GPT
    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append({"role": "user", "content": h["user"]})
        messages.append({"role": "assistant", "content": h["bot"]})

    # Добавим последнее сообщение
    messages.append({"role": "user", "content": user_message})

    # Запрос в OpenAI
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response['choices'][0]['message']['content'].strip()

        # Обновляем историю
        user_histories[user_phone].append({
            "user": user_message,
            "bot": reply
        })

        return reply
    except Exception as e:
        print(f"❌ GPT қатесі: {e}")
        return "Кешіріңіз, қазір жауап бере алмаймын. Кейінірек қайталап көріңіз."

# Обработка входящих сообщений
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if messages:
            user_message = messages[0]["text"]["body"]
            user_phone = messages[0]["from"]

            print(f"💬 {user_phone}: {user_message}")

            # GPT-ответ
            gpt_reply = get_gpt_response(user_phone, user_message)

            # Отправляем в WhatsApp
            send_whatsapp_message(user_phone, gpt_reply)
    except Exception as e:
        print(f"❌ Вебхук қатесі: {e}")

    return jsonify({"status": "ok"}), 200

# Проверка доступности сервера
@app.route('/', methods=['GET'])
def home():
    return "Healvix бот іске қосылды!", 200

# Локальный запуск
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
