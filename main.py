import os
import time
import threading
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

# sales_prompts.py

SALES_SCRIPT_PROMPT = """
Сен — Даурен есімді Healvix көз орталығының кеңесшісісің. Міндетің — клиентті бүгін шешім қабылдауға жеткізу. Сен тірі адам сияқты сөйлейсің: жылы, сенімді, кейде эмоциямен қысым жасап.  

📌 Стиль:  
- Жылы, сенімді, қажет кезде қатаң.  
- Қауіпті нақты көрсету (қорқыныш + мысал).  
- Уақыт шектеуі («соңғы қорап», «тек бүгін жеңілдік»).  
- Кез келген сылтауға дайын жауап.  
- Әрқашан қазір заказ беруге бағыттау.  

📌 Міндетті фразалар:  
- «Бұл жай дәрі емес, көруіңізді сақтайтын мүмкіндік.»  
- «Кешіктірсеңіз, ертең кеш болуы мүмкін.»  
- «Соңғы қораптар ғана қалды.»  

📌 Тыйым салынған:  
- Робот сияқты сөйлеу  
- Суық, эмоциясыз жауап  
- Клиентті «кейін» жіберу  

📌 Өнім:  
- 1 қорап — 9 990 ₸  
- 3 қорап (акция) — 21 990 ₸  
- Доставка — 1 500–2 000 ₸, Қазақстан бойынша  
- Құрамы: қаражидек, календула, очанка, жүзім сүйегі, сәбіз, теңіз кірпісі + дәрумендер  
- Әсері: көруді жақсартады, қабынуды азайтады, катаракта/глаукома алдын алады  
- Қарсы көрсетілім: онкология, стент, бала емізу  
"""

STAGE_PROMPTS = {
    "0": "Сәлеметсіз бе! 👋 Қалыңыз қалай? Менің атым Даурен, Healvix көз орталығының маманымын. Есіміңіз кім? Көзіңізде қандай белгілер бар?",
    
    "1": "Жалпы, көруіңізде қандай өзгерістер байқадыңыз? 👁️ Бұлдырлау, ұсақ әріптерді көрмеу, жарыққа сезімталдық бар ма?",
    
    "2": "Бұл қашан басталды? Дәрігерге қаралдыңыз ба? ⏳ Көп адам кешіктіріп, катарактаға дейін жеткізеді. Ерте қолға алсақ, нәтиже әлдеқайда жақсы болады.",
    
    "3": "Көз — нәзік мүше. Уақтылы ем болмаса, асқынып операцияға апарады. Бірақ дұрыс емді ерте бастасаңыз, көру сапасы жақсарады. 45 жастағы клиентіміз уақытында бастады, қазір көлік айдап жүр.",
    
    "4": "Сізге көмектесетін өнім — Healvix 🌿💊. 100% табиғи: қаражидек, календула, очанка, жүзім сүйегі, сәбіз, теңіз кірпісі және дәрумендер. Бұл көздің қан айналымын жақсартып, тор қабықты қоректендіреді.",
    
    "5": "Баға: 1 қорап — 9 990 ₸, ал акциямен 3 қорап — 21 990 ₸. 🎁 Жеңілдік уақытша, қоймада соңғы қораптар қалды. Бүгін үлгеріп алыңыз.",
    
    "6": "Күмән болса — айтыңыз. Бағаға қатысты: біз адал сатамыз, қолдан қымбаттатпаймыз. Ақша аз болса — бөліп төлеу бар. Ең дұрысы — емді созбай бастау. Сізге ыңғайлысы қайсы — 1 қорап па, әлде 3 қорап па?"
}

FAQ_PROMPTS = {
    "Баға қанша?": "1 қорап — 9 990 ₸. Ал қазір акциямен 3 қорап — бар болғаны 21 990 ₸ 🎁",
    "Неге арзан?": "Біз адал сатамыз. Бағаны қолдан қымбаттатпаймыз, науқастардың ауруымен ойнамаймыз.",
    "Құрамы қандай?": "100% табиғи: қаражидек, календула, очанка, жүзім сүйегі, сәбіз, теңіз кірпісі және дәрумендер (A, B, C, D, E).",
    "Катарактаға көмектесе ме?": "Иә, катарактаның алдын алуға көмектеседі. Бірақ қарсы көрсетілім болмаса ғана.",
    "Глаукомаға көмектесе ме?": "Иә, көруді жақсартып, көз қысымын төмендетуге әсер етеді.",
    "Қарсы көрсетілім бар ма?": "Онкологиясы барларға, жүрегінде стент барларға және бала емізіп жүрген әйелдерге болмайды.",
    "Қалай ішу керек?": "Қаптамада 60 капсула бар. Күніне 2 капсуладан қабылдайсыз.",
    "Жеткізу қалай?": "Қазақстанның барлық аймағына жеткіземіз 🚚. Бағасы 1 500–2 000 ₸."
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

FOLLOW_UP_DELAY = 60
FOLLOW_UP_MESSAGE = "Сізден жауап болмай жатыр 🤔 Сұрақтарыңыз болса, жауап беруге дайынмын."

def follow_up_checker():
    while True:
        now = time.time()
        for phone, state in list(USER_STATE.items()):
            last_time = state.get("last_time")
            last_stage = state.get("stage", "0")
            if last_time:
                elapsed = now - last_time
                print(f"[⏱️] Проверка: {phone}, прошло {elapsed:.1f} сек")
                if elapsed > FOLLOW_UP_DELAY and not state.get("followed_up"):
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

            start_followup_thread()

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

from datetime import datetime, timedelta

# ==== Настройки ====

SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

# Хранилище для защиты от повторов
last_sent = {}

# ==== Отправка сообщения в WhatsApp ====
def handle_manager_message(phone, text):
    """
    Отправка сообщения в WhatsApp через 360dialog.
    """
    payload = {
        "messaging_product": "whatsapp",  # ОБЯЗАТЕЛЬНОЕ поле!
        "to": phone,
        "type": "text",
        "text": {
            "body": text
        }
    }

    print(f"[DEBUG] Отправка в WhatsApp: {phone} → {text}")
    print(f"[DEBUG] Payload: {payload}")

    try:
        response = requests.post(
            WHATSAPP_API_URL,
            headers=HEADERS,
            json=payload,
            timeout=10
        )
        print(f"[DEBUG] Ответ WhatsApp API: {response.status_code} {response.text}")
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"❌ Ошибка отправки WhatsApp: {e}")

# ==== Функция запроса в CRM ====
def fetch_order_from_crm(order_id):
    headers = {
        "Content-Type": "application/json",
        "Authorization": SALESRENDER_TOKEN
    }
    query = {
        "query": f"""
        query {{
            ordersFetcher(filters: {{ include: {{ ids: ["{order_id}"] }} }}) {{
                orders {{
                    id
                    data {{
                        humanNameFields {{
                            value {{
                                firstName
                                lastName
                            }}
                        }}
                        phoneFields {{
                            value {{
                                international
                                raw
                                national
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """
    }
    try:
        response = requests.post(SALESRENDER_URL, headers=headers, json=query, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
        return data[0] if data else None
    except Exception as e:
        print(f"❌ Ошибка запроса в CRM API: {e}")
        return None


# ==== Основная логика ====
def process_salesrender_order(order):
    try:
        # Если customer пустой, пытаемся подтянуть из CRM
        if not order.get("customer") and "id" in order:
            print(f"⚠ customer пуст, подтягиваю из CRM по ID {order['id']}")
            full_order = fetch_order_from_crm(order["id"])
            if full_order:
                order = full_order
            else:
                print("❌ CRM не вернул данные — пропуск")
                return

        first_name = ""
        last_name = ""
        phone = ""

        if "customer" in order:
            first_name = order.get("customer", {}).get("name", {}).get("firstName", "").strip()
            last_name = order.get("customer", {}).get("name", {}).get("lastName", "").strip()
            phone = order.get("customer", {}).get("phone", {}).get("raw", "").strip()
        else:
            human_fields = order.get("data", {}).get("humanNameFields", [])
            phone_fields = order.get("data", {}).get("phoneFields", [])
            if human_fields:
                first_name = human_fields[0].get("value", {}).get("firstName", "").strip()
                last_name = human_fields[0].get("value", {}).get("lastName", "").strip()
            if phone_fields:
                phone = phone_fields[0].get("value", {}).get("international", "").strip()

        name = f"{first_name} {last_name}".strip()

        if not phone:
            print("❌ Телефон отсутствует — пропуск")
            return

        now = datetime.utcnow()
        if phone in last_sent and now - last_sent[phone] < timedelta(minutes=3):
            print(f"⚠ Повторный недозвон по {phone} — пропускаем")
            return

        # Определяем приветствие (UTC+6)
        now_kz = now + timedelta(hours=6)
        if 5 <= now_kz.hour < 12:
            greeting = "Қайырлы таң"
        elif 12 <= now_kz.hour < 18:
            greeting = "Сәлеметсіз бе"
        else:
            greeting = "Қайырлы кеш"

        # Генерация сообщения через GPT
        try:
            if name:
                prompt = (
                    f"{greeting}! Клиенттің аты {name}. "
                    f"Оған қоңырау шалдық, бірақ байланыс болмады. "
                    f"Клиентке WhatsApp-та қысқа, жылы, достық хабарлама жазыңыз. "
                    f"Хабарламаны Айдос атынан Healvix орталығынан жазыңыз."
                )
            else:
                prompt = (
                    f"{greeting}! Біз клиентке қоңырау шалдық, бірақ байланыс болмады. "
                    f"Клиентке WhatsApp-та қысқа, жылы, достық хабарлама жазыңыз. "
                    f"Хабарламаны Айдос атынан Healvix орталығынан жазыңыз. "
                    f"Есімін қолданбаңыз."
                )

            gpt_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            message_text = gpt_response.choices[0].message.content.strip()
        except Exception as e:
            print(f"❌ GPT қатесі: {e}")
            message_text = f"{greeting}! Біз сізге қоңырау шалдық, бірақ байланыс болмады. Уақытыңыз болса, хабарласыңыз."

        # Отправляем в WhatsApp (твоя функция)
        handle_manager_message(phone, message_text)

        # Запоминаем отправку
        last_sent[phone] = now
        print(f"✅ Сообщение отправлено на {phone}")

    except Exception as e:
        print(f"❌ Ошибка обработки заказа: {e}")

# ==== Вебхук ====
@app.route('/salesrender-hook', methods=['POST'])
def salesrender_hook():
    print("=== Входящий запрос в /salesrender-hook ===")
    try:
        data = request.get_json()
        print("Payload:", data)

        orders = (
            data.get("data", {}).get("orders")
            or data.get("orders")
            or [data]
        )

        if not orders or not isinstance(orders, list):
            return jsonify({"error": "Нет заказов"}), 400

        threading.Thread(
            target=process_salesrender_order,
            args=(orders[0],),
            daemon=True
        ).start()

        return jsonify({"status": "accepted"}), 200
    except Exception as e:
        print(f"❌ Ошибка парсинга вебхука: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
