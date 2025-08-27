import requests
from flask import Flask, request, jsonify
import json

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"


def client_exists(phone):
    """Проверяет, есть ли у клиента заказы в CRM и возвращает статус"""
    headers = {
        "Authorization": SALESRENDER_API_KEY,
        "Content-Type": "application/json"
    }

    query = {
        "query": f"""
        query {{
          ordersFetcher(filters: {{ include: {{ phone: "{phone}" }} }}) {{
            orders {{
              id
              statusId
            }}
          }}
        }}
        """
    }

    try:
        resp = requests.post(SALESRENDER_BASE_URL, headers=headers, json=query, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        print("📩 Ответ CRM (client_exists):", json.dumps(data, indent=2, ensure_ascii=False))

        orders = data.get("data", {}).get("ordersFetcher", {}).get("orders", [])

        if not orders:
            print(f"🔍 У клиента {phone} заказов нет")
            return None

        for order in orders:
            print(f"ℹ️ Найден заказ {order['id']} со статусом {order['statusId']}")
            if order["statusId"] == 1:
                return 1  # есть активный заказ

        return None  # заказов в статусе 1 нет → можно создать новый

    except Exception as e:
        print(f"❌ Ошибка проверки клиента: {e}")
        return None


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
        print("📦 Ответ создания заказа:", json.dumps(data, indent=2, ensure_ascii=False))
        if "errors" in data:
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

        if messages:
            phone = messages[0].get("from")
        elif contacts:
            phone = contacts[0].get("wa_id")

        if contacts and "profile" in contacts[0]:
            name = contacts[0]["profile"].get("name", "Клиент")

        if not phone:
            print("❌ Не удалось определить номер телефона")
            return jsonify({"status": "no phone"}), 200

        status = client_exists(phone)
        if status == 1:
            print(f"⚠️ У клиента {phone} уже есть заказ в статусе 1 — новый не создаём")
            return jsonify({"status": "client has active order"}), 200

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
