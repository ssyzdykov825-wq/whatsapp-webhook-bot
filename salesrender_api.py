import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

# ==========================
# Получение заказов по телефону
# ==========================
def get_orders_by_phone(phone):
    """Возвращает список заказов по номеру телефона"""
    query = """
    query($phone: String!) {
      ordersFetcher(filters: { phone: $phone }) {
        orders {
          id
          statusId
        }
      }
    }
    """
    headers = {
        "Content-Type": "application/json",
        "Authorization": SALESRENDER_API_KEY
    }
    try:
        resp = requests.post(
            SALESRENDER_URL,
            json={"query": query, "variables": {"phone": phone}},
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        print("📦 Ответ CRM (ordersFetcher):", data)
        return data.get("data", {}).get("ordersFetcher", {}).get("orders", [])
    except Exception as e:
        print(f"❌ Ошибка получения заказов по телефону {phone}: {e}")
        return []

# ==========================
# Создание заказа
# ==========================
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

    variables = {"firstName": first_name, "lastName": last_name, "phone": phone}

    try:
        resp = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
        data = resp.json()
        print("📦 Ответ создания заказа:", data)
        if "errors" in data:
            return None
        return data["data"]["orderMutation"]["addOrder"]["id"]
    except Exception as e:
        print(f"❌ Ошибка создания заказа: {e}")
        return None

# ==========================
# Webhook
# ==========================
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

        # Проверяем заказы по телефону
        orders = get_orders_by_phone(phone)
        create_new = True

        if orders:
            for o in orders:
                sid = o.get("statusId")
                print(f"🔎 Найден заказ {o['id']} со статусом {sid}")
                if sid == 1:
                    create_new = False
                    break
                if sid in [3, 4, 8, 10, 11]:
                    create_new = True
                    break

        if create_new:
            order_id = create_order(name, phone)
            if not order_id:
                return jsonify({"status": "error creating order"}), 500
            print(f"✅ Заказ {order_id} создан ({name}, {phone})")
        else:
            print(f"⚠️ Новый заказ не нужен для {phone}")
            return jsonify({"status": "order exists"}), 200

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
