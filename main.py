# 💡 Расширенная версия GPT-бота Healvix с поддержкой этапов скрипта

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

USER_STATE = {}

# Обновленный SALES_SCRIPT_PROMPT с живым стилем и шаблон-фразами
SALES_SCRIPT_PROMPT = """
(весь предыдущий prompt здесь вставлен — см. предыдущий шаг)
"""

STAGE_PROMPTS = {
    "0": "Сәлеметсіз бе! Сізге Healvix көз емдеу орталығынан хабарласып отырмын. Қалыңыз қалай? Сізде көрумен байланысты мәселе бар ма, өзіңізде ме әлде жақыныңызда ма?",
    "1": "Көзіңізде қандай белгілер мазалайды? Бұлдыр көру, қызару, жылау немесе катаракта сияқты мәселелер бар ма?",
    "2": "Сол белгілер қанша уақыт болды? Соңғы рет дәрігерге қаралдыңыз ба? Каплялар, линза қолдандыңыз ба?",
    "3": "Сол үшін біз ұсынатын Healvix өнімі — 100% табиғи, құрамында қаражидек, лютеин, Е витамині бар. Көз тамырларын күшейтеді, көруді жақсартады.",
    "4": "Бізде бірнеше ем курсы бар. Мысалы, 3 ай — 85 000 тг, 6 ай — 180 000 тг. Сізге қандай курс тиімді болады?",
    "5": "Көп клиент те сенімсіздікпен қарайды. Бірақ өніміміз сертификатталған, табиғи. Результат болмаса — ақшаны қайтарамыз.",
    "6": "Онда бүгін заказды тіркейік. Каспий нөміріңізді айтып жіберсеңіз, алдын ала төлеммен рәсімдейміз."
}

def split_message(text, max_length=1000):
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
        user_data = USER_STATE.get(user_phone, {})
        history = user_data.get("history", [])
        stage = user_data.get("stage", "0")

        prompt = SALES_SCRIPT_PROMPT + "\n\n" + STAGE_PROMPTS.get(stage, "")

        messages = [{"role": "system", "content": prompt}]
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

        next_stage = str(int(stage) + 1) if int(stage) < 6 else "6"

        USER_STATE[user_phone] = {
            "history": history[-5:] + [{"user": user_msg, "bot": reply}],
            "last_message": user_msg,
            "stage": next_stage
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
