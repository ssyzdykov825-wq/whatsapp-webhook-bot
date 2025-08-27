import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# --- Настройки SalesRender ---
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

def get_client(phone):
    """Возвращает данные клиента из CRM"""
    url = f"{SALESRENDER_BASE_URL}/clients?search={phone}"
    headers = {"Authorization": SALESRENDER_API_KEY, "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        clients = data.get("data", [])
        if clients:
            return clients[0]  # возвращаем первый совпавший
        return None
    except Exception as e:
        print(f"❌ Ошибка получения клиента: {e}")
        return None

def should_resend_lead(client):
    """Проверяем, нужно ли повторно отправлять лид"""
    resend_statuses = ["отклонен", "не в обработке"]
    if not client:
        return True  # клиент новый — отправляем
    status = client.get("status", "").lower()
    return status in resend_statuses

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

    headers = {"Content-Type": "application/json", "Authorization": SALESRENDER_API_KEY}
    variables = {"firstName": first_name, "lastName": last_name, "phone": phone}

    try:
        response = requests.post(SALESRENDER_BASE_URL, json={"query": mutation, "variables": variables}, headers=headers)
        data = response.json()
        if "errors" in data:
            print("❌ Ошибка создания заказа:", data["errors"])
            return None
        return data["data"]["orderMutation"]["addOrder"]["id"]
    except Exception as e:
        print(f"❌ Ошибка создания заказа: {e}")
        return None

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Получены данные от 360dialog:", data)

    try:
        entry = data.get("entry", [])
        if not entry:
            return jsonify({"status": "no entry"}), 200

        value = entry[0].get("changes", [])[0].get("value", {})
        messages = value.get("messages", [])
        contacts = value.get("contacts", [])

        phone = None
        name = "Клиент"

        # Берём номер телефона
        if messages:
            phone = messages[0].get("from")
        elif contacts:
            phone = contacts[0].get("wa_id")

        # Берём имя
        if contacts and "profile" in contacts[0]:
            name = contacts[0]["profile"].get("name", "Клиент")

        if not phone:
            print("❌ Не удалось определить номер телефона")
            return jsonify({"status": "no phone"}), 200

        # Проверка клиента и статуса
        client = get_client(phone)
        if should_resend_lead(client):
            order_id = create_order(name, phone)
            if order_id:
                print(f"✅ Заказ {order_id} создан ({name}, {phone})")
            else:
                return jsonify({"status": "error creating order"}), 500
        else:
            print(f"⚠️ Клиент {phone} уже есть в CRM с активным статусом — заказ не создаём")
            return jsonify({"status": "client exists, active"}), 200

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
