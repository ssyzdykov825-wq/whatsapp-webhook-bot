import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

def client_exists(phone):
    """
    Проверяет клиента по телефону.
    Возвращает последний заказ (dict) или None, если заказов нет.
    """
    headers = {
        "Authorization": SALESRENDER_API_KEY,
        "Content-Type": "application/json"
    }

    query = {
        "query": f"""
        query {{
            ordersFetcher(
                filters: {{ include: {{ phones: ["{phone}"] }} }}
                limit: 1
                sort: {{ field: "id", order: DESC }}
            ) {{
                orders {{
                    id
                    status {{ name }}
                    data {{
                        phoneFields {{ value {{ raw }} }}
                    }}
                }}
            }}
        }}
        """
    }

    try:
        resp = requests.post(SALESRENDER_BASE_URL, headers=headers, json=query, timeout=10)
        resp.raise_for_status()
        orders = resp.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
        if orders:
            print(f"🔍 Найден последний заказ {orders[0]['id']} для {phone} со статусом {orders[0]['status']['name']}")
            return orders[0]
        else:
            print(f"ℹ️ Для {phone} заказов не найдено")
            return None
    except Exception as e:
        print(f"❌ Ошибка client_exists: {e}")
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
        print("📦 Ответ создания заказа:", data)
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

        # Используем твою функцию process_new_lead
        order_id = process_new_lead(name, phone)

        if order_id:
            print(f"✅ Заказ {order_id} создан ({name}, {phone})")
        else:
            print(f"ℹ️ Новый заказ НЕ был создан для {phone}")

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200
