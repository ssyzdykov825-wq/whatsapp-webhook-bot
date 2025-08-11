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
        return {"international": "+7" + digits[1:], "national": digits}
    elif len(digits) == 11 and digits.startswith("7"):
        return {"international": "+" + digits, "national": "8" + digits[1:]}
    elif len(digits) == 10:
        return {"international": "+7" + digits, "national": "8" + digits}
    return {"international": "+" + digits, "national": digits}

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
        addCustomer(input: $input) { id }
      }
    }
    """
    first_name, *last_parts = name.strip().split()
    last_name = " ".join(last_parts) if last_parts else ""
    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    phone = format_phone(phone_raw)

    variables = {
        "input": {
            "email": unique_email,
            "password": "ChangeMe123!",
            "name": {"firstName": first_name, "lastName": last_name},
            "locale": {"language": "ru_RU", "currency": "KZT", "timezone": "Asia/Almaty"},
            "phone": phone
        }
    }

    resp = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        return None

    if "errors" in data:
        if any(err.get("extensions", {}).get("code") == "ERR_CUSTOMER_PHONE_ALREADY_USED" for err in data["errors"]):
            return find_customer_by_phone(phone_raw)
        return None

    return data["data"]["customerMutation"]["addCustomer"]["id"]

# --- Получение ID полей формы заказа ---
def get_order_form_fields(project_id):
    query = """
    query GetOrderForm($projectId: ID!) {
      orderFormFetcher(projectId: $projectId) {
        fields { id name type }
      }
    }
    """
    resp = requests.post(SALESRENDER_URL, json={"query": query, "variables": {"projectId": project_id}}, headers=headers)
    try:
        data = resp.json()
    except ValueError:
        print("❌ Ошибка получения формы заказа:", resp.text)
        return None
    return data.get("data", {}).get("orderFormFetcher", {}).get("fields", [])

# --- Создание заказа ---
def create_order(customer_id, phone, name, project_id="1", status_id="1"):
    fields = get_order_form_fields(project_id)
    if not fields:
        print("❌ Нет полей формы заказа")
        return None

    name_field = next((f for f in fields if "имя" in f["name"].lower()), None)
    phone_field = next((f for f in fields if "тел" in f["name"].lower()), None)

    if not name_field or not phone_field:
        print("❌ Не удалось найти поля для имени и телефона")
        return None

    # Далее создание заказа без изменений

# ...

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
        if not customer_id:
            customer_id = create_customer(user_name, user_phone)
        if not customer_id:
            return jsonify({"status": "error creating customer"}), 500

        order_id = create_order(customer_id, user_phone, user_name, project_id="1", status_id="1")
        if not order_id:
            # Вместо 500 лучше вернуть 200, чтобы не падал сервер,
            # и отладочная информация
            print("❌ Не удалось создать заказ, пропускаем")
            return jsonify({"status": "order not created, missing fields or error"}), 200

        print(f"✅ Заказ {order_id} создан для клиента {customer_id} ({user_name}, {user_phone})")

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
