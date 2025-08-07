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

# Храним данные по пользователям в памяти
USER_STATE = {}

# Скрипт как system_prompt
SALES_SCRIPT_PROMPT = """
Сен Healvix өнімін сататын кәсіби кеңесшісің. Клиентпен жылы, сенімді және анық сөйлейсің.
Мақсатың — клиентке көзге арналған табиғи кешеннің маңыздылығын түсіндіріп, сатуға жеткізу.

Мына құрылымды ұстан:
1. Сәлемдесу және кім екеніңді таныстыру.
2. Мәселені нақтылау ("қандай белгілер мазалайды?").
3. Қауіптерді түсіндіру ("көру қабілетінің нашарлауы", "операция", т.б.).
4. Healvix шешім ретінде ұсыну (құрамы, әсері, нәтижелері).
5. Тапсырысқа бағыттау (жеңілдік, жеткізу, төлем).
6. Күмән туындаса — сенімді түрде жауап беру.
7. Тапсырысты рәсімдеп, байланыс мәліметін сұра.

❗Егер клиент қысқа жауап берсе, нақтылап сұра.  
❗Жауап тым ұзақ болса — бөле отырып 2–3 хабарламаға жаз.  
❗Сұхбатты біртіндеп жүргіз, скрипттің барлық кезеңдерінен өткізуге тырыс.
"""

def split_message(text, max_length=1000):
    """Делит сообщение на части, если слишком длинное."""
    parts = []
    while len(text) > max_length:
        split_index = text[:max_length].rfind(". ")
        if split_index == -1:
            split_index = max_length
        parts.append(text[:split_index+1].strip())
        text = text[split_index+1:].strip()
    if text:
        parts.append(text)
    return parts

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
        history = USER_STATE.get(user_phone, {}).get("history", [])
        messages = [{"role": "system", "content": SALES_SCRIPT_PROMPT}]
        for item in history:
            messages.append({"role": "user", "content": item["user"]})
            messages.append({"role": "assistant", "content": item["bot"]})
        messages.append({"role": "user", "content": user_msg})

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()

        # Обновляем историю
        USER_STATE[user_phone] = {
            "history": history[-5:] + [{"user": user_msg, "bot": reply}],
            "last_message": user_msg
        }

        return reply
    except Exception as e:
        print(f"❌ GPT қатесі: {e}")
        return "Кешіріңіз, қазір жауап бере алмаймын. Кейінірек көріңіз."

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Келген JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if messages:
            msg = messages[0]
            user_phone = msg["from"]
            user_msg = msg["text"]["body"]

            print(f"💬 {user_phone}: {user_msg}")

            # Повтор — пропускаем
            if USER_STATE.get(user_phone, {}).get("last_message") == user_msg:
                print("⚠️ Қайталау — өткізіп жібереміз")
                return jsonify({"status": "duplicate"}), 200

            reply = get_gpt_response(user_msg, user_phone)
            for part in split_message(reply):
                send_whatsapp_message(user_phone, part)

    except Exception as e:
        print(f"❌ Обработка қатесі: {e}")

    return jsonify({"status": "ok"}), 200

@app.route('/', methods=['GET'])
def home():
    return "Healvix бот іске қосылды!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
