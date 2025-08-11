import requests
from flask import Flask, request, jsonify
import uuid

app = Flask(__name__)

SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

headers = {
    "Content-Type": "application/json",
    "Authorization": SALESRENDER_TOKEN
}

# --- Поиск клиента по телефону ---
def find_customer_by_phone(phone):
    query = """
    query ($phone: String!) {
      customersFetcher(filters: { include: { phone: $phone } }) {
        customers {
          id
          name {
            firstName
            lastName
          }
          phone {
            national
            international
          }
        }
      }
    }
    """
    variables = {"phone": phone}
    response = requests.post(SALESRENDER_URL, json={"query": query, "variables": variables}, headers=headers)
    data = response.json()
    print("🔍 Ответ поиска клиента:", data)
    customers = data.get("data", {}).get("customersFetcher", {}).get("customers", [])
    return customers[0]["id"] if customers else None

# --- Создание клиента ---
def create_customer(name, phone):
    mutation = """
    mutation AddCustomer($input: AddCustomerInput!) {
      customerMutation {
        addCustomer(input: $input) {
          id
        }
      }
    }
    """
    first_name = name.split()[0] if name else "Имя"
    last_name = " ".join(name.split()[1:]) if name and len(name.split()) > 1 else "Фамилия"
    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"

    variables = {
        "input": {
            "email": unique_email,
            "password": "ChangeMe123!",
            "name": {
                "firstName": first_name,
                "lastName": last_name
            },
            "locale": {
                "language": "ru_RU",
                "currency": "KZT",
                "timezone": "Asia/Almaty"
            },
            "phone": phone
        }
    }

    response = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
    data = response.json()
    print("🆕 Ответ создания клиента:", data)

    # Если номер уже есть — ищем клиента
    if "errors" in data:
        if any(err.get("extensions", {}).get("code") == "ERR_CUSTOMER_PHONE_ALREADY_USED" for err in data["errors"]):
            print("ℹ Телефон уже используется, ищем существующего клиента...")
            return find_customer_by_phone(phone)
        print("Ошибка создания клиента:", data["errors"])
        return None

    return data["data"]["customerMutation"]["addCustomer"]["id"]

# --- Создание заказа ---
def create_order(customer_id, phone):
    mutation = """
    mutation AddOrder($input: AddOrderInput!) {
      orderMutation {
        addOrder(input: $input) {
          id
        }
      }
    }
    """
    variables = {
        "input": {
            "projectId": "1",  # твой проект
            "statusId": "1",   # твой статус
            "orderData": {
                "phoneFields": [{"value": phone}]
            },
            "customerId": customer_id
        }
    }
    print("📤 Отправляем заказ:", variables)
    response = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
    data = response.json()
    print("📦 Ответ создания заказа:", data)

    if "errors" in data:
        print("Ошибка создания заказа:", data["errors"])
        return None
    return data["data"]["orderMutation"]["addOrder"]["id"]

# --- Форматирование номера ---
def format_phone(phone):
    return "+" + phone if not phone.startswith("+") else phone

# --- Обработка вебхука WhatsApp ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if not messages:
            return jsonify({"status": "no messages"}), 200

        msg = messages[0]
        user_phone = format_phone(msg["from"])
        user_name = msg.get("profile", {}).get("name", "Имя Клиента")

        # Ищем клиента
        customer_id = find_customer_by_phone(user_phone)

        # Если нет — создаём
        if not customer_id:
            customer_id = create_customer(user_name, user_phone)

        if not customer_id:
            return jsonify({"status": "error creating customer"}), 500

        # Создаём заказ
        order_id = create_order(customer_id, user_phone)
        if not order_id:
            return jsonify({"status": "error creating order"}), 500

        print(f"✅ Заказ {order_id} создан для клиента {customer_id} ({user_name}, {user_phone})")

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
