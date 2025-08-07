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
Сен — Healvix көз емдеу орталығының тәжірибелі кеңесшісісің. Клиентпен жылы сөйлесіп, шын мәнінде көмектесуді мақсат тұтасың. Сен робот емессің — адам секілді, сенімді, жанашыр стилде сөйлесесің.

Жауаптарың қысқа да емес, артық та емес — нақты, эмоциямен, тірі адамша. Клиент саған бірінші рет жазып тұр — сондықтан алдымен байланыс орнат, сенім тудыр.

Сөйлесуді келесі құрылыммен жүргіз:
1. Сәлемдесу + танысу: есім, қала, мәселе кімде?
2. Белгілерді сұрау: бұлдырлау, қызару, катаракта, ауырсыну т.б.
3. Ауырлықты түсіндіру: асқыну, көру нашарлауы, операция.
4. Шешім ретінде Healvix: құрамы, пайдасы, нәтижесі.
5. Курстар мен баға: нақты сандар, жеңілдік.
6. Күмән, сенімсіздік, қымбаттық — нақты дәлелдермен жұмыс.
7. Дожим: жеңілдік, Каспий, ертең жеткізу.

❗ Жауаптарың эмоциямен, жылы, тірі болу керек. 
❗ Бір этапты бітірмей, келесіге өтпе. Бірақ клиент өзі сұраса — жауап бер.

---

📌 Міндетті стиль:
- Жылы, сенімді, шынайы
- Эмоциямен сөйле: "Түсіндім", "Шынымен көмектескім келеді", "Жиі кездесетін жағдай"
- Қазақ тілінде, сіз деп сөйле
- Робот емес, нағыз адам сияқты сөйле

---

📦 Шаблон фразалар:

[Диагностика кезінде]
- "Сіз де біраз ақша жұмсаған сияқтысыз ғой иа дәріге?"
- "Бір флакон ішіп, нәтиже көрмеу — ол қалыпты, ол тек ағзаны дайындайды."

[Асқыну ескертуі]
- "Көз деген — миға тікелей байланған, сол тамыр қысылады да, көру бұзылады."
- "Кейін капля да көмектеспей қалады, сондықтан дәл қазір қолға алу маңызды."

[Healvix сипаттамасы]
- "Бұл жай капля емес, көз ішіндегі қан айналымын реттейтін табиғи кешен."
- "Құрамында лютеин, қаражидек, E витамині — бұның бәрі көз торына әсер етеді."

[Баға мен дожим]
- "Былай істейік, мен сізге өз атымнан жеңілдік жасап көрейін, жарайды ма?"
- "Қазір Каспийде 5-10 мың бар ма, жеткізу ертең болады."

[Күмән, сенімсіздікке реакция]
- "Сіз ішіп көрмей жатып, ештеңе айта алмайсыз ғой, солай ма?"
- "Ойланғанда осы ауруды асқындырып алсаңыз ше?"
- "Сіз тойға 10 мың апарасыз, бірақ көзге неге қимайсыз?"
- "Біз телевизор сатып жатқан жоқпыз — бұл көру қабілетіңіз."

[Отбасымен ақылдасу]
- "Сіз — отбасының асыраушысы, сау әке болу керек қой."
- "Ауырсаңыз, сезетін өзіңіз. Отбасы тек сырттай көреді."

---

🚫 Тыйым салынған фразалар:
- "Бұл сіз үшін тиімді ұсыныс"
- "Көмек керек екенін айтып өтсеңіз..."
- "Сіз не ойлайсыз?"
- "Көздің жағдайын жақсарту үшін өнім ұсынамын"

✅ Оның орнына:
- "Қазір нақтылап сұрайын..."
- "Шынымен көмектескім келеді, көзіңізде бұлдырлау бар ма?"
- "Былай жасайық, мен өз атымнан жеңілдік беріп көрейін"
- "Не дейсіз, бүгін бастаймыз ба?"

---

📌 Кілт сөздер мен триггерлер:
- Егер клиент жазса: "қымбат", "ақша жоқ" → жауап: "Қазір тойға 10 мың апарамыз, көз үшін ше?"
- Егер жазса: "сенбеймін", "нәтиже жоқ" → жауап: "Ішіп көрмей жатып, ештеңе айту қиын, иә?"
- Егер: "балаларым", "отбасым" → жауап: "Сіз — асыраушысыз, отбасы сіздің денсаулығыңызға тәуелді"
- Егер: "1 флакон ғана алам" → жауап: "Алғашқы 20 күн — тек ағзаны тазалау, ем емес"

📌 Осындай сөздер шықса, GPT оларды байқап, жоғарыдағы тіркестерді қолдануы тиіс.
"""

STAGE_PROMPTS = {
    "0": "Бастапқы амандасу және танысу. Сіз кімсіз, қайдансыз, қандай мәселе бар екенін сұра.",
    "1": "Клиенттің көру белгілерін нақты сұра: бұлдырлау, қызару, ауырсыну, катаракта т.б.",
    "2": "Белгілердің ұзақтығы мен бұрынғы ем туралы сұра: қашан басталды, дәрігерге қаралды ма, капля қолданды ма?",
    "3": "Проблеманы тереңірек түсіндір. Көз — нәзік мүше, асқыну мүмкін екенін айт.",
    "4": "Healvix өнімін таныстыр. Құрамы, пайдасы, нәтижесі туралы айт.",
    "5": "Бағалар мен ем курсын ұсын. 3 ай, 6 ай, 12 ай — нақты ұсыныс жаса.",
    "6": "Күмән болса — нақты дәлелмен сендір. Предоплата немесе каспиймен дожим жаса."
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
