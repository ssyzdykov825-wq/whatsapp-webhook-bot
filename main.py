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

# --- Поиск клиента по телефону ---
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
def create_order(customer_id, phone_raw, full_name, project_id="1", status_id="1"):
    mutation = """
    mutation AddOrder($input: AddOrderInput!) {
      orderMutation {
        addOrder(input: $input) {
          id
        }
      }
    }
    """
    phone = format_phone(phone_raw)
    parts = full_name.strip().split()
    first_name = parts[0] if parts else ""
    last_name = " ".join(parts[1:]) if len(parts) > 1 else ""

    variables = {
        "input": {
            "projectId": project_id,
            "statusId": status_id,
            "orderData": {
                "customFields": [
                    {
                        "id": "phone",
                        "value": {
                            "national": phone["national"],
                            "international": phone["international"]
                        }
                    },
                    {
                        "id": "name",
                        "value": {
                            "firstName": first_name,
                            "lastName": last_name
                        }
                    }
                ]
            },
            "customerId": customer_id
        }
    }

    resp = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        print("❌ Невалидный JSON при создании заказа:", resp.text)
        return None
    if "errors" in data:
        return None
    return data["data"]["orderMutation"]["addOrder"]["id"]

# --- Обработка вебхука ---
@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    try:
        messages = data["entry"][0]["changes"][0]["value"].get("messages")
        if not messages:
            return jsonify({"status": "no messages"}), 200

        msg = messages[0]
        raw_from = msg.get("from")
        user_name = msg.get("profile", {}).get("name", "Имя Клиента")
        user_phone = raw_from

        customer_id = find_customer_by_phone(user_phone)
        if not customer_id:
            customer_id = create_customer(user_name, user_phone)
        if not customer_id:
            return jsonify({"status": "error creating customer"}), 500

        order_id = create_order(customer_id, user_phone, user_name, project_id="1", status_id="1")
        if not order_id:
            return jsonify({"status": "error creating order"}), 500

        print(f"✅ Заказ {order_id} создан для клиента {customer_id} ({user_name}, {user_phone})")

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
