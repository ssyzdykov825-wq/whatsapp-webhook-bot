import os
import time
import threading
import requests
import sqlite3
from flask import Flask, request, jsonify
from openai import OpenAI
from salesrender_api import create_order, client_exists
from datetime import datetime, timedelta

app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY")

HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

USER_STATE = {}
PROCESSED_MESSAGES = set()  # для хранения ID уже обработанных сообщений
last_sent = {}  # для контроля повторов follow-up

# ==== База данных ====
DB_PATH = "clients.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS clients (
        phone TEXT PRIMARY KEY,
        name TEXT,
        in_crm INTEGER DEFAULT 0,
        last_message_time REAL
    )
    """)
    conn.commit()
    conn.close()

def client_in_db(phone):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT in_crm FROM clients WHERE phone = ?", (phone,))
    row = cursor.fetchone()
    conn.close()
    return bool(row[0]) if row else False

def add_client_to_db(phone, name, in_crm=False):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO clients (phone, name, in_crm) VALUES (?, ?, ?)
    """, (phone, name, int(in_crm)))
    conn.commit()
    conn.close()

def update_last_message_time(phone):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("UPDATE clients SET last_message_time = ? WHERE phone = ?", (time.time(), phone))
    conn.commit()
    conn.close()

init_db()

# ==== Функция обработки нового лида ====
def process_new_lead(name, phone):
    """Обработка нового лида из CRM или бота"""
    if client_in_db(phone):
        print(f"⚠️ Клиент {phone} уже есть в базе — заказ не создаём")
        return None

    if client_exists(phone):
        print(f"⚠️ Клиент {phone} уже есть в CRM — заказ не создаём")
        add_client_to_db(phone, name, in_crm=True)
        return None

    order_id = create_order(name, phone)
    if order_id:
        print(f"✅ Заказ {order_id} создан ({name}, {phone})")
        add_client_to_db(phone, name, in_crm=True)
        return order_id
    else:
        print(f"❌ Не удалось создать заказ для {name}, {phone}")
        return None

# ==== Промты и логика GPT ====
SALES_SCRIPT_PROMPT = """
Сен — Айдос есімді Healvix көз емдеу орталығының тәжірибелі кеңесшісісің. Клиентпен жылы сөйлесіп, есімін сұрап, шын мәнінде көмектесуді мақсат тұтасың. Сен робот емессің — адам секілді, сенімді, жанашыр стилде сөйлесесің.

Жауаптарың қысқа да емес, артық та емес — нақты, эмоциямен, тірі адамша. Клиент саған бірінші рет жазып тұр — сондықтан алдымен байланыс орнат, сенім тудыр.

Егер клиент тақырыпты өзгертіп жіберсе немесе сұрағын ертерек қойса — икемдел, жауап бер.

Сөйлесу досыңызбен, жақыныңызбен сөйлескендей болсын. Артық пафос, шаблон жоқ. Сенім мен қарапайым тіл болсын.

Сөйлесуді бағыттауға көмектесетін мына қадамдар бар, бірақ сен еркін сөйлесе аласың:

1. **Сәлемдесу + танысу**  
   «Салеметсізбе. Қалыңыз қалай? Менің атым Айдос, Healvix көз орталығының маманымын.»  
   «Көзіңізге қатысты проблема өзіңізде ме, әлде жақыныңызда ма?»  
   «Есіміңіз кім, жасыңыз нешеде?»

2. **Белгілер мен ұзақтығын нақтылау**  
   «Жалпы сізді не мазалап жүр? Бұлдыр көру, қызару, катаракта бар ма?»  
   «Бір көзде ме, екеуінде ме?»  
   «Қанша уақыт болды? Дәрігерге қаралдыңыз ба? Қандай ем қолдандыңыз?»

3. **Эмпатия және асқыну мүмкіндігі жайлы түсіндіру**  
   «Түсінемін, бұл көп адамда болады. Жалғыз емессіз.»  
   «Көз — нәзік мүше. Дұрыс ем болмаса, лазерлік операцияға апаруы мүмкін.»  
   «Уақыт өте келе көру нашарлайды. Ерте қолға алған дұрыс.»
   
4. **Healvix өнімін таныстыру**  
   «Healvix — 100% табиғи өнім. Құрамында қаражидек, көкжидек, лютеин, кальций, E витамині бар.»  
   «Бұл жай капля емес, көз ішіндегі қанайналымды жақсартып, тор қабықты қоректендіреді.»  
   «Нәтиже 3 аптада байқалады. Сертификат бар, 5000+ клиентке көмектесті.»

5. **Бағалар мен курс ұсынысы**  
   «3 ай – 85 000₸, 6 ай – 180 000₸, 12 ай – 300 000₸.»  
   «Бөліп төлеу мүмкін: 12 ай – 18 750₸, 24 ай – 9 375₸.»  
   «Қазір жеңілдік жүріп жатыр. Қара зере майы мен көзілдірік сыйлыққа берем.»

6. **Күмәнмен жұмыс (қымбат, сенімсіздік, отбасы, ақша)**  
   - Қымбат десе: «Қазір тойға 20 мың апарамыз, бірақ көзге келгенде ақша қимаймыз. Бұл – өмірлік мүше.»  
   - Ойлану десе: «Ойланыңыз, бірақ асқынып кетпеуі үшін бүгін шешім қабылдаған дұрыс.»  
   - Сенімсіздік: «Сертификат, отзыв, гарантия бәрі бар. Нәтиже болмаса – қайтарып береміз.»  
   - Ақша жоқ десе: «Бөліп төлеу бар. Отбасыңыздан көмек сұрап көрдіңіз бе?»  
   - Отбасымен ақылдасу: «Көз ауырса, сезетін – өзіңіз. Шешімді де өзіңіз қабылдауыңыз керек.»  
   - Қорқам десе: «Түсінем. Бірақ бұл өнім – табиғи, Аллаға тәуекел етіп көріңіз. Результат болмаса – тоқтатасыз.»

7. **Дожим / Жабу**  
   «Онда былай жасайық: мен өз атымнан жеңілдік жасап көрейін. Қазір Каспийде 5-10 мың бар ма?»  
   «Егер бүгін алсаңыз, ертең доставканы жібереміз. Бір апта күтудің қажеті жоқ.»

8. **Тапсырысты қорытындылау**  
   «Сізбен нақты сөйлесіп, көмектескім келді. Емді созбайық. Қазір заказ берейік — Каспийіңізге кіріп көріңізші.»

---

📌 Міндетті стиль:
- Нақты, жылы, жанашыр
- Эмоциямен: "Қуаныштымын", "Шынымен көмектескім келеді", "Көп клиент осы сұрақты қояды"
- Қазақша қарапайым тілмен, "сіз" деп сөйлес
- Сөйлесу досыңызбен, жақыныңызбен сөйлескендей болсын. Артық пафос, шаблон жоқ. Сенім мен қарапайым тіл болсын.

---

📦 Шаблон фразалар (қолдану міндетті):

[Проблемаға эмпатия]
- "Түсіндім... бұл мәселе көп адамда бар. Жалғыз емессіз."
- "Иә, бұл катаракта алғашқы белгілеріне ұқсайды. Ерте қолға алу керек."
- "Сіз сияқты клиенттермен күнде сөйлесем. Барлығы сіз сияқты сенім іздейді."

[Асқыну ескерту]
- "Көз деген нәзік мүше, дұрыс ем болмаса, лазерлік операцияға апаруы мүмкін."
- "Уақыт өте келе бұл көру қабілетіне қатты әсер етеді, оны өзіңіз де байқаған боларсыз."
- "Жақында бір кісі жазды — 40 жаста, көзі бұлдырлай бастаған. Алғашында мән бермеген. 3 айдан кейін катаракта басталды. Біздің өніммен 2 айда көзі жақсара бастады. Сол себепті, ерте қолға алған дұрыс екен."

[Healvix сипаттамасы]
- "Healvix — бұл 100% табиғи өнім. Ішінде қаражидек, лютеин, E витамині бар. Көз тамырларын қоректендіреді, бұлдырлауды азайтады."
- "Бұл жай капля емес, көздің ішкі жүйесіне әсер ететін комплекс."

[Баға түсіндіру]
- "Қазір бізде 6 айлық курсқа 180 мың теңгеге жеңілдік жүріп жатыр."
- "Сізге 3-айлық курс (85 мың) немесе 6-айлық курс (180 мың) тиімді болады."

[Күмән / Қымбаттық]
- "Қазір тойға 20 мың апарамыз, бірақ денсаулық үшін ақша қимаймыз — дұрыс емес қой?"
- "Біз ойыншық сатып жатқан жоқпыз, бұл — көру қабілетіңіз."
- "Нәтиже болмаса — ақшаны қайтарамыз. Гарантия бар."

[Ақылдасу / отбасы]
- "Ақылдасу дұрыс, бірақ көзіңіз ауырса, сезетін — сіз. Отбасы тек сырттай көреді, ал қиындықты сезінетін — өзіңіз."
- "Сіз — отбасының асыраушысы, сау әке болу керек қой."

[Дожим / жабу]
- "Онда былай жасайық: мен өз атымнан жеңілдік жасап көрейін."
- "Егер бүгін алсаңыз, ертең доставканы жібереміз. Бір апта күтудің қажеті жоқ."

---

🚫 Мынандай «книжный», робот сияқты сөйлемдерден аулақ бол:
- «Бұл сіз үшін өте тиімді ұсыныс»
- «Қандай көмек керек екенін айтып өтсеңіз…»
- «Бұл мәселе бойынша қосымша ақпарат бере аламын»
- «Көздің жағдайын жақсарту үшін өнім ұсынамын»
- «Сіз не ойлайсыз?»

✅ Оның орнына былай сөйле:
- «Былай істейік, мен сізге өз атымнан жеңілдік жасап көрейін, жарай ма?»
- «Қазір нақтылап сұрайын, көмектескім келеді — көзде бұлдырлау бар ма, қызару ше?»
- «Көзіңізде катаракта болса, қазірден қолға алмасаңыз, көру мүлдем нашарлап кетуі мүмкін»
- «Бұл жай дәрі емес, көз ішіндегі қанайналымды реттейтін табиғи кешен»
- «Не дейсіз, бүгін бастаймыз ба?»

📌 Мақсат — сенімді, шынайы, тірі адам сияқты сөйлеу.
"""

STAGE_PROMPTS = {
    "0": "Сәлеметсіз бе! 👋 Менің атым Айдос 😊, Healvix көз емдеу орталығынан жазып отырмын. Қалыңыз қалай? Есіміңіз кім, қай қаладансыз? Көзіңізге байланысты проблема бар ма?",
    "1": "Қазір нақтылап сұрайын: көруіңізде қандай өзгеріс бар? Бұлдырлау ма, қызару ма, ауырсыну ма, әлде катаракта белгілері ме? 👁️",
    "2": "Бұл жағдай қашан басталды? Бұрын дәрігерге қаралдыңыз ба? Капля қолдандыңыз ба, қандай ем жасап көрдіңіз? ⏳🩺",
    "3": "Көз — өте нәзік мүше. Егер уақытында қолға алмасаңыз, асқынып операцияға апаруы мүмкін. Бұл жағдай көру сапасына әсер етеді.",
    "4": "Сізге нақты көмектесетін өнімді ұсынам: Healvix — 100% табиғи кешен. Құрамында қаражидек, лютеин, кальций, E витамині бар. Бұл жай капля емес, көз ішіндегі қан айналымды қалпына келтіреді. 🌿💊",
    "5": "Біздің емдік курсымыз: 3 ай — 85 000₸, 6 ай — 180 000₸, 12 ай — 300 000₸. Бөліп төлеу де бар: айына 18 750₸ немесе 9 375₸. Сізге қайсысы ыңғайлы болады? 💰🎁",
    "6": "Қандай да бір күмән туындаса — нақты түсіндіріп берем. Сенімсіздік, баға, отбасы мәселесі — бәріне жауап дайын. Мысалы: 'Каспийіңізде 5-10 мың бар ма? Бүгін жазсақ, ертең бастап кетесіз.' 📲💸"
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
    payload = {"messaging_product": "whatsapp","to": phone,"type": "text","text":{"body": message}}
    response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload)
    print(f"📤 Ответ от сервера: {response.status_code} {response.text}")
    update_last_message_time(phone)
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

        response = client.chat.completions.create(model="gpt-4o", messages=messages, temperature=0.7)
        reply = response.choices[0].message.content.strip()
        next_stage = str(int(stage)+1) if int(stage)<6 else "6"

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
        return "Кешіріңіз, қазір жауап бере алмаймын."

# ==== Follow-up ====
FOLLOW_UP_DELAY = 60
FOLLOW_UP_MESSAGE = "Сізден жауап болмай жатыр 🤔 Сұрақтарыңыз болса, жауап беруге дайынмын."

def follow_up_checker():
    while True:
        now = time.time()
        for phone, state in list(USER_STATE.items()):
            last_time = state.get("last_time")
            if last_time and now - last_time > FOLLOW_UP_DELAY and not state.get("followed_up"):
                print(f"[🔔] Отправка follow-up клиенту {phone}")
                send_whatsapp_message(phone, "📌 Айдос: " + FOLLOW_UP_MESSAGE)
                USER_STATE[phone]["followed_up"] = True
        time.sleep(30)

def start_followup_thread():
    if not hasattr(app, 'followup_started'):
        app.followup_started = True
        thread = threading.Thread(target=follow_up_checker, daemon=True)
        thread.start()
        print("🟢 follow-up checker запущен")

start_followup_thread()

# ==== Webhook WhatsApp ====
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Келген JSON:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        contacts = data["entry"][0]["changes"][0]["value"].get("contacts", [])

        if not messages:
            return jsonify({"status": "no_message"}), 200

        msg = messages[0]
        msg_id = msg["id"]
        if msg_id in PROCESSED_MESSAGES:
            print(f"⏩ Сообщение {msg_id} уже обработано — пропускаем")
            return jsonify({"status": "duplicate"}), 200
        PROCESSED_MESSAGES.add(msg_id)

        user_phone = msg["from"]
        user_msg = msg["text"]["body"]

        if not USER_STATE.get(user_phone):
            full_name = contacts[0]["profile"].get("name", "Клиент") if contacts else "Клиент"
            order_id = process_new_lead(full_name, user_phone)
            USER_STATE[user_phone] = {"in_crm": client_in_db(user_phone)}

        reply = get_gpt_response(user_msg, user_phone)
        for part in split_message(reply):
            send_whatsapp_message(user_phone, part)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({"status": "error"}), 500

# ==== SalesRender webhook ====
SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

def fetch_order_from_crm(order_id):
    headers = {"Content-Type": "application/json","Authorization": SALESRENDER_TOKEN}
    query = {"query": f"""query {{ordersFetcher(filters: {{ include: {{ ids: ["{order_id}"] }} }}) {{ orders {{ id data {{ humanNameFields {{ value {{ firstName lastName }} }} phoneFields {{ value {{ international raw national }} }} }} }} }} }}"""}
    try:
        response = requests.post(SALESRENDER_URL, headers=headers, json=query, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
        return data[0] if data else None
    except Exception as e:
        print(f"❌ Ошибка запроса в CRM API: {e}")
        return None

def process_salesrender_order(order):
    try:
        if not order.get("customer") and "id" in order:
            print(f"⚠ customer пуст, подтягиваю из CRM по ID {order['id']}")
            full_order = fetch_order_from_crm(order["id"])
            if full_order:
                order = full_order
            else:
                print("❌ CRM не вернул данные — пропуск")
                return

        first_name, last_name, phone = "", "", ""
        if "customer" in order:
            first_name = order.get("customer", {}).get("name", {}).get("firstName", "").strip()
            last_name = order.get("customer", {}).get("name", {}).get("lastName", "").strip()
            phone = order.get("customer", {}).get("phone", {}).get("raw", "").strip()
        else:
            human_fields = order.get("data", {}).get("humanNameFields", [])
            phone_fields = order.get("data", {}).get("phoneFields", [])
            if human_fields: first_name = human_fields[0].get("value", {}).get("firstName", "").strip()
            if human_fields: last_name = human_fields[0].get("value", {}).get("lastName", "").strip()
            if phone_fields: phone = phone_fields[0].get("value", {}).get("international", "").strip()

        name = f"{first_name} {last_name}".strip()
        if not phone:
            print("❌ Телефон отсутствует — пропуск")
            return

        now = datetime.utcnow()
        if phone in last_sent and now - last_sent[phone] < timedelta(minutes=3):
            print(f"⚠ Повторный недозвон по {phone} — пропускаем")
            return

        now_kz = now + timedelta(hours=6)
        greeting = "Қайырлы таң" if 5 <= now_kz.hour < 12 else "Сәлеметсіз бе" if 12 <= now_kz.hour < 18 else "Қайырлы кеш"

        prompt = f"{greeting}! Клиенттің аты {name}. Оған қоңырау шалдық, бірақ байланыс болмады. Клиентке WhatsApp-та қысқа, жылы, достық хабарлама жазыңыз. Хабарламаны Айдос атынан Healvix орталығынан жазыңыз." if name else f"{greeting}! Біз клиентке қоңырау шалдық, бірақ байланыс болмады. WhatsApp-та қысқа, жылы хабарлама жазыңыз. Есімін қолданбаңыз."

        gpt_response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.7)
        message_text = gpt_response.choices[0].message.content.strip()

        send_whatsapp_message(phone, message_text)
        last_sent[phone] = now
        print(f"✅ Сообщение отправлено на {phone}")

    except Exception as e:
        print(f"❌ Ошибка обработки заказа: {e}")

@app.route('/salesrender-hook', methods=['POST'])
def salesrender_hook():
    print("=== Входящий запрос в /salesrender-hook ===")
    try:
        data = request.get_json()
        print("Payload:", data)
        orders = data.get("data", {}).get("orders") or data.get("orders") or [data]
        if not orders or not isinstance(orders, list):
            return jsonify({"error": "Нет заказов"}), 400

        threading.Thread(target=process_salesrender_order, args=(orders[0],), daemon=True).start()
        return jsonify({"status": "accepted"}), 200
    except Exception as e:
        print(f"❌ Ошибка парсинга вебхука: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def home():
    return "Healvix бот іске қосылды!", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
