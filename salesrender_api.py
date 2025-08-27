import requests
import traceback
from flask import Flask, request, jsonify

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

def get_lead_status(phone):
    """
    Ищет лид по номеру телефона в SalesRender и возвращает его ID и статус.
    Если лид не найден, возвращает None.
    """
    query = """
    query($phone: String!) {
      orderSearch(filter: { humanFields: [{ field: "phone", value: $phone }] }) {
        data {
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
    variables = {
        "phone": phone
    }

    try:
        resp = requests.post(
            SALESRENDER_BASE_URL,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=10
        )
        resp.raise_for_status()
        data = resp.json()
        
        if "errors" in data:
            print(f"❌ Ошибка GraphQL-запроса: {data['errors']}")
            return None
            
        orders = data.get("data", {}).get("orderSearch", {}).get("data", [])
        
        if orders:
            lead_info = orders[0]
            print(f"🔍 Клиент найден. ID лида: {lead_info['id']}, статус: {lead_info['statusId']}")
            return lead_info
        else:
            print(f"🔍 Клиент не найден в CRM ({phone})")
            return None
    except Exception as e:
        print(f"❌ Ошибка при поиске клиента: {e}")
        return None

def create_order(full_name, phone):
    """
    Создаёт заказ в SalesRender
    """
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
            print(f"❌ Ошибка создания заказа: {data['errors']}")
            return None
        
        order_id = data["data"]["orderMutation"]["addOrder"]["id"]
        print(f"✅ Заказ {order_id} создан ({full_name}, {phone})")
        return order_id
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

        existing_lead = get_lead_status(phone)

        if existing_lead:
            if existing_lead['statusId'] != 1:
                print(f"⚠️ Клиент {phone} уже есть в CRM, и его лид в обработке (статус {existing_lead['statusId']}). Создаем новый.")
                order_id = create_order(name, phone)
                if not order_id:
                    return jsonify({"status": "error creating order"}), 500
            else:
                print(f"⚠️ Клиент {phone} уже есть в CRM, но его лид не в обработке (статус {existing_lead['statusId']}). Повторная отправка не требуется.")
                return jsonify({"status": "client exists and not in processing"}), 200
        else:
            print(f"✅ Клиент {phone} не найден в CRM. Создаем новый лид.")
            order_id = create_order(name, phone)
            if not order_id:
                return jsonify({"status": "error creating order"}), 500

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        traceback.print_exc()
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
