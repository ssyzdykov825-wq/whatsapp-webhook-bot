import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

# --- ДОПОЛНИТЕЛЬНЫЕ ФУНКЦИИ ---

def get_customer_id_by_phone(phone: str):
    """Ищем клиента по телефону"""
    url = f"{SALESRENDER_BASE_URL}/clients?search={phone}"
    headers = {
        "Authorization": SALESRENDER_API_KEY,
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("data", [])
        return items[0].get("id") if items else None
    except Exception as e:
        print(f"❌ Ошибка get_customer_id_by_phone: {e}")
        return None


def get_orders_by_customer_id(customer_id: str):
    """Тянем заказы по clientId"""
    query = {
        "query": f"""
        query {{
          ordersFetcher(filters: {{ customerIds: ["{customer_id}"] }}) {{
            orders {{
              id
              statusId
            }}
          }}
        }}
        """
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": SALESRENDER_API_KEY
    }
    try:
        resp = requests.post(SALESRENDER_BASE_URL, headers=headers, json=query, timeout=10)
        resp.raise_for_status()
        return resp.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
    except Exception as e:
        print(f"❌ Ошибка get_orders_by_customer_id: {e}")
        return []


def needs_new_order(phone: str) -> bool:
    """
    Правила:
    - Если есть заказ со statusId == 1 → НЕ создаём.
    - Во всех остальных случаях → создаём.
    """
    cust_id = get_customer_id_by_phone(phone)
    if not cust_id:
        print(f"ℹ️ Клиент с телефоном {phone} не найден → создаём заказ")
        return True

    orders = get_orders_by_customer_id(cust_id)
    print(f"📋 Заказы клиента {cust_id}: {orders}")

    if any(int(o.get("statusId", 0)) == 1 for o in orders):
        print("⛔ Есть заказ в статусе 1 → новый заказ НЕ создаём")
        return False

    print("✅ Нет заказов в статусе 1 → создаём новый заказ")
    return True

# --- СТАРЫЕ ФУНКЦИИ ---

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
            return None
        return data["data"]["orderMutation"]["addOrder"]["id"]
    except Exception as e:
        print(f"❌ Ошибка создания заказа: {e}")
        return None

# --- WEBHOOK ---

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

        if messages:
            phone = messages[0].get("from")
        elif contacts:
            phone = contacts[0].get("wa_id")

        if contacts and "profile" in contacts[0]:
            name = contacts[0]["profile"].get("name", "Клиент")

        if not phone:
            print("❌ Не удалось определить номер телефона")
            return jsonify({"status": "no phone"}), 200

        # 🔍 Проверка — нужно ли создавать заказ
        if not needs_new_order(phone):
            return jsonify({"status": "order in progress"}), 200

        # ✅ Создаём заказ
        order_id = create_order(name, phone)
        if not order_id:
            return jsonify({"status": "error creating order"}), 500

        print(f"✅ Заказ {order_id} создан ({name}, {phone})")

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
