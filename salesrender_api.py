import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

def normalize_phone_for_crm(phone: str) -> str:
    """Приводим номер к виду +7xxxxxxxxxx"""
    phone = phone.strip()
    if phone.startswith("8") and len(phone) == 11:
        return "+7" + phone[1:]
    if phone.startswith("7") and len(phone) == 11:
        return "+" + phone
    if not phone.startswith("+") and len(phone) == 10:
        return "+7" + phone
    return phone

import requests

def client_exists(phone):
    """
    Проверяет клиента по телефону.
    Возвращает словарь:
    {
        "has_active": bool,
        "last_order": dict | None
    }
    """
    headers = {
        "Authorization": SALESRENDER_TOKEN,
        "Content-Type": "application/json"
    }

    query = {
        "query": f"""
        query {{
            ordersFetcher(
                filters: {{ include: {{ phones: ["{phone}"] }} }}
                limit: 5
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
        resp = requests.post(SALESRENDER_URL, headers=headers, json=query, timeout=10)
        resp.raise_for_status()
        orders = resp.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])

        if not orders:
            print(f"ℹ️ Для {phone} заказов не найдено")
            return {"has_active": False, "last_order": None}

        last_order = orders[0]
        last_status = (last_order.get("status") or {}).get("name", "").strip().lower()

        allowed_statuses = {"спам/тест", "отменен", "недозвон 5 дней", "недозвон", "перезвонить"}

        if last_status in allowed_statuses:
            print(f"✅ Последний заказ {last_order['id']} в статусе '{last_status}' → можно создать новый")
            return {"has_active": False, "last_order": last_order}
        else:
            print(f"⏳ У клиента есть активный заказ {last_order['id']} со статусом '{last_status}'")
            return {"has_active": True, "last_order": last_order}

    except Exception as e:
        print(f"❌ Ошибка client_exists: {e}")
        return {"has_active": False, "last_order": None}


# ==============================
# Создание заказа
# ==============================
def create_order(name, phone):
    """
    Создаёт новый заказ в SalesRender
    """
    headers = {
        "Authorization": SALESRENDER_TOKEN,
        "Content-Type": "application/json"
    }

    variables = {
        "firstName": name,
        "lastName": "",
        "phone": phone
    }

    query = {
        "query": """
        mutation($firstName: String!, $lastName: String, $phone: String!) {
            orderMutation {
                addOrder(
                    input: {
                        customer: {
                            name: { firstName: $firstName, lastName: $lastName }
                            phone: { raw: $phone }
                        }
                    }
                ) {
                    id
                }
            }
        }
        """,
        "variables": variables
    }

    try:
        print(f"DEBUG: variables = {variables}")
        resp = requests.post(SALESRENDER_URL, headers=headers, json=query, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"📦 Полный ответ CRM: {data}")

        order_id = data.get("data", {}).get("orderMutation", {}).get("addOrder", {}).get("id")
        if order_id:
            print(f"✅ Заказ успешно создан, ID={order_id}")
            return order_id
        else:
            print("❌ Не удалось получить ID заказа из ответа CRM")
            return None

    except Exception as e:
        print(f"❌ Ошибка create_order: {e}")
        return None


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
        "Authorization": SALESRENDER_TOKEN
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
            SALESRENDER_URL,
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
