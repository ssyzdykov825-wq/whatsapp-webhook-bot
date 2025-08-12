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

def find_customer_by_phone(phone):
    query = """
    query ($phone: String!) {
      customersFetcher(filters: { phoneFields: { value: $phone } }) {
        customers {
          id
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
    if "errors" in data:
        print("Ошибка создания клиента:", data["errors"])
        return None
    return data["data"]["customerMutation"]["addCustomer"]["id"]

def create_order(customer_id, phone, full_name="Имя Клиента"):
    mutation = """
    mutation AddOrder($input: AddOrderInput!) {
      orderMutation {
        addOrder(input: $input) {
          id
        }
      }
    }
    """
    first_name = full_name.split()[0] if full_name else ""
    last_name = " ".join(full_name.split()[1:]) if len(full_name.split()) > 1 else ""

    variables = {
        "input": {
            "projectId": 1,
            "statusId": 1,
            "orderData": {
                "humanNameFields": [
                    {
                        "field": "name",
                        "value": {
                            "firstName": first_name,
                            "lastName": last_name
                        }
                    }
                ],
                "phoneFields": [
                    {
                        "field": "phone",
                        "value": phone
                    }
                ]
            },
            "cart": {
                "items": [
                    {
                        "itemId": 1,
                        "variation": 1,
                        "quantity": 1
                    }
                ]
            },
            "customerId": customer_id
        }
    }
    response = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
    data = response.json()
    print("📦 Ответ создания заказа:", data)
    if "errors" in data:
        print("Ошибка создания заказа:", data["errors"])
        return None
    return data["data"]["orderMutation"]["addOrder"]["id"]

def format_phone(phone):
    return "+" + phone if not phone.startswith("+") else phone

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Получены данные от 360dialog:", data)

    try:
        messages = data.get("messages", [])
        if not messages:
            return jsonify({"status": "no messages"}), 200

        msg = messages[0]
        raw_phone = msg.get("from")
        user_phone = format_phone(raw_phone)

        contacts = data.get("contacts", [])
        user_name = contacts[0]["profile"]["name"] if contacts and "profile" in contacts[0] else "Имя Клиента"

        # Создаём клиента
        customer_id = create_customer(user_name, user_phone)
        if not customer_id:
            return jsonify({"status": "error creating customer"}), 500

        # Создаём заказ
        order_id = create_order(customer_id, user_phone, user_name)
        if not order_id:
            return jsonify({"status": "error creating order"}), 500

        print(f"✅ Заказ {order_id} создан для клиента {customer_id} ({user_name}, {user_phone})")

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
