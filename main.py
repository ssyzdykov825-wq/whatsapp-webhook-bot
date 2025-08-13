# main.py
import os
import time
import json
import requests
import psycopg2
from flask import Flask, request, jsonify
from openai import OpenAI
from salesrender_api import create_order, client_exists  # твои функции CRM

# ================== ENV ==================
DATABASE_URL    = os.environ.get("DATABASE_URL")       # postgres://user:pass@host:port/db
OPENAI_API_KEY  = os.environ.get("OPENAI_API_KEY")     # ключ OpenAI
WHATSAPP_API_KEY = os.environ.get("WHATSAPP_API_KEY")  # ключ 360dialog

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
HEADERS = {
    "Content-Type": "application/json",
    "D360-API-KEY": WHATSAPP_API_KEY
}

# ================== APP / GPT ==================
app = Flask(__name__)
client = OpenAI(api_key=OPENAI_API_KEY)

# ================== DB helpers ==================
def db_exec(sql, params=None, fetchone=False, fetchall=False):
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute(sql, params or [])
    data = None
    if fetchone:
        data = cur.fetchone()
    elif fetchall:
        data = cur.fetchall()
    conn.commit()
    cur.close()
    conn.close()
    return data

def init_db():
    # таблица для защиты от дублей
    db_exec("""
        CREATE TABLE IF NOT EXISTS processed_messages (
            id TEXT PRIMARY KEY
        );
    """)

    # таблица состояния пользователя
    db_exec("""
        CREATE TABLE IF NOT EXISTS user_state (
            phone        TEXT PRIMARY KEY,
            stage        TEXT DEFAULT '0',
            history      TEXT DEFAULT '[]',
            last_message TEXT,
            last_time    DOUBLE PRECISION,
            followed_up  BOOLEAN DEFAULT FALSE,
            in_crm       BOOLEAN DEFAULT FALSE
        );
    """)

    # исправляем типы BOOLEAN для старых колонок
    db_exec("""
DO $$
BEGIN
    -- followed_up
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name='user_state' AND column_name='followed_up' AND data_type<>'boolean'
    ) THEN
        ALTER TABLE user_state ALTER COLUMN followed_up DROP DEFAULT;
        ALTER TABLE user_state ALTER COLUMN followed_up TYPE BOOLEAN USING (followed_up::boolean);
        ALTER TABLE user_state ALTER COLUMN followed_up SET DEFAULT FALSE;
    END IF;

    -- in_crm
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name='user_state' AND column_name='in_crm' AND data_type<>'boolean'
    ) THEN
        ALTER TABLE user_state ALTER COLUMN in_crm DROP DEFAULT;
        ALTER TABLE user_state ALTER COLUMN in_crm TYPE BOOLEAN USING (in_crm::boolean);
        ALTER TABLE user_state ALTER COLUMN in_crm SET DEFAULT FALSE;
    END IF;
END $$;
""")  # <-- закрываем тройные кавычки для db_exec

init_db()

# ================== Utils ==================
def split_message(text, max_length=1000):
    parts = []
    text = text or ""
    while len(text) > max_length:
        split_index = text[:max_length].rfind(". ")
        if split_index == -1:
            split_index = max_length
        parts.append(text[:split_index+1].strip())
        text = text[split_index+1:].strip()
    if text:
        parts.append(text)
    return parts

def is_message_processed(msg_id: str) -> bool:
    row = db_exec("SELECT 1 FROM processed_messages WHERE id=%s;", (msg_id,), fetchone=True)
    return row is not None

def add_processed_message(msg_id: str):
    db_exec("INSERT INTO processed_messages (id) VALUES (%s) ON CONFLICT DO NOTHING;", (msg_id,))

# ================== User state ==================
def get_user_state(phone: str):
    row = db_exec("""
        SELECT stage, history, last_message, last_time, followed_up, in_crm
        FROM user_state WHERE phone=%s;
    """, (phone,), fetchone=True)
    if not row:
        return None
    stage, history_json, last_message, last_time, followed_up, in_crm = row
    try:
        history = json.loads(history_json or "[]")
    except Exception:
        history = []
    return {
        "stage": stage or "0",
        "history": history,
        "last_message": last_message,
        "last_time": last_time,
        "followed_up": bool(followed_up),
        "in_crm": bool(in_crm),
    }

def set_user_state(phone: str, stage, history, last_message, last_time, followed_up, in_crm=False):
    history_json = json.dumps(history or [])
    db_exec("""
        INSERT INTO user_state (phone, stage, history, last_message, last_time, followed_up, in_crm)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (phone) DO UPDATE SET
            stage=%s, history=%s, last_message=%s, last_time=%s, followed_up=%s, in_crm=%s;
    """, (
        phone, stage, history_json, last_message, last_time, bool(followed_up), bool(in_crm),
        stage, history_json, last_message, last_time, bool(followed_up), bool(in_crm)
    ))

# ================== CRM gate ==================
def process_new_lead(name: str, phone: str):
    """Проверяем локально и в CRM, создаём заказ если надо, ставим флаг in_crm=True."""
    state = get_user_state(phone)
    if state and state.get("in_crm"):
        print(f"⚠️ {phone} уже помечен как in_crm=True — пропуск")
        return None

    if client_exists(phone):
        print(f"⚠️ {phone} найден в CRM — отмечаем in_crm=True")
        set_user_state(phone, stage="0", history=[], last_message=None, last_time=None, followed_up=False, in_crm=True)
        return None

    order_id = create_order(name, phone)
    if order_id:
        print(f"✅ Заказ {order_id} создан для {name} ({phone})")
        set_user_state(phone, stage="0", history=[], last_message=None, last_time=None, followed_up=False, in_crm=True)
        return order_id
    else:
        print(f"❌ Не удалось создать заказ для {name} ({phone})")
        return None

# ================== WhatsApp (360dialog) ==================
def send_whatsapp_360(phone: str, message: str):
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "text",
        "text": {"body": message}
    }
    try:
        resp = requests.post(WHATSAPP_API_URL, headers=HEADERS, json=payload, timeout=30)
        print(f"📤 Ответ от 360dialog: {resp.status_code} {resp.text}")
        return resp
    except Exception as e:
        print(f"❌ Ошибка отправки в 360dialog: {e}")

# ================== GPT core ==================
SALES_SCRIPT_PROMPT = "Ты вежливый ассистент отдела продаж. Отвечай кратко и по делу."
STAGE_PROMPTS = {
    "0": "Поздоровайся и уточни задачу.",
    "1": "Уточни детали заявки и бюджет.",
    "2": "Предложи следующий шаг: звонок или оформление.",
    "3": "Напомни про выгоды и дедлайн.",
    "4": "Закрой на действие.",
    "5": "Поблагодари и закрепи договоренности.",
    "6": "Диалог завершён, вежливо отвечай коротко."
}

def get_gpt_response(user_msg: str, user_phone: str) -> str:
    # Получаем текущее состояние пользователя
    user_data = get_user_state(user_phone) or {
        "history": [],
        "stage": "0",
        "last_message": None,
        "last_time": None,
        "followed_up": False,
        "in_crm": False
    }

    history = user_data["history"]
    stage = user_data["stage"]

    # Формируем системный prompt с учётом текущего stage
    prompt = SALES_SCRIPT_PROMPT + "\n\n" + STAGE_PROMPTS.get(stage, "")

    # Собираем историю для GPT
    messages = [{"role": "system", "content": prompt}]
    for item in history[-20:]:
        if "user" in item:
            messages.append({"role": "user", "content": item["user"]})
        if "bot" in item:
            messages.append({"role": "assistant", "content": item["bot"]})
    messages.append({"role": "user", "content": user_msg})

    # Запрос к GPT
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=messages,
        temperature=0.7
    )
    reply = resp.choices[0].message.content.strip()

    # Умная логика перехода stage
    next_stage = stage

    if stage == "0":
        # Если приветствие прошло и есть конкретный вопрос/запрос
        if any(word in user_msg.lower() for word in ["цена", "стоимость", "услуга", "оформить"]):
            next_stage = "1"
    elif stage == "1":
        # Если пользователь дал детали заявки или бюджет
        if any(word in user_msg.lower() for word in ["хочу", "заказать", "оформить"]):
            next_stage = "2"
    elif stage == "2":
        # Продолжаем по сценарию, например после звонка или предложения
        next_stage = "3"  # пример, можно усложнить
    # stage 3–6 можно менять аналогично по бизнес-логике

    # Сохраняем историю (до 20 последних пар)
    new_history = (history + [{"user": user_msg, "bot": reply}])[-20:]
    set_user_state(
        phone=user_phone,
        stage=next_stage,
        history=new_history,
        last_message=user_msg,
        last_time=time.time(),
        followed_up=False,
        in_crm=user_data.get("in_crm", False)
    )

    return reply
    
# ================== Webhook (360dialog формат входящих) ==================
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Келген JSON:", data)

    try:
        entry = data.get("entry", [])[0]
        change = entry.get("changes", [])[0]
        value = change.get("value", {})

        # пропускаем статусы (sent/delivered/read)
        if value.get("statuses") and not value.get("messages"):
            return jsonify({"status": "status_event"}), 200

        messages = value.get("messages", [])
        contacts = value.get("contacts", [])

        if not messages:
            return jsonify({"status": "no_message"}), 200

        msg = messages[0]
        msg_id = msg["id"]

        # проверка на дубль
        if is_message_processed(msg_id):
            print(f"⏩ Сообщение {msg_id} уже обработано — пропускаем")
            return jsonify({"status": "duplicate"}), 200
        add_processed_message(msg_id)

        # поддерживаем только текст
        if msg.get("type") != "text":
            print("⚠️ Неподдерживаемый тип:", msg.get("type"))
            return jsonify({"status": "unsupported_type"}), 200

        user_phone = msg["from"]
        user_msg = msg["text"]["body"]
        full_name = contacts[0]["profile"].get("name", "Клиент") if contacts else "Клиент"

        # нормализуем номер (для единообразия)
        norm_phone = user_phone.replace("+", "").replace(" ", "").replace("-", "")

        # получаем текущее состояние пользователя
        user_state = get_user_state(norm_phone)
        if not user_state:
            # новый клиент — создаём заказ в CRM
            order_id = process_new_lead(full_name, norm_phone)
            if order_id:
                print(f"✅ Новый заказ {order_id} создан ({full_name}, {norm_phone})")
            else:
                print(f"ℹ️ Клиент {norm_phone} уже есть в CRM или заказ не создан")
            # стартовое состояние, history пустая
            set_user_state(
                norm_phone,
                stage="0",
                history=[],
                last_message=None,
                last_time=None,
                followed_up=False,
                in_crm=True
            )
        else:
            # уже есть состояние — используем существующую stage и историю
            print(f"ℹ️ Клиент {norm_phone} уже в базе, stage={user_state['stage']}, история длина={len(user_state['history'])}")

        # получаем ответ GPT с учётом истории
        reply = get_gpt_response(user_msg, norm_phone)

        # отправка в WhatsApp (если длинное, режем на части)
        for part in split_message(reply):
            send_whatsapp_360(norm_phone, part)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route('/', methods=['GET'])
def health():
    return 'ok', 200

# ================== Run ==================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
