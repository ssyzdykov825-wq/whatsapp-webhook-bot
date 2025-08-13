import os
import time
import threading
import requests
import json
import re # Добавлено для нормализации номера телефона
from flask import Flask, request, jsonify
from openai import OpenAI
from datetime import datetime, timedelta

# Import the new state management functions
from state_manager import (
    init_db, load_cache_from_db,
    get_client_state, save_client_state, client_in_db_or_cache,
    follow_up_checker, cleanup_old_clients,
    MAX_HISTORY_FOR_GPT
)

# NOTE: If you have a real salesrender_api.py file with create_order and client_exists functions,
# delete the dummy functions below and uncomment 'from salesrender_api import create_order, client_exists'.
# --- Dummy salesrender_api functions (remove if you have a real file) ---
def create_order(name, phone):
    print(f"SIMULATING CRM: Creating order for {name} ({phone})")
    # In a real scenario, this would call your SalesRender API to create an order
    return f"ORDER_{int(time.time())}" # Simulate an order ID

def client_exists(phone):
    print(f"SIMULATING CRM: Checking if client {phone} exists.")
    # In a real scenario, this would check your SalesRender CRM
    # For now, let's say it doesn't exist to trigger order creation
    return False
# --- End of dummy functions ---

# ==============================
# Configuration
# ==============================
app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY") # Ensure this is set as an env var

HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

# In-memory set for message ID deduplication (volatile, resets on app restart)
PROCESSED_MESSAGES = set()

# SalesRender CRM Config
SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
# IMPORTANT: This token is visible in your old code. In production, use os.environ.get()
# If you set SALESRENDER_TOKEN env var, this fallback will not be used.
SALESRENDER_TOKEN = os.environ.get("SALESRENDER_TOKEN", "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc")

# ==============================
# Phone Number Normalization
# ==============================
def normalize_phone_number(phone_raw):
    """
    Нормализует номер телефона к международному формату с '+'.
    Пример: '77071234567' -> '+77071234567'
            '87071234567' -> '+77071234567'
            '+77071234567' -> '+77071234567'
    """
    if not phone_raw:
        return ""
    
    # Удаляем все нецифровые символы
    phone_digits = re.sub(r'\D', '', phone_raw)

    if not phone_digits:
        return ""

    # Если начинается с 8, меняем на 7
    if phone_digits.startswith('8'):
        phone_digits = '7' + phone_digits[1:]
    
    # Если не начинается с 7, и имеет длину, подходящую для Казахстана (предполагаем 10 цифр после '7')
    # Это предположение, если номера могут приходить без 7 или 8 в начале.
    if not phone_digits.startswith('7') and len(phone_digits) == 10: 
        phone_digits = '7' + phone_digits
    
    # Добавляем '+' в начало, если его нет
    if not phone_digits.startswith('+'):
        return '+' + phone_digits
    
    return phone_digits

# ==============================
# SalesRender Utilities
# ==============================
def fetch_order_from_crm(order_id):
    """Fetches order details from SalesRender CRM using GraphQL."""
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
                        humanNameFields {{ value {{ firstName lastName }} }}
                        phoneFields {{ value {{ international raw national }} }}
                    }}
                }}
            }}
        }}
        """
    }
    try:
        response = requests.post(SALESRENDER_URL, headers=headers, json=query, timeout=10)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        data = response.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
        return data[0] if data else None
    except Exception as e:
        print(f"❌ CRM fetch error: {e}")
        return None

def process_new_lead(name, phone):
    """
    Processes a new lead: checks CRM, creates order if needed, and updates client state.
    This function is adapted from the NEW code for robustness.
    """
    # Phone is already normalized when it enters this function via webhook/salesrender_hook
    if client_in_db_or_cache(phone):
        print(f"⚠️ Клиент {phone} уже в базе/кэше, пропускаем создание заказа.")
        return None

    # Check if client exists in CRM
    if client_exists(phone):
        print(f"⚠️ Клиент {phone} уже есть в CRM, обновляем состояние.")
        save_client_state(phone, name=name, in_crm=True)
        return None

    # If client not in CRM, create order
    order_id = create_order(name, phone)
    if order_id:
        print(f"✅ Заказ {order_id} создан для {name}, {phone}. Обновляем состояние.")
        save_client_state(phone, name=name, in_crm=True)
        return order_id
    else:
        print(f"❌ Не удалось создать заказ для {name}, {phone}. Создаем запись клиента без CRM связи.")
        save_client_state(phone, name=name, in_crm=False) # Still save client state even if order creation fails
        return None


def process_salesrender_order(order):
    """
    Processes a SalesRender order webhook. Updates client state and sends manager message.
    Adapted from your old code, integrated with new state management.
    """
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
            # Normalize phone directly from CRM data
            phone = normalize_phone_number(order.get("customer", {}).get("phone", {}).get("raw", "").strip())
        else:
            human_fields = order.get("data", {}).get("humanNameFields", [])
            phone_fields = order.get("data", {}).get("phoneFields", [])
            if human_fields:
                first_name = human_fields[0].get("value", {}).get("firstName", "").strip()
                last_name = human_fields[0].get("value", {}).get("lastName", "").strip()
            if phone_fields:
                # Normalize phone directly from CRM data
                phone = normalize_phone_number(phone_fields[0].get("value", {}).get("international", "").strip())

        name = f"{first_name} {last_name}".strip() or "Клиент"

        if not phone:
            print("❌ Телефон отсутствует — пропуск")
            return

        # If client is already in the system, no need to process as new lead
        # This prevents duplicate initial processing from SalesRender if client already messaged bot.
        if client_in_db_or_cache(phone): # Phone is already normalized here
            print(f"ℹ️ Клиент {phone} уже известен, обновляем его CRM статус.")
            save_client_state(phone, name=name, in_crm=True) # Ensure CRM status is true
            # Optionally, you might want to send a different message to known clients
            # For now, let's skip manager message for existing clients
            return

        # For new leads from CRM, ensure they are added to our state system
        process_new_lead(name, phone) # Phone is already normalized here


        # Manager message logic (from old code)
        now = datetime.utcnow()
        # last_sent is still in-memory for this specific rate-limiting purpose
        if phone in last_sent and now - last_sent[phone] < timedelta(minutes=3):
            print(f"⚠ Повторный недозвон по {phone} — пропускаем отправку менеджеру.")
            return

        # Determine greeting (UTC+6)
        now_kz = now + timedelta(hours=6)
        if 5 <= now_kz.hour < 12:
            greeting = "Қайырлы таң"
        elif 12 <= now_kz.hour < 18:
            greeting = "Сәлеметсіз бе"
        else:
            greeting = "Қайырлы кеш"

        # Generate message via GPT
        try:
            if name and name != "Клиент":
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
            print(f"❌ GPT error: {e}")
            message_text = f"{greeting}! Біз сізге қоңырау шалдық, бірақ байланыс болмады. Уақытыңыз болса, хабарласыңыз."

        # Send to WhatsApp
        send_whatsapp_message(phone, message_text) # Re-using the main send_whatsapp_message

        # Remember dispatch
        last_sent[phone] = now
        print(f"✅ Message sent to {phone}")

    except Exception as e:
        print(f"❌ Error processing order: {e}")


# ==============================
# GPT Prompts (kept in main app.py)
# ==============================
SALES_SCRIPT_PROMPT = """
Сен — Айдос есімді Healvix көз емдеу орталығының тәжірибелі кеңесшісісің. Клиентпен жылы сөйлесіп, есімін сұрап, шын мәнінде көмектесуді мақсат тұтасың. Сен робот емессің — адам секілді, сенімді, жанашыр стилде сөйлесесің.

Жауаптарың қысқа да емес, артық та емес — нақты, эмоциямен, тірі адамша. Клиент саған бірінші рет жазып тұр — сондықтан алдымен байланыс орнат, сенім тудыр.

Егер клиент тақырыпты өзгертіп жіберсе немесе сұрағын ертерек қойса — икемдел, жауап бер.

Сөйлесу досыңызбен, жақыныңызбен сөйлескендей болсын. Артық пафос, шаблон жоқ. Сенім мен қарапайым тіл болсын.

Сөйлесуді бағыттауға көмектесетін мына қадамдар бар, бірақ сен еркін сөйлесе аласың:

1. **Сәлемдесу + танысу** «Салеметсізбе. Қалыңыз қалай? Менің атым Айдос, Healvix көз орталығының маманымын.»  
   «Көзіңізге қатысты проблема өзіңізде ме, әлде жақыныңызда ма?»  
   «Есіміңіз кім, жасыңыз нешеде?»

2. **Белгілер мен ұзақтығын нақтылау** «Жалпы сізді не мазалап жүр? Бұлдыр көру, қызару, катаракта бар ма?»  
   «Бір көзде ме, екеуінде ме?»  
   «Қанша уақыт болды? Дәрігерге қаралдыңыз ба? Қандай ем қолдандыңыз?»

3. **Эмпатия және асқыну мүмкіндігі жайлы түсіндіру** «Түсінемін, бұл көп адамда болады. Жалғыз емессіз.»  
   «Көз — нәзік мүше. Дұрыс ем болмаса, лазерлік операцияға апаруы мүмкін.»  
   «Уақыт өте келе көру нашарлайды. Ерте қолға алған дұрыс.»
   
4. **Healvix өнімін таныстыру** «Healvix — 100% табиғи өнім. Құрамында қаражидек, көкжидек, лютеин, кальций, E витамині бар.»  
   «Бұл жай капля емес, көз ішіндегі қанайналымды жақсартып, тор қабықты қоректендіреді.»  
   «Нәтиже 3 аптада байқалады. Сертификат бар, 5000+ клиентке көмектесті.»

5. **Бағалар мен курс ұсынысы** «3 ай – 85 000₸, 6 ай – 180 000₸, 12 ай – 300 000₸.»  
   «Бөліп төлеу мүмкін: 12 ай – 18 750₸, 24 ай – 9 375₸.»  
   «Қазір жеңілдік жүріп жатыр. Қара зере майы мен көзілдірік сыйлыққа берем.»

6. **Күмәнмен жұмыс (қымбат, сенімсіздік, отбасы, ақша)** - Қымбат десе: «Қазір тойға 20 мың апарамыз, бірақ көзге келгенде ақша қимаймыз. Бұл – өмірлік мүше.»  
   - Ойлану десе: «Ойланыңыз, бірақ асқынып кетпеуі үшін бүгін шешім қабылдаған дұрыс.»  
   - Сенімсіздік: «Сертификат, отзыв, гарантия бәрі бар. Нәтиже болмаса – қайтарып береміз.»  
   - Ақша жоқ десе: «Бөліп төлеу бар. Отбасыңыздан көмек сұрап көрдіңіз бе?»  
   - Отбасымен ақылдасу: «Көз ауырса, сезетін – сіз. Отбасы тек сырттай көреді, ал қиындықты сезінетін – өзіңіз.»  
   - Қорқам десе: «Түсінем. Бірақ бұл өнім – табиғи, Аллаға тәуекел етіп көріңіз. Результат болмаса – тоқтатасыз.»

7. **Дожим / Жабу** «Онда былай жасайық: мен өз атымнан жеңілдік жасап көрейін. Қазір Каспийде 5-10 мың бар ма?»  
   «Егер бүгін алсаңыз, ертең доставканы жібереміз. Бір апта күтудің қажеті жоқ.»

8. **Тапсырысты қорытындылау** «Сізбен нақты сөйлесіп, көмектескім келді. Емді созбайық. Қазір заказ берейік — Каспийіңізге кіріп көріңізші.»

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

[Тапсырысты қорытындылау]
- "Сізбен нақты сөйлесіп, көмектескім келді. Емді созбайық. Қазір заказ берейік — Каспийіңізге кіріп көріңізші."

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

[Тапсырысты қорытындылау]
- "Сізбен нақты сөйлесіп, көмектескім келді. Емді созбайық. Қазір заказ берейік — Каспийіңізге кіріп көріңізші."

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

[Тапсырысты қорытындылау]
- "Сізбен нақты сөйлесіп, көмектескім келді. Емді созбайық. Қазір заказ берейік — Каспийіңізге кіріп көріңізші."

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

def build_messages_for_gpt(state, user_msg):
    """Builds messages for GPT, using the last N messages from history + current stage."""
    prompt = SALES_SCRIPT_PROMPT + "\n\n" + STAGE_PROMPTS.get(state["stage"], "")
    messages = [{"role": "system", "content": prompt}]

    # Using MAX_HISTORY_FOR_GPT from state_manager
    recent_history = state["history"][-MAX_HISTORY_FOR_GPT:] 
    for item in recent_history:
        u = item.get("user", "")
        b = item.get("bot", "")
        if u:
            messages.append({"role": "user", "content": u})
        if b:
            messages.append({"role": "assistant", "content": b})

    messages.append({"role": "user", "content": user_msg})
    return messages


def split_message(text, max_length=1000):
    """Splits long texts by sentences or newlines for WhatsApp."""
    parts = []
    text = text.strip()
    while len(text) > max_length:
        # Try to find a good split point (newline or sentence end)
        split_index = max(text[:max_length].rfind("\n"), text[:max_length].rfind(". "))
        if split_index == -1 or split_index < max_length * 0.5:
            split_index = max_length
        parts.append(text[:split_index].strip())
        text = text[split_index:].lstrip()
    if text:
        parts.append(text)
    return parts


def send_whatsapp_message(phone, message):
    """Sends a message to WhatsApp via 360dialog API."""
    payload = {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": message}}
    try:
        response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload, timeout=15)
        print(f"📤 WhatsApp response: {getattr(response, 'status_code', 'no_response')}")
        return response
    except Exception as e:
        print(f"❌ WhatsApp request error: {e}")
        return None


def get_gpt_response(user_msg, phone):
    """Gets a response from GPT and updates client state."""
    state = get_client_state(phone) # Use the new state manager function
    messages = build_messages_for_gpt(state, user_msg)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ GPT error: {e}")
        return "Кешіріңіз, қазір жауап бере алмаймын."

    # Determine next stage (capped at 6)
    try:
        next_stage_int = min(6, max(0, int(state["stage"])) + 1)
    except Exception:
        next_stage_int = 0
    next_stage = str(next_stage_int)

    # Update history and state using the new state manager function
    new_history = list(state["history"]) + [{"user": user_msg, "bot": reply}]
    save_client_state(
        phone,
        stage=next_stage,
        history=new_history,
        last_time=time.time(), # Update last_time
        followed_up=False      # Reset follow_up flag as we just responded
    )
    return reply


# ==============================
# Flask Routes
# ==============================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(silent=True) or {}
    print("📩 Incoming JSON:", data)

    try:
        entry = (data.get("entry") or [{}])[0]
        changes = (entry.get("changes") or [{}])[0]
        value = changes.get("value") or {}
        messages = value.get("messages")
        contacts = value.get("contacts", [])

        if not messages:
            print("INFO: No messages in webhook payload.")
            return jsonify({"status": "no_message"}), 200

        msg = messages[0]
        msg_id = msg["id"]

        # Deduplication check using in-memory set (resets on restart)
        if msg_id in PROCESSED_MESSAGES:
            print(f"⏩ Message {msg_id} already processed — skipping")
            return jsonify({"status": "duplicate"}), 200
        PROCESSED_MESSAGES.add(msg_id)

        # ✨ Применяем нормализацию к номеру из WhatsApp ✨
        user_phone = normalize_phone_number(msg.get("from")) 
        user_msg = (msg.get("text") or {}).get("body", "")

        print(f"DEBUG: Processing message from normalized phone: {user_phone}, message: {user_msg}")

        if not (user_phone and isinstance(user_msg, str) and user_msg.strip()):
            print(f"INFO: Ignored message from {user_phone} due to empty content or invalid format.")
            return jsonify({"status": "ignored"}), 200

        # Initialize lead if seen for the first time (uses new state manager)
        # client_in_db_or_cache уже внутри вызывает get_client_state, который нормализует
        if not client_in_db_or_cache(user_phone): # user_phone уже нормализован здесь
            name = "Клиент"
            if contacts and isinstance(contacts, list):
                profile = (contacts[0] or {}).get("profile") or {}
                name = profile.get("name", "Клиент")
            
            print(f"DEBUG: New client {user_phone} detected. Name: {name}. Processing new lead.")
            process_new_lead(name, user_phone) # user_phone передается нормализованным
        else:
            print(f"DEBUG: Client {user_phone} found in DB/Cache. Continuing existing conversation.")

        # Continue with bot logic
        reply = get_gpt_response(user_msg.strip(), user_phone) # user_phone передается нормализованным

        # Split and send WhatsApp message parts
        for part in split_message(reply):
            send_whatsapp_message(user_phone, part)

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"❌ Webhook error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/salesrender-hook', methods=['POST'])
def salesrender_hook():
    print("=== Incoming request to /salesrender-hook ===")
    try:
        data = request.get_json(silent=True) or {}
        print("Payload:", json.dumps(data, indent=2, ensure_ascii=False))

        # Handle various SalesRender webhook formats
        orders = (
            data.get("data", {}).get("orders")
            or data.get("orders")
            or [data] # Fallback if it's a single order object directly
        )

        if not orders or not isinstance(orders, list):
            return jsonify({"error": "No orders found or invalid format"}), 400

        # Process the first order (or loop if needed for multiple orders) in a separate thread
        threading.Thread(
            target=process_salesrender_order,
            args=(orders[0],),
            daemon=True
        ).start()

        return jsonify({"status": "accepted"}), 200
    except Exception as e:
        print(f"❌ Webhook parsing error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/', methods=['GET'])
def home():
    return "Healvix бот іске қосылды!", 200

# ==============================
# Application Startup - Moved outside if __name__ == "__main__" for Gunicorn
# ==============================

print("DEBUG: Starting application initialization (outside if __name__).") 
init_db() # Initialize the database
print("DEBUG: Database init_db() completed (outside if __name__).") 
load_cache_from_db() # Load all existing clients into cache
print("DEBUG: Cache loaded from DB (outside if __name__).") 

# Start background threads for follow-up and cleanup
# Pass send_whatsapp_message function as an argument to follow_up_checker
threading.Thread(target=follow_up_checker, args=(send_whatsapp_message,), daemon=True).start()
print("DEBUG: Follow-up checker thread started.")
threading.Thread(target=cleanup_old_clients, daemon=True).start()
print("DEBUG: Cleanup old clients thread started.")

# For local development, keep the if __name__ == "__main__" block
if __name__ == "__main__":
    print("DEBUG: Running app in local development mode via 'python app.py'.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
