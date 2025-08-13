import os
import time
import threading
import requests
import json
import re
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

# ✨ ИМПОРТИРУЕМ ВАШИ РЕАЛЬНЫЕ ФУНКЦИИ SALESRENDER API - ПРЕДПОЛАГАЕТСЯ, ЧТО ОНИ РАБОТАЮТ КОРРЕКТНО ✨
from salesrender_api import create_order, client_exists 


# ==============================
# Конфигурация
# ==============================
app = Flask(__name__)
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY") # Убедитесь, что это установлено как переменная окружения

HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

# Кэш в оперативной памяти для дедупликации ID сообщений (сбрасывается при перезапуске приложения)
PROCESSED_MESSAGES = set()

# Конфигурация SalesRender CRM (используется и в salesrender_api.py, но оставлена здесь для полноты, если нужна в других местах)
# Убедитесь, что ваш salesrender_api.py использует эти значения или свой метод для конфигурации.
SALESRENDER_URL = os.environ.get("SALESRENDER_URL", "https://de.backend.salesrender.com/companies/1123/CRM")
SALESRENDER_TOKEN = os.environ.get("SALESRENDER_TOKEN", "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc")

# ==============================
# Нормализация номера телефона
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
    if not phone_digits.startswith('7') and len(phone_digits) == 10: 
        phone_digits = '7' + phone_digits
    
    # Добавляем '+' в начало, если его нет
    if not phone_digits.startswith('+'):
        return '+' + phone_digits
    
    return phone_digits

# ==============================
# Утилиты SalesRender
# ==============================
# Примечание: create_order и client_exists теперь импортируются из salesrender_api.py
# Убедитесь, что ваш salesrender_api.py корректно реализует fetch_order_from_crm, если это необходимо.

def fetch_order_from_crm(order_id):
    """Извлекает детали заказа из SalesRender CRM с помощью GraphQL."""
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
        response.raise_for_status() # Вызывает HTTPError для плохих ответов (4xx или 5xx)
        data = response.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
        return data[0] if data else None
    except Exception as e:
        print(f"❌ Ошибка получения из CRM: {e}")
        return None

def process_new_lead(name, phone):
    """
    Регистрирует нового лида во внутренней БД бота и создает заказ в CRM, если это необходимо.
    Эта функция теперь предназначена ТОЛЬКО для управления внутренней БД бота после проверки в CRM.
    """
    # Эта проверка в основном для внутренней БД бота, а не для статуса CRM для первоначального решения вебхука
    if client_in_db_or_cache(phone):
        print(f"⚠️ Клиент {phone} уже в базе/кэше (в process_new_lead), пропускаем создание/обновление.")
        return None 

    # Если мы дошли сюда, клиент новый для БД бота.
    # Теперь снова проверяем CRM, чтобы решить, нужно ли создавать заказ.
    # Примечание: Это важная проверка, потому что client_exists мог быть True ранее,
    # что привело к ответу, но клиента все еще нужно добавить в БД бота.
    crm_exists_status = client_exists(phone) # Вызываем реальную функцию client_exists здесь

    if crm_exists_status:
        # Клиент существует в CRM, но новый для БД бота. Просто добавляем в БД бота, не создавая новый заказ.
        print(f"DEBUG: Клиент {phone} найден в CRM, но новый для БД бота. Сохраняем в БД бота с in_crm=True.")
        save_client_state(phone, name=name, in_crm=True)
        return None # Новый заказ не создан
    else:
        # Клиент НЕ найден в CRM (и новый для БД бота). Создаем заказ.
        print(f"DEBUG: Клиент {phone} НЕ найден в CRM. Создаем заказ и сохраняем в БД бота.")
        order_id = create_order(name, phone) # Вызываем реальную функцию create_order

        if order_id:
            print(f"✅ Заказ {order_id} создан для {name}, {phone}. Обновляем состояние в боте.")
            save_client_state(phone, name=name, in_crm=True)
            return order_id
        else:
            print(f"❌ Не удалось создать заказ для {name}, {phone}. Создаем запись клиента без CRM связи в боте.")
            save_client_state(phone, name=name, in_crm=False)
            return None


def process_salesrender_order(order):
    """
    Обрабатывает вебхук заказа SalesRender. Обновляет состояние клиента и отправляет сообщение менеджеру.
    """
    try:
        # --- (Существующий код для парсинга данных заказа и нормализации телефона) ---
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
            phone = normalize_phone_number(order.get("customer", {}).get("phone", {}).get("raw", "").strip())
        else:
            human_fields = order.get("data", {}).get("humanNameFields", [])
            phone_fields = order.get("data", {}).get("phoneFields", [])
            if human_fields:
                first_name = human_fields[0].get("value", {}).get("firstName", "").strip()
                last_name = human_fields[0].get("value", {}).get("lastName", "").strip()
            if phone_fields:
                phone = normalize_phone_number(phone_fields[0].get("value", {}).get("international", "").strip())

        name = f"{first_name} {last_name}".strip() or "Клиент"

        if not phone:
            print("❌ Телефон отсутствует — пропуск")
            return
        # --- (Конец существующего кода парсинга) ---

        # ✨ ИЗМЕНЕННАЯ ЛОГИКА ЗДЕСЬ ✨
        # Всегда обновляем состояние клиента во внутренней БД бота, независимо от того, новый он или известный.
        # Это гарантирует, что БД бота всегда актуальна со статусом CRM.
        # Это заменяет старый блок `if client_in_db_or_cache(phone): ... return`.
        if not client_in_db_or_cache(phone):
            # Клиент новый для БД бота (пришел из вебхука SalesRender).
            # Мы предполагаем, что если SalesRender отправляет вебхук, клиент неявно находится в CRM.
            print(f"ℹ️ Клиент {phone} новый для базы бота (из вебхука SalesRender), добавляем.")
            save_client_state(phone, name=name, in_crm=True)
        else:
            # Клиент уже известен БД бота. Просто убедимся, что его статус CRM обновлен (он должен быть true из хука CRM).
            print(f"ℹ️ Клиент {phone} уже известен боту, обновляем его CRM статус.")
            save_client_state(phone, name=name, in_crm=True) # Убедимся, что in_crm=True


        # Логика сообщения менеджеру (эта часть теперь ВСЕГДА будет выполняться, если вебхук содержит телефон)
        now = datetime.utcnow()
        # last_sent по-прежнему в памяти для целей ограничения частоты (сбрасывается при перезапуске приложения)
        # Примечание: last_sent - это in-memory dict, и оно не сохраняется при перезапусках.
        # Если вы хотите, чтобы это ограничение частоты было персистентным, его нужно перенести в БД.
        global last_sent # Объявляем last_sent как глобальную переменную
        if phone not in last_sent: # Инициализация, если ключа нет
            last_sent[phone] = datetime.fromtimestamp(0) # Устанавливаем очень старое время, чтобы первое сообщение прошло

        if now - last_sent[phone] < timedelta(minutes=3):
            print(f"⚠ Повторный недозвон по {phone} — пропускаем отправку менеджеру из-за ограничения частоты.")
            return # Этот return по-прежнему хорош для ограничения частоты

        # Определяем приветствие (UTC+6)
        now_kz = now + timedelta(hours=6)
        if 5 <= now_kz.hour < 12:
            greeting = "Қайырлы таң"
        elif 12 <= now_kz.hour < 18:
            greeting = "Сәлеметсіз бе"
        else:
            greeting = "Қайырлы кеш"

        # Генерируем сообщение через GPT
        try:
            # Для доступа к истории/стадии для GPT, если необходимо, явно загружаем состояние
            current_client_state = get_client_state(phone) 
            
            # Корректируем промпт для сценария "недозвон", если данные вебхука содержат такой статус
            # Предполагаем, что поле 'status' или аналогичное может существовать в полезной нагрузке вебхука,
            # хотя оно не видно в предоставленном вами примере полезной нагрузки.
            # Пока используем вашу существующую структуру промпта.
            if name and name != "Клиент":
                # Этот промпт подразумевает уведомление CRM о пропущенном звонке.
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
            print(f"❌ Ошибка GPT: {e}")
            message_text = f"{greeting}! Біз сізге қоңырау шалдық, бірақ байланыс болмады. Уақытыңыз болса, хабарласыңыз."

        # Отправляем в WhatsApp
        send_whatsapp_message(phone, message_text)

        # Запоминаем отправку
        last_sent[phone] = now
        print(f"✅ Сообщение отправлено на {phone}")

    except Exception as e:
        print(f"❌ Ошибка обработки заказа: {e}")
        import traceback
        traceback.print_exc() # Добавляем трассировку стека для полной информации об ошибке

# Словарь в памяти для ограничения частоты сообщений менеджеру (сбрасывается при перезапуске приложения)
last_sent = {} # Инициализируем здесь
# ==============================
# Промпты GPT (уточненные)
# ==============================
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

def build_messages_for_gpt(state, user_msg):
    """Строит сообщения для GPT, используя последние N сообщений из истории + текущую стадию."""
    prompt = SALES_SCRIPT_PROMPT + "\n\n" + STAGE_PROMPTS.get(state["stage"], "")
    messages = [{"role": "system", "content": prompt}]

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
    """Разделяет длинные тексты по предложениям или новым строкам для WhatsApp."""
    parts = []
    text = text.strip()
    while len(text) > max_length:
        split_index = max(text[:max_length].rfind("\n"), text[:max_length].rfind(". "))
        if split_index == -1 or split_index < max_length * 0.5:
            split_index = max_length
        parts.append(text[:split_index].strip())
        text = text[split_index:].lstrip()
    if text:
        parts.append(text)
    return parts


def send_whatsapp_message(phone, message):
    """Отправляет сообщение в WhatsApp через 360dialog API."""
    payload = {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"body": message}}
    try:
        response = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload, timeout=15)
        print(f"📤 Ответ WhatsApp: {getattr(response, 'status_code', 'нет_ответа')}")
        return response
    except Exception as e:
        print(f"❌ Ошибка запроса WhatsApp: {e}")
        return None


def get_gpt_response(user_msg, phone):
    """Получает ответ от GPT и обновляет состояние клиента."""
    state = get_client_state(phone)
    messages = build_messages_for_gpt(state, user_msg)

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.7
        )
        reply = response.choices[0].message.content.strip()
    except Exception as e:
        print(f"❌ Ошибка GPT: {e}")
        return "Кешіріңіз, қазір жауап бере алмаймын."

    try:
        next_stage_int = min(6, max(0, int(state["stage"])) + 1)
    except Exception:
        next_stage_int = 0
    next_stage = str(next_stage_int)

    new_history = list(state["history"]) + [{"user": user_msg, "bot": reply}]
    save_client_state(
        phone,
        stage=next_stage,
        history=new_history,
        last_time=time.time(),
        followed_up=False
    )
    return reply


# ==============================
# Маршруты Flask
# ==============================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json(silent=True) or {}
    print("📩 Входящий JSON:", data)

    try:
        entry = (data.get("entry") or [{}])[0]
        changes = (entry.get("changes") or [{}])[0]
        value = changes.get("value") or {}
        messages = value.get("messages")
        contacts = value.get("contacts", [])

        if not messages:
            print("INFO: Нет сообщений в полезной нагрузке вебхука.")
            return jsonify({"status": "no_message"}), 200

        msg = messages[0]
        msg_id = msg["id"]

        if msg_id in PROCESSED_MESSAGES:
            print(f"⏩ Сообщение {msg_id} уже обработано — пропускаем")
            return jsonify({"status": "duplicate"}), 200
        PROCESSED_MESSAGES.add(msg_id)

        user_phone = normalize_phone_number(msg.get("from")) 
        user_msg = (msg.get("text") or {}).get("body", "")

        print(f"DEBUG: Обрабатываем сообщение от нормализованного телефона: {user_phone}, сообщение: {user_msg}")

        if not (user_phone and isinstance(user_msg, str) and user_msg.strip()):
            print(f"INFO: Сообщение от {user_phone} проигнорировано из-за пустого содержимого или неверного формата.")
            return jsonify({"status": "ignored"}), 200

        # --- НОВАЯ ЛОГИКА ДЛЯ ПРОВЕРКИ CRM И ТИХОЙ РЕГИСТРАЦИИ ---
        should_send_bot_reply = False # По умолчанию НЕ отвечаем на первый контакт

        # Получаем имя из контактов, если доступно (используется для регистрации в CRM, если клиент новый)
        name = "Клиент" 
        if contacts and isinstance(contacts, list):
            profile = (contacts[0] or {}).get("profile") or {}
            name = profile.get("name", "Клиент")

        # 1. Проверяем, существует ли клиент во внутренней БД/кэше бота (приоритет быстрому поиску)
        client_in_bot_db = client_in_db_or_cache(user_phone)

        if client_in_bot_db:
            # Клиент известен внутренней БД бота (либо из предыдущего взаимодействия, либо из хука SalesRender).
            # Всегда отвечаем.
            print(f"DEBUG: Клиент {user_phone} найден в БД бота. Продолжаем диалог.")
            should_send_bot_reply = True
        else:
            # Клиент НЕ известен внутренней БД бота. Это потенциальное первое взаимодействие для бота.
            # Теперь проверяем CRM SalesRender, используя ВАШУ работающую функцию client_exists.
            crm_already_exists = client_exists(user_phone) 

            if crm_already_exists:
                # Клиент найден в CRM, но НОВЫЙ для внутренней БД бота.
                # Добавляем в БД бота, а затем отвечаем.
                print(f"DEBUG: Клиент {user_phone} НАЙДЕН в CRM, но НОВЫЙ для БД бота. Добавляем в БД бота и отвечаем.")
                # Здесь не нужно вызывать create_order, так как клиент уже существует в CRM.
                save_client_state(user_phone, name=name, in_crm=True) # Убедимся, что 'in_crm' установлено в True
                should_send_bot_reply = True
            else:
                # Клиент НЕ найден в CRM, и НОВЫЙ для внутренней БД бота.
                # Тихо регистрируем в CRM (через process_new_lead) и в БД бота.
                print(f"DEBUG: Клиент {user_phone} НЕ найден в CRM и НОВЫЙ для БД бота. Тихо регистрируем лида.")
                process_new_lead(name, user_phone) # Это вызывает ваш create_order и сохраняет в БД бота.
                should_send_bot_reply = False # Бот остается без немедленного ответа для этого первого взаимодействия
        
        # Окончательное решение об отправке ответа
        if should_send_bot_reply:
            reply = get_gpt_response(user_msg.strip(), user_phone)
            for part in split_message(reply):
                send_whatsapp_message(user_phone, part)
        else:
            print(f"DEBUG: Тихо обработан новый клиент {user_phone}. Немедленный ответ бота не отправлен.")

        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print(f"❌ Ошибка вебхука: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/salesrender-hook', methods=['POST'])
def salesrender_hook():
    print("=== Входящий запрос на /salesrender-hook ===")
    try:
        data = request.get_json(silent=True) or {}
        print("Полезная нагрузка:", json.dumps(data, indent=2, ensure_ascii=False))

        orders = (
            data.get("data", {}).get("orders")
            or data.get("orders")
            or [data] # Запасной вариант, если это один объект заказа напрямую
        )

        if not orders or not isinstance(orders, list):
            return jsonify({"error": "Заказы не найдены или неверный формат"}), 400

        # Обрабатываем первый заказ (или циклически, если нужно для нескольких заказов) в отдельном потоке
        threading.Thread(
            target=process_salesrender_order,
            args=(orders[0],),
            daemon=True
        ).start()

        return jsonify({"status": "accepted"}), 200
    except Exception as e:
        print(f"❌ Ошибка парсинга вебхука: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/', methods=['GET'])
def home():
    return "Healvix бот іске қосылды!", 200

# ==============================
# Запуск приложения - Перенесен за пределы if __name__ == "__main__" для Gunicorn
# ==============================

print("DEBUG: Запуск инициализации приложения (вне if __name__).")
init_db() # Инициализируем базу данных
print("DEBUG: init_db() базы данных завершено (вне if __name__).")
load_cache_from_db() # Загружаем всех существующих клиентов в кэш
print("DEBUG: Кэш загружен из БД (вне if __name__).")

# Запускаем фоновые потоки для follow-up и очистки
threading.Thread(target=follow_up_checker, args=(send_whatsapp_message,), daemon=True).start()
print("DEBUG: Поток проверки follow-up запущен.")
threading.Thread(target=cleanup_old_clients, daemon=True).start()
print("DEBUG: Поток очистки старых клиентов запущен.")

if __name__ == "__main__":
    print("DEBUG: Приложение запущено в режиме локальной разработки через 'python app.py'.")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
