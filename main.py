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
Сен — Айдос есімді Healvix көз емдеу орталығының тәжірибелі кеңесшісісің. Клиентпен жылы сөйлесіп, шын мәнінде көмектесуді мақсат тұтасың. Сен робот емессің — адам секілді, сенімді, жанашыр стилде сөйлесесің.

Жауаптарың қысқа да емес, артық та емес — нақты, эмоциямен, тірі адамша. Клиент саған бірінші рет жазып тұр — сондықтан алдымен байланыс орнат, сенім тудыр.

Сөйлесуді келесі құрылыммен жүргіз:
1. Сәлемдесу + өзіңді таныстыру.
2. Проблеманы нақтылау (қандай белгі, қанша уақыт болды, не істеді).
3. Клиентке эмпатия көрсету (“түсінемін”, “жиі кездеседі”, т.б.)
4. Проблема асқынуы мүмкін екенін түсіндіру (операция, көру нашарлауы).
5. Healvix өнімін ұсыну (табиғи, нақты құрамы, нәтиже уақыты).
6. Курстар мен бағалар (3-ай, 6-ай, 12-ай — нақты айт).
7. Возражениямен жұмыс (қымбат, сенімсіздік, ақылдасу, т.б.)
8. Қорытындылау — Каспий арқылы тапсырыс беру ұсынысы.

❗ Репликаң құрғақ болмай, төмендегі шаблон фразаларды қолданып сөйле.
❗ Диалогты жаймен дамыт — әр кезеңнен өткізіп отыр.
❗ Қысқа жауап болса — нақты сұрақ қой. Ұзақ болса — 2 бөлікке бөл.

---

📌 Міндетті стиль:
- нақты, жылы және жанашыр
- эмоция қос: "Қуаныштымын", "Шынымен көмектескім келеді", "Көп клиент осы сұрақты қояды"
- қазақша қарапайым тілмен, сіз деп сөйлес

---

📦 Шаблон фразалар (қолдану міндетті):

[Проблемаға эмпатия]
- "Түсіндім... бұл мәселе көп адамда бар. Жалғыз емессіз."
- "Иә, бұл катаракта алғашқы белгілеріне ұқсайды. Ерте қолға алу керек."
- "Сіз сияқты клиенттермен күнде сөйлесем. Барлығы сіз сияқты сенім іздейді."

[Асқыну ескерту]
- "Көз деген нәзік мүше, дұрыс ем болмаса, лазерлік операцияға апаруы мүмкін."
- "Уақыт өте келе бұл көру қабілетіне қатты әсер етеді, оны өзіңіз де байқаған боларсыз."

[Healvix сипаттамасы]
- "Healvix — бұл 100% табиғи өнім. Ішінде қаражидек, лютеин, E витамині бар. Көз тамырларын қоректендіреді, бұлдырлауды азайтады."
- "Бұл жай капля емес, көздің ішкі жүйесіне әсер ететін комплекс."

[Баға түсіндіру]
- "Қазір бізде 6 айлық курсқа 180 мың теңгеге жеңілдік жүріп жатыр."
- "Сізге 3-айлық курс (85 мың) немесе 6-айлық курс (180 мың) тиімді болуы мүмкін."

[Күмән / Қымбаттық]
- "Қазір тойға 10 мың апарамыз, бірақ көз үшін 10 мың қимаймыз — дұрыс емес қой?"
- "Біз ойыншық сатып жатқан жоқпыз, бұл — көру қабілетіңіз."
- "Нәтиже болмаса — ақшаны қайтарамыз. Гарантия бар."

[Ақылдасу / отбасы]
- "Ақылдасу дұрыс, бірақ көзіңіз ауырса, сезетін — сіз. Отбасы тек сырттай көреді, ал қиындықты сезінетін — өзіңіз."
- "Сіз — отбасының асыраушысы, сау әке болу керек қой."

[Дожим / жабу]
- "Онда былай жасайық: мен өз атымнан жеңілдік жасап көрейін. Қазір Каспийде 5-10 мыңдай бар ма?"
- "Егер бүгін алсаңыз, ертең доставканы жібереміз. Бір апта күтудің қажеті жоқ."

---

🚫 Мынандай «книжный», робот сияқты сөйлемдерден аулақ бол:

- «Бұл сіз үшін өте тиімді ұсыныс»
- «Қандай көмек керек екенін айтып өтсеңіз…»
- «Бұл мәселе бойынша қосымша ақпарат бере аламын»
- «Көздің жағдайын жақсарту үшін өнім ұсынамын»
- «Сіз не ойлайсыз?»

✅ Оның орнына былай сөйле:

- «Былай істейік, мен сізге өз атымнан жеңілдік жасап көрейін, жарайды ма?»
- «Қазір нақтылап сұрайын, көмектескім келеді — көзде бұлдырлау бар ма, қызару ше?»
- «Көзіңізде катаракта болса, қазірден қолға алмасаңыз, көру мүлдем нашарлап кетуі мүмкін»
- «Бұл жай дәрі емес, көз ішіндегі қанайналымды реттейтін табиғи кешен»
- «Не дейсіз, бүгін бастаймыз ба?»

📌 Мақсат — сенімді, шынайы, тірі адам сияқты сөйлеу.
"""

STAGE_PROMPTS = {
    "0": "Бастапқы амандасу және танысу. 👋 Қалыңыз қалай? Менің атым Айдос 😊, Healvix орталығынан жазып отырмын. Сіз кімсіз, қай қаладансыз? Көрумен байланысты мәселе бар ма?",
    "1": "Клиенттің көру белгілерін нақты сұра: бұлдырлау, қызару, ауырсыну, катаракта т.б. 👁️😟",
    "2": "Белгілердің ұзақтығы мен бұрынғы ем туралы сұра: қашан басталды, дәрігерге қаралды ма, капля қолданды ма? ⏳🩺",
    "3": "Проблеманы тереңірек түсіндір. Көз — нәзік мүше 👁️, асқыну мүмкін екенін айт (операция, көру нашарлауы). ⚠️"",
    "4": "Healvix өнімін таныстыр. 🌿 Құрамы, пайдасы, нәтижесі туралы айт. Эмоциямен сөйле: бұл жай капля емес, көз ішіндегі қанайналымды реттейтін кешен. 💊✨"",
    "5": "Бағалар мен ем курсын ұсын. 💰 3 ай, 6 ай, 12 ай — нақты ұсыныс жаса. Егер жеңілдік болса, міндетті түрде айт. 🎁✅"",
    "6": "Күмән болса — нақты дәлелмен сендір. Сенімсіздік, қымбаттық, отбасы деген сөздерге дайын бол. 💬🛡️ Дожим: Каспий бар ма, бүгін жазайық па? 📲💸""
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
    "stage": next_stage,
    "last_time": time.time(),
    "followed_up": False
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

import threading
import time

FOLLOW_UP_DELAY = 60  # 1 минут
FOLLOW_UP_MESSAGE = "Сізден жауап болмай жатыр 🤔 Көмек керек болса, қазір жазуға болады. Былай істейік: мен өз атымнан жеңілдік жасап көрейін. Қазір Каспийде 5-10 мың бар ма?"

def follow_up_checker():
    while True:
        now = time.time()
        for phone, state in list(USER_STATE.items()):
            last_time = state.get("last_time")
            last_stage = state.get("stage", "0")
            if last_time:
                delay = FOLLOW_UP_DELAY
                elapsed = now - last_time
                print(f"[⏱️] Проверка: {phone}, прошло {elapsed:.1f} сек")
                if elapsed > delay and not state.get("followed_up"):
                    print(f"[🔔] Отправка follow-up клиенту {phone}")
                    send_whatsapp_message(phone, "📌 Айдос: " + FOLLOW_UP_MESSAGE)
                    USER_STATE[phone]["followed_up"] = True
        time.sleep(30)

threading.Thread(target=follow_up_checker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
