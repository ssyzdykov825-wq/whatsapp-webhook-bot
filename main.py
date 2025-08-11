import requests
from flask import Flask, request, jsonify
import uuid
import json

app = Flask(__name__)

# --- Конфиг ---
SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

headers = {
    "Content-Type": "application/json",
    "Authorization": SALESRENDER_TOKEN
}

# --- Форматирование телефона ---
def format_phone(phone_raw):
    digits = ''.join(filter(str.isdigit, str(phone_raw)))
    if len(digits) == 11 and digits.startswith("8"):
        national = digits
        international = "+" + "7" + digits[1:]
    elif len(digits) == 11 and digits.startswith("7"):
        international = "+" + digits
        national = "8" + digits[1:]
    elif len(digits) == 10:
        international = "+7" + digits
        national = "8" + digits
    else:
        international = "+" + digits if not phone_raw.startswith("+") else phone_raw
        national = digits
    return {"international": international, "national": national}

# --- Поиск клиента ---
def find_customer_by_phone(phone):
    q = """
    query ($phone: String!) {
      customersFetcher(filters: { include: { phone: $phone } }) {
        customers {
          id
          name { firstName lastName }
          phone { national international }
        }
      }
    }
    """
    ph = format_phone(phone)
    for phone_variant in (ph["international"], ph["national"]):
        variables = {"phone": phone_variant}
        resp = requests.post(SALESRENDER_URL, json={"query": q, "variables": variables}, headers=headers)
        try:
            data = resp.json()
        except ValueError:
            print("❌ Невалидный JSON при поиске клиента:", resp.text)
            continue
        customers = data.get("data", {}).get("customersFetcher", {}).get("customers", [])
        if customers:
            return customers[0]["id"]
    return None

# --- Создание клиента ---
def create_customer(name, phone_raw):
    mutation = """
    mutation AddCustomer($input: AddCustomerInput!) {
      customerMutation {
        addCustomer(input: $input) {
          id
        }
      }
    }
    """
    if name:
        parts = name.strip().split()
        first_name = parts[0]
        last_name = " ".join(parts[1:]) if len(parts) > 1 else ""
    else:
        first_name = ""
        last_name = ""

    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    phone = format_phone(phone_raw)

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

    resp = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        print("❌ Невалидный JSON при создании клиента:", resp.text)
        return None

    if "errors" in data:
        if any(err.get("extensions", {}).get("code") == "ERR_CUSTOMER_PHONE_ALREADY_USED" for err in data["errors"]):
            return find_customer_by_phone(phone_raw)
        return None

    return data["data"]["customerMutation"]["addCustomer"]["id"]

# --- Создание заказа ---
def create_order(customer_id, phone, name, project_id, status_id):
    query = """
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
            "customerId": customer_id,
            "projectId": "1",
            "statusId": "1",
            "orderData": {
                "title": f"Заказ от {name}",
                "description": f"Создан из WhatsApp, телефон: {phone}"
            }
        }
    }

    resp = requests.post(SALESRENDER_URL, json={"query": query, "variables": variables}, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        print("❌ Невалидный JSON при создании заказа:", resp.text)
        return None

    print("📡 Ответ GraphQL при создании заказа:", json.dumps(data, ensure_ascii=False, indent=2))

    if "errors" in data:
        print("❌ Ошибка при создании заказа:", data["errors"])
        return None

    return data.get("data", {}).get("orderMutation", {}).get("addOrder", {}).get("id")

# --- Обработка вебхука ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий вебхук:", data)

    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if not messages:
            return jsonify({"status": "no messages"}), 200

        msg = messages[0]
        raw_from = msg.get("from")
        profile_info = data["entry"][0]["changes"][0]["value"].get("contacts", [{}])[0].get("profile", {})
        user_name = profile_info.get("name", "Имя Клиента")
        user_phone = raw_from

        customer_id = find_customer_by_phone(user_phone)
        print("🔍 Найденный клиент:", customer_id)

        if not customer_id:
            customer_id = create_customer(user_name, user_phone)
        print("👤 Созданный клиент:", customer_id)

        if not customer_id:
            return jsonify({"status": "error creating customer"}), 500

        order_id = create_order(customer_id, user_phone, user_name, project_id="1", status_id="1")
        print("📦 Созданный заказ:", order_id)

        if not order_id:
            return jsonify({"status": "error creating order"}), 500

        print(f"✅ Заказ {order_id} создан для клиента {customer_id} ({user_name}, {user_phone})")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
