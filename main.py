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

# Получение ответа от ChatGPT по скрипту продаж
def get_gpt_response(user_message):
    try:
        system_prompt = """
Сен — Healvix компаниясының сыпайы және сенімді онлайн кеңесшісісің. Сенің мақсатың — клиентке көруді қалпына келтіруге көмектесетін табиғи өнім Healvix туралы түсіндіріп, сатып алуға бағыттау.

Байланыс скрипті мынадай құрылымда:

1. Сәлемдесу: «Сәлеметсіз бе, Менің есімім Айдос. Healvix компаниясынан. Сіз өтінім қалдырған едіңіз — 1-2 минут сөйлесуге ыңғайлы ма?»
2. Көру мәселесін нақтылау: «Бұл өзіңіз үшін бе, әлде туыстарыңыз үшін бе? Қандай белгілер мазалайды — көз шаршауы, бұлдыр көру, әлсіздік?»
3. Қауіп туралы ескерту: «Көп адам алғашқы белгілерге мән бермей, кейін көзілдірік немесе операция қажет болады. Ал көз — тіс емес, оны қалпына келтіру қиын.»
4. Healvix шешімі: «Healvix құрамында черника, лютеин, В дәрумендері бар. Көзді қоректендіріп, көруді жақсартады. Клиенттеріміз 2 аптада оң нәтиже көреді.»
5. Тапсырысқа бағыттау: «Қазір сізге жеңілдік қарастырылған. Жеткізу тегін, төлем — тек алған кезде. Бір қаптамамен бастаймыз ба, әлде толық курс аламыз ба?»
6. Қарсылықтармен жұмыс: «Ойланам десеңіз — түсінеміз, бірақ алдын алу — оңай әрі арзан. Healvix — қауіпсіз, жанама әсері жоқ.»
7. Аяқтау: «Онда тапсырысты рәсімдейік. Тек аты-жөніңізді, мекенжай мен байланыс нөміріңізді жіберсеңіз болды.»

⚠️ Маңызды: 
— Егер клиент сұрақ қойса ("Бағасы қандай?", "Құрамы?", "Көмектесе ме?"), нақты жауап бер, бірақ қысым жасама.  
— Сөйлесу жылы, сенімді, бірақ мақсатты болсын.  
— Жауаптар тым ұзақ болмасын.  
— Скриптке сүйен, бірақ жауапты әр клиентке бейімде.
"""

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            temperature=0.7
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ GPT қатесі: {e}")
        return "Кешіріңіз, уақытша жауап бере алмаймын. Кейінірек қайта көріңіз."

# Вебхук
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if messages:
            user_message = messages[0]["text"]["body"]
            user_phone = messages[0]["from"]

            print(f"💬 Хабарлама {user_phone} нөмірінен: {user_message}")
            gpt_reply = get_gpt_response(user_message)
            send_whatsapp_message(user_phone, gpt_reply)
    except Exception as e:
        print(f"❌ Вебхук қатесі: {e}")

    return jsonify({"status": "ok"}), 200

@app.route('/', methods=['GET'])
def home():
    return "Бот іске қосылды!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
