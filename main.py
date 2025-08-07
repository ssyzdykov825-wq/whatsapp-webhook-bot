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

# Состояние пользователя (этап скрипта)
user_states = {}

# Шаги скрипта продаж
sales_script = [
    "Сәлеметсіз бе! Мен Healvix компаниясынан Айдоспын. Сіз өтінім қалдырған едіңіз — 1-2 минут сөйлесуге ыңғайлы ма?",
    "Өтінімді өзіңіз үшін қалдырдыңыз ба, әлде жақындарыңызға ма? Қандай белгілер мазалайды — көздің шаршауы, бұлыңғыр көру, көру қабілетінің төмендеуі?",
    "Иә, экран, стресс, жас ерекшеліктері — бұлардың бәрі көзге ауырлық түсіреді. Бірақ бастапқы белгілерді елемеу — кейін үлкен проблемаға айналуы мүмкін.",
    "Көру қабілетін жоғалту — жай ғана ыңғайсыздық емес. Бұл — кітап оқи алмау, көлік жүргізе алмау, жақындарыңызды анық көре алмау. Сіз дұрыс қадам жасадыңыз.",
    "Healvix — бұл көзді табиғи жолмен қорғайтын және қалпына келтіретін кешен. Құрамында черника, лютеин, В дәрумендері бар.",
    "Қазір сіздің өтініміңіз бойынша арнайы жеңілдік бар. Жеткізу тегін, төлем — алған кезде. Қалайсыз: бір айлық курс па, әлде толық нәтиже үшін 2–3 айға аламыз ба?",
    "Онда келістік, тапсырысты рәсімдейік. Аты-жөніңіз, мекенжай және байланыс нөміріңізді жіберсеңіз болды. Курьер жеткізеді, төлем — алған кезде.",
    "Тапсырыс қабылданды! Жақын күндері сізбен байланысамыз. Көру қабілетіңізге бүгіннен бастап қамқорлық жасағаныңыз дұрыс шешім. Күніңіз сәтті өтсін!"
]

# Ответы на возражения
objection_responses = {
    "қымбат": "Түсінемін, бірақ көру — кейінге қалдыруға болмайтын нәрсе. Қазір бір қаптамамен бастап көруге болады. Тәуекел жоқ.",
    "ойланам": "Әрине. Бірақ дәл қазір алдын алу — ең тиімді жол. Кейін көруді қалпына келтіру әлдеқайда қиын.",
    "онша жаман емес": "Дәл осындай кезең — алдын алуға таптырмас уақыт. Healvix — бұл көзге арналған күнделікті күтім сияқты.",
    "сенбеймін": "Клиенттердің 80%-дан астамы көзінің демалып, көруінің жақсарғанын байқап отыр. Healvix — бұл нақты нәтиже үшін."
}

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

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if messages:
            user_message = messages[0]["text"]["body"].lower()
            user_phone = messages[0]["from"]
            print(f"💬 {user_phone}: {user_message}")

            # Проверка на возражения
            for keyword, response in objection_responses.items():
                if keyword in user_message:
                    send_whatsapp_message(user_phone, response)
                    return jsonify({"status": "ok"}), 200

            # Определение текущего шага
            step = user_states.get(user_phone, 0)

            if step < len(sales_script):
                send_whatsapp_message(user_phone, sales_script[step])
                user_states[user_phone] = step + 1
            else:
                send_whatsapp_message(user_phone, "Қосымша сұрақтарыңыз болса, жазыңыз!")
    except Exception as e:
        print(f"❌ GPT қатесі: {e}")
        send_whatsapp_message(user_phone, "Кешіріңіз, уақытша қате шықты. Кейінірек қайталап көріңіз.")

    return jsonify({"status": "ok"}), 200

@app.route('/', methods=['GET'])
def home():
    return "Бот іске қосылды!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
