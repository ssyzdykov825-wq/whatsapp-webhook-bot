import requests
from flask import Flask, request, jsonify
import traceback
import json

# --- Настройки SalesRender ---
# !!! ВНИМАНИЕ: ЗАМЕНИТЕ ЭТИ ДАННЫЕ НА СВОИ АКТУАЛЬНЫЕ !!!
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZWRlbnJkZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

# Создаем приложение Flask здесь, так как весь код находится в одном файле.
app = Flask(__name__)

# --- Внутренняя база данных (заглушка) ---
# Для примера используем словарь в памяти.
# В реальном приложении это должна быть настоящая база данных.
IN_MEMORY_DB = {}

def normalize_phone_number(phone):
    """Простая функция нормализации номера телефона."""
    return ''.join(filter(str.isdigit, phone))

def client_in_db_or_cache(phone):
    """
    Проверяет, есть ли клиент во внутренней базе данных/кэше.
    """
    print(f"DEBUG: Проверка клиента {phone} во внутренней базе.")
    return phone in IN_MEMORY_DB

def save_client_state(phone, name, in_crm):
    """
    Сохраняет состояние клиента во внутренней базе данных.
    """
    IN_MEMORY_DB[phone] = {
        "name": name,
        "in_crm": in_crm
    }
    print(f"DEBUG: Состояние клиента {name} ({phone}) сохранено в IN_MEMORY_DB: in_crm={in_crm}")

def find_client(phone):
    """
    Находит клиента с таким телефоном в SalesRender и возвращает его данные.
    Возвращает None, если клиент не найден.
    """
    url = f"{SALESRENDER_BASE_URL}/clients?search={phone}"
    headers = {
        "Authorization": SALESRENDER_API_KEY,
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"DEBUG: Полный ответ от CRM (find_client): {json.dumps(data, indent=2)}")
        clients = data.get("data", [])
        if clients:
            print(f"🔍 Клиент найден в CRM ({phone})")
            return clients[0]
        else:
            print(f"🔍 Клиент не найден в CRM ({phone})")
            return None
    except Exception as e:
        print(f"❌ Ошибка проверки клиента: {e}")
        traceback.print_exc()
        return None

def is_lead_active(client_data):
    """
    Проверяет, находится ли лид в обработке, по его ID статуса.
    """
    active_status_id = 1
    
    status_id = client_data.get("statusId")
    print(f"DEBUG: Полученный statusId из CRM: {status_id}")

    if status_id == active_status_id:
        print(f"⚠️ Лид со статусом ID '{status_id}' уже в обработке.")
        return True
    else:
        print(f"✅ Лид со статусом ID '{status_id}' не в обработке. Можно создавать новый заказ.")
        return False

def create_order(full_name, phone):
    """Создаёт заказ в SalesRender"""
    mutation = """
    mutation($firstName: String!, $lastName: String!, $phone: String!) {
      orderMutation {
        addOrder(
          input: {
            projectId: 1
            statusId: 1
            orderData: {
              humanNameFields: [
                { field: "name", value: { firstName: $firstName, lastName: $lastName } }
              ]
              phoneFields: [
                { field: "phone", value: $phone }
              ]
            }
          }
        ) {
          id
        }
      }
    }
    """
    name_parts = full_name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    headers = {
        "Content-Type": "application/json",
        "Authorization": SALESRENDER_API_KEY
    }

    variables = {
        "firstName": first_name,
        "lastName": last_name,
        "phone": phone
    }

    try:
        response = requests.post(SALESRENDER_BASE_URL, json={"query": mutation, "variables": variables}, headers=headers)
        data = response.json()
        print("📦 Ответ создания заказа:", data)
        if "errors" in data:
            print(f"❌ GraphQL ошибка при создании заказа: {data['errors']}")
            return None
        return data["data"]["orderMutation"]["addOrder"]["id"]
    except Exception as e:
        print(f"❌ Ошибка создания заказа: {e}")
        traceback.print_exc()
        return None

# --- Функция вебхука ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("\n--- 📩 Получены данные от 360dialog ---")
    print(data)

    try:
        entry = data.get("entry", [])
        if not entry:
            return jsonify({"status": "no entry"}), 200

        value = entry[0].get("changes", [])[0].get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])

        phone = None
        name = "Клиент"

        if messages:
            phone = messages[0].get("from")
        elif contacts:
            phone = contacts[0].get("wa_id")

        if contacts and "profile" in contacts[0]:
            name = contacts[0]["profile"].get("name", "Клиент")

        if not phone:
            print("❌ Не удалось определить номер телефона")
            return jsonify({"status": "no phone"}), 200
        
        normalized_phone = normalize_phone_number(phone)
        order_id = process_new_lead(name, normalized_phone)

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        traceback.print_exc()
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200

# --- Логика обработки лида ---
def process_new_lead(name, phone):
    """
    Регистрирует нового лида, проверяя сначала внутреннюю БД бота, а затем CRM.
    Создает заказ в CRM только если клиент не найден или его лид не в обработке.
    """
    print(f"\n--- 🤖 Обработка нового потенциального клиента: {name} ({phone}) ---")

    if client_in_db_or_cache(phone):
        print(f"⚠️ Клиент {phone} уже в базе/кэше бота, пропускаем.")
        return None

    client_data = find_client(phone)

    if client_data:
        if is_lead_active(client_data):
            print(f"⚠️ Клиент {phone} найден в CRM и его лид в обработке.")
            save_client_state(phone, name=name, in_crm=True)
            return None
        else:
            print(f"✅ Клиент {phone} найден в CRM, но его лид не активен. Создаем новый заказ.")
            order_id = create_order(name, phone)
            if order_id:
                print(f"📦 Заказ {order_id} создан для {name}.")
                save_client_state(phone, name=name, in_crm=True)
                return order_id
            else:
                print("❌ Не удалось создать заказ.")
                save_client_state(phone, name=name, in_crm=False)
                return None
    else:
        print(f"✨ Клиент {phone} не найден в CRM. Создаем новый заказ.")
        order_id = create_order(name, phone)
        if order_id:
            print(f"📦 Заказ {order_id} создан для {name}.")
            save_client_state(phone, name=name, in_crm=True)
            return order_id
        else:
            print("❌ Не удалось создать заказ.")
            save_client_state(phone, name=name, in_crm=False)
            return None

# --- Запуск приложения ---
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
