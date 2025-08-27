import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

def client_exists(phone):
    """
    Проверяет клиента по телефону.
    Возвращает dict:
      {
        "has_active": True/False,   # есть ли активный заказ
        "last_order": {...}         # последний заказ по ID (для инфо)
      }
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
                limit: 10
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

        if not orders:
            print(f"ℹ️ Для {phone} заказов не найдено")
            return {"has_active": False, "last_order": None}

        allowed_statuses = {"Спам/Тест", "Отменен", "Недозвон 5 дней", "Недозвон", "Перезвонить"}

        has_active = any(order["status"]["name"] not in allowed_statuses for order in orders)

        print(f"🔍 Проверено {len(orders)} заказов для {phone}. Активный найден? {has_active}")

        return {
            "has_active": has_active,
            "last_order": orders[0]
        }

    except Exception as e:
        print(f"❌ Ошибка client_exists: {e}")
        return {"has_active": False, "last_order": None}


def create_order(full_name, phone):
    """Создаёт заказ в SalesRender и возвращает его ID или None"""
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

    # Разделяем имя
    name_parts = full_name.strip().split(" ", 1) if full_name else ["", ""]
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
        print(f"\n=== create_order вызван ===")
        print(f"DEBUG: variables = {variables}")
        response = requests.post(
            SALESRENDER_BASE_URL,
            json={"query": mutation, "variables": variables},
            headers=headers,
            timeout=10
        )
        print(f"DEBUG: HTTP {response.status_code}")
        try:
            data = response.json()
            print(f"📦 Полный ответ CRM: {data}")
        except Exception:
            print("❌ Не удалось распарсить JSON, вот сырой ответ:")
            print(response.text)
            return None

        if "errors" in data:
            print(f"❌ CRM вернула ошибки: {data['errors']}")
            return None

        order_id = data.get("data", {}).get("orderMutation", {}).get("addOrder", {}).get("id")
        if order_id:
            print(f"✅ Заказ успешно создан, ID={order_id}")
            return order_id
        else:
            print("⚠️ CRM не вернула ID заказа")
            return None

    except Exception as e:
        print(f"❌ Ошибка при запросе в CRM: {e}")
        return None


@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print("📩 Входящий JSON:", data)

    entry = data.get("entry", [])[0]
    changes = entry.get("changes", [])[0]
    value = changes.get("value", {})
    messages = value.get("messages", [])

    if not messages:
        return jsonify({"status": "no messages"}), 200

    msg = messages[0]
    phone = msg.get("from")
    contact = value.get("contacts", [{}])[0]
    name = contact.get("profile", {}).get("name", "Неизвестный")

    text = msg.get("text", {}).get("body", "")
    print(f"DEBUG: Обрабатываем сообщение от {phone}, текст: {text}")

    # ❌ раньше было так:
    # order_id = create_order(name, phone)

    # ✅ теперь через нашу логику
    order_id = process_new_lead(name, phone)

    if order_id:
        print(f"🎉 Заказ {order_id} успешно создан")
    else:
        print("⏳ Новый заказ не был создан")

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__": 
    app.run(host="0.0.0.0", port=5000)
