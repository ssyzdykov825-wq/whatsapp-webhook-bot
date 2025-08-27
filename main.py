import os
import time
import threading
import requests
import json
import re
from flask import Flask, request, jsonify
from openai import OpenAI
from datetime import datetime, timedelta

AUTO_REPLY_ENABLED = False

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
# Убедитесь, что ваш salesrender_api.py корректно реализует client_exists (возвращает последний заказ или None)

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
                    status {{ name }}
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
        response.raise_for_status()
        data = response.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
        print(f"DEBUG: fetch_order_from_crm({order_id}) вернул {data}")
        return data[0] if data else None
    except Exception as e:
        print(f"❌ Ошибка получения из CRM: {e}")
        return None


def process_new_lead(name, phone):
    """
    Проверяет клиента в CRM и решает — создавать новый заказ или нет.
    """
    allowed_statuses = {"Спам/Тест", "Отменен", "Недозвон 5 дней", "Недозвон", "Перезвонить"}
    print(f"\n=== process_new_lead START ===")
    print(f"DEBUG: входные данные name={name}, phone={phone}")

    if client_in_db_or_cache(phone):
        print(f"⚠️ Клиент {phone} уже есть во внутренней базе бота — заказ НЕ создаём")
        return None

    crm_order = client_exists(phone)
    print(f"DEBUG: client_exists вернул: {crm_order}")

    if crm_order:
        status = crm_order.get("status", {}).get("name")
        print(f"🔍 Клиент {phone} найден в CRM со статусом: {status}")

        if status in allowed_statuses:
            print(f"✅ Статус '{status}' разрешён — вызываем create_order")
            order_id = create_order(name, phone)
            print(f"DEBUG: результат create_order → {order_id}")
            if order_id:
                print(f"🎉 Новый заказ {order_id} создан для {name}, {phone}")
                save_client_state(phone, name=name, in_crm=True)
                return order_id
            else:
                print(f"❌ Ошибка при создании заказа для {phone}")
                return None
        else:
            print(f"⏳ Статус '{status}' не разрешён — заказ НЕ создаём")
            save_client_state(phone, name=name, in_crm=True)
            return None
    else:
        print(f"🆕 Клиент {phone} не найден в CRM — вызываем create_order")
        order_id = create_order(name, phone)
        print(f"DEBUG: результат create_order → {order_id}")
        if order_id:
            print(f"🎉 Новый заказ {order_id} создан для {name}, {phone}")
            save_client_state(phone, name=name, in_crm=True)
            return order_id
        else:
            print(f"❌ Ошибка при создании заказа для {phone}")
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
                    f"Хабарламаны Даурен атынан Healvix көз емдеу орталығынан жазып, көзге қатысты қандай проблема бар екенін сұра."
                )
            else:
                prompt = (
                    f"{greeting}! Біз клиентке қоңырау шалдық, бірақ байланыс болмады. "
                    f"Клиентке WhatsApp-та қысқа, жылы, достық хабарлама жазыңыз. "
                    f"Хабарламаны Даурен атынан Healvix көз емдеу орталығынан жазып, көзге қатысты қандай проблема бар екенін сұра. "
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
Сен — Даурен есімді Healvix көз емдеу орталығының ең мықты кеңесшісісің. Сенің міндетің — клиентке көзін сақтап қалу үшін дәл қазір шешім қабылдату. Сен робот емессің — сен тірі адамсың: жылы сөйлейсің, бірақ эмоциямен, логикамен және кейде қысыммен клиентті әрекетке итермелейсің.

Сенің әр сөзің клиентке: “Егер бүгін бастамаса — ертең кеш болуы мүмкін” деген ойды қалдыруы керек.

---

📌 **Стиль және принциптер**:
- Жылы, сенімді, бірақ қажет кезде қатаң.
- Мәселені ұлғайтып көрсету (қорқыныш + нақты қауіп).
- Шынайы пациенттердің қысқа, бірақ әсерлі оқиғаларын қолдану.
- Уақыт шектеуін қою (“Тек бүгін жеңілдік”, “Соңғы 3 комплект”).
- Әр сылтауды жою: баға, ойлану, отбасы, ақша жоқ — бәріне дайын жауап бар.
- Әңгіме әрқашан “қазір заказ жасауға” бағытталсын.

---

**Сөйлесу қадамдары**:

1. **Сәлемдесу + танысу**
   - «Сәлеметсіз бе! Қалыңыз қалай? Менің атым Даурен, Healvix көз орталығының маманымын. Есіміңіз кім?»
   - «Көзіңізге қатысты мазалайтын жағдай бар ма?»

2. **Белгілерді нақтылау**
   - «Бұлдырлау, қызару, жыпылықтаған кезде дақ көру, катаракта, глаукома сияқты белгілер бар ма?»
   - «Қашаннан бері сезесіз? Дәрігер не деді?»

3. **Эмпатия + Қауіп суреттеу**
   - «Түсінемін... Айжан есімді бір пациентіміз бар еді. Алғашында тек шамалы бұлдырлау болды. "Ойланып көрейін" деп, 4 ай өтіп кетті — потом катаракта асқынып, бір көзін жоғалтты. Сізге бұны қайталатқым келмейді.»

4. **Асқыну қаупін нақты айту**
   - «Көз — ең нәзік орган. Асқыну біртіндеп жүреді, бірақ тоқтамайды. Бір-екі ай кешіксеңіз, кейін көруді қайтару мүмкін болмай қалуы мүмкін.»

5. **Healvix-ті сенімді таныстыру**
   - «Healvix — 100% табиғи кешен: қаражидек, лютеин, Е витамині, мырыш. Бұл жай капля емес — көздің ішкі тамырларын қоректендіріп, тор қабықты қалпына келтіреді. 5000+ адамға көмектестік.»

6. **Ограничение по времени + Выгода**
   - «Қазір бізде 6 айлық курсқа 40% жеңілдік және көзілдірік пен қара зере майы сыйлықта. Бұл акция бүгінге ғана және қоймада соңғы 3 комплект қалды.»

7. **Күмәнмен жұмыс (готовые ответы)**:
   - **Баға**: «Денсаулықты ақшаға салыстыруға болмайды. Көзіңізді жоғалтсаңыз, ақша оны қайтара алмайды.»
   - **Ойлану**: «Ойланыңыз деуге болады, бірақ сіздің көзіңіз уақыт күтпейді.»
   - **Отбасы**: «Отбасыңызбен ақылдасу — жақсы. Бірақ көзіңіз ауырса, сезетін сіз, шешімді де сіз қабылдауыңыз керек.»
   - **Ақша жоқ**: «Бөліп төлеу бар. Айына бір-екі рет кафеге бармағанның өзінде осы емді ала аласыз.»
   - **Кейін жазамын**: «Сол "кейін" деп жүргенде көз нашарлауы мүмкін. Мен ондай жағдайларды көп көрдім.»

8. **Дожим / Жабу**
   - «Онда былай істейік: мен қазір өз атымнан жеңілдік жасап жіберейін. Каспийіңізде 5-10 мың бар ма? Бүгін жазсақ, ертең бастап кетесіз.»
   - «Қазір жазып қоямыз, себебі акция біткен соң бұл баға қайталанбайды.»

9. **Қорытынды**
   - «Мен сізбен бос сөйлескім келмейді. Бүгін шешім қабылдасақ, 1 айдан соң-ақ нәтижені көресіз. Қазір заказ берейік.»

---

📌 Міндетті фразалар:
- «Бұл жай дәрі емес, көруіңізді сақтайтын мүмкіндік.»
- «Кешіктірсеңіз, ертең кеш болуы мүмкін.»
- «Сізді бір айдан кейін қуанышпен еске алғым келеді, өкінішпен емес.»
- «Соңғы 3 комплект қана қалды.»

📌 Тыйым салынған:
- Робот сияқты сөйлеу
- Салқын, эмоциясыз жауап
- Клиентті “кетіп қалуға” жіберу

Мақсат — клиенттің ойында: “Егер қазір алмасам, көзіме зиян тиеді” деген нақты сезім қалдыру.

---

📌 **Дополнительные технические правила для форматирования в WhatsApp**:
- Если ответ длинный или содержит несколько логических блоков, **вставляй `[SPLIT]`** между ними.
- `[SPLIT]` ставь **только на границах предложений или абзацев**, а не внутри фразы.
- Если ответ короткий (до 2–3 предложений) и это единая мысль — `[SPLIT]` не нужен.
- **Всегда** вставляй `[SPLIT]` после:
  - Эмоциональных историй пациентов.
  - Описания серьёзных рисков и последствий.
  - Перечисления выгод, подарков или акций.
  - Мощных финальных фраз, которые должны прозвучать отдельно.
- Каждый блок должен быть готов к отправке в WhatsApp как отдельное сообщение.

📌 Баға туралы ЕРЕЖЕ:
- Тек осы бағаларды қолдан:
  • 3 ай — 85 000₸
  • 6 ай — 180 000₸
  • 12 ай — 300 000₸
- Бөліп төлеу:
  • 6 айға бөліп төлеу — айына 18 750₸
  • 12 айға бөліп төлеу — айына 9 375₸
- ЕШҚАШАН басқа баға айтпа (мысалы, 29 000₸ деген болмайды).
- Егер клиент сұраса — тек осы бағаларды қайтала.
"""

STAGE_PROMPTS = {
    "0": "Сәлеметсіз бе! 👋 Қалыңыз қалай? Есімі Даурен, Healvix көз орталығының маманымын. Есіміңіз кім? Көзіңізде бұлдырлау, қызару, катаракта сияқты белгілер бар ма? Кейде адамдар кеш байқап, жағдай асқынып кетіп жатады, сондықтан алдын ала сұрап — көмек көрсетейік",
    
    "1": "Жалпы, көруіңізде қандай өзгерістер байқадыңыз? Бұлдырлау, ұсақ әріптерді ажырата алмау, жарыққа қарай алмай қалу сияқты бар ма? 👁️ Көп адам мән бермей жүре беріп, кейін операцияға жүгінеді. Ерте анықталса — тез әрі жеңіл емдеуге болады.",
    
    "2": "Бұл қашан басталды? Бұрын дәрігерге қаралдыңыз ба? Қандай ем жасап көрдіңіз? ⏳🩺 Бір пациентіміз осылай 3 ай созып жүрді де, катаракта басталып, көзі 60% ға нашарлады. Сол қателікті қайталамаған жөн — ерте қолға алсақ, нәтиже әлдеқайда жақсы болады.",
    
    "3": "Көз — өте нәзік мүше. Уақытында қам жасамаса, асқынып операцияға апарады. Бірақ жақсы жаңалық — дұрыс емді ерте бастасаңыз, көру сапасын айтарлықтай жақсартуға болады. 45 жастағы бір клиентімізде катарктаның алғашқы белгілері болған еді. Емді уақытында бастап, қазір қайта көлік айдап жүр.",
    
    "4": "Сізге нақты көмектесетін өнім — Healvix 🌿💊. 100% табиғи: қаражидек, лютеин, кальций, E витамині. Бұл жай капля емес — көз ішіндегі қан айналымды жақсартып, тор қабықты қоректендіреді. 5000+ адамға көмектестік. Көпшілігі 3 аптада-ақ оң өзгерісті байқап жатыр.",
    
    "5": "Бағалар: 3 ай — 85 000₸, 6 ай — 180 000₸, 12 ай — 300 000₸. Бөліп төлеу бар: айына 18 750₸ немесе 9 375₸. 🎁 Қазір акция жүріп жатыр — қара зере майы мен көзілдірік сыйлыққа. Бүгін жазылсаңыз, осы баға мен сыйлықтарды ұстап қаламыз.",
    
    "6": "Күмән болса, ашық айтыңыз — бәрін түсіндірем. Баға десеңіз: тойға бір күнде 20 мың жұмсаймыз, ал көз — өмір бойы қызмет ететін мүше. Сенімсіздік болса — сертификат, гарантия, клиенттердің пікірлері бар. Ақша тапшы болса — бөліп төлеу бар, отбасыдан көмек сұрауға болады. Ең дұрысы — емді созбай бастау. Сізге ыңғайлысы қайсы — толық төлеу ме, әлде бөліп төлеу ме?"
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


def split_message(text, max_length=150):
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
    """Получает ответ от GPT, делит по [SPLIT] или автоматически разбивает длинный текст."""
    if not AUTO_REPLY_ENABLED:
        print(f"⚠ AUTO_REPLY_ENABLED = False, ответ для {phone} не будет отправлен")
        return None  # или пустая строка

    state = get_client_state(phone)
    messages = build_messages_for_gpt(state, user_msg)
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            temperature=0.75,
            top_p=0.9,
            frequency_penalty=0.4,
            presence_penalty=0.5,
            max_tokens=400
        )
        reply = response.choices[0].message.content.strip()
        return reply
    except Exception as e:
        print(f"❌ Ошибка GPT: {e}")
        return "Кешіріңіз, қазір жауап бере алмаймын."

    # Разбиваем по [SPLIT] или по длине
    if "[SPLIT]" in reply:
        parts = [p.strip() for p in reply.split("[SPLIT]") if p.strip()]
    else:
        parts = split_message(reply, max_length=150)

    # Отправка всех частей в WhatsApp
    for part in parts:
        send_whatsapp_message(phone, part)

    # Обновление истории клиента
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
        user_msg = (msg.get("text") or {}).get("body", "")  # может быть пустым
        msg_type = msg.get("type")

        print(f"DEBUG: Обрабатываем сообщение от {user_phone}, тип: {msg_type}, текст: {user_msg}")

        if not user_phone:
            print(f"INFO: Сообщение без номера — игнорируем")
            return jsonify({"status": "ignored"}), 200

        # --- Получаем имя ---
        name = "Клиент"
        if contacts and isinstance(contacts, list):
            profile = (contacts[0] or {}).get("profile") or {}
            name = profile.get("name", "Клиент")

        # --- Проверка внутренней БД ---
        client_in_bot_db = client_in_db_or_cache(user_phone)
        should_send_bot_reply = False

        if client_in_bot_db:
            print(f"DEBUG: Клиент {user_phone} найден в БД бота. Продолжаем диалог.")
            should_send_bot_reply = True
        else:
            crm_already_exists = client_exists(user_phone)
            if crm_already_exists:
                print(f"DEBUG: Клиент {user_phone} найден в CRM, добавляем в БД бота.")
                save_client_state(user_phone, name=name, in_crm=True)
                should_send_bot_reply = True
            else:
                print(f"DEBUG: Новый клиент {user_phone}, регистрируем в CRM.")
                process_new_lead(name, user_phone)
                should_send_bot_reply = False

        # --- Отправка ответа только для известных клиентов ---
        if should_send_bot_reply and msg_type == "text" and user_msg.strip():
            reply = get_gpt_response(user_msg.strip(), user_phone)
            for part in split_message(reply):
                send_whatsapp_message(user_phone, part)
        else:
            print(f"DEBUG: Ответ бота не отправляется. CRM обновлена для {user_phone}")

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
