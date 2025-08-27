import requests
import traceback
import json

# --- Настройки SalesRender ---
# !!! ВНИМАНИЕ: ЗАМЕНИТЕ ЭТИ ДАННЫЕ НА СВОИ АКТУАЛЬНЫЕ !!!
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZWRlbnJkZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

def find_client(phone):
    """
    Находит клиента с таким телефоном в SalesRender и возвращает его данные.
    Возвращает None, если клиент не найден.
    """
    url = f"{SALESRENDER_BASE_URL}/clients?search={phone}"
    headers = {
        "Authorization": SALESRENDER_API_KEY,
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        print(f"DEBUG: Полный ответ от CRM (find_client): {json.dumps(data, indent=2)}")
        clients = data.get("data", [])
        if clients:
            print(f"🔍 Клиент найден в CRM ({phone})")
            return clients[0]  # Возвращаем данные первого найденного клиента
        else:
            print(f"🔍 Клиент не найден в CRM ({phone})")
            return None
    except Exception as e:
        print(f"❌ Ошибка проверки клиента: {e}")
        traceback.print_exc()
        return None

def is_lead_active(client_data):
    """
    Проверяет, находится ли лид в обработке, по его ID статуса.
    """
    active_status_id = 1
    
    # Мы ожидаем, что в данных клиента будет поле 'statusId'
    status_id = client_data.get("statusId")
    print(f"DEBUG: Полученный statusId из CRM: {status_id}")

    if status_id == active_status_id:
        print(f"⚠️ Лид со статусом ID '{status_id}' уже в обработке.")
        return True
    else:
        print(f"✅ Лид со статусом ID '{status_id}' не в обработке. Можно создавать новый заказ.")
        return False

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
            print(f"❌ GraphQL ошибка при создании заказа: {data['errors']}")
            return None
        return data["data"]["orderMutation"]["addOrder"]["id"]
    except Exception as e:
        print(f"❌ Ошибка создания заказа: {e}")
        traceback.print_exc()
        return None

def fetch_order_from_crm(order_id):
    """Извлекает детали заказа из SalesRender CRM с помощью GraphQL."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": SALESRENDER_API_KEY
    }
    query = {
        "query": f"""
        query {{
            ordersFetcher(filters: {{ include: {{ ids: ["{order_id}"] }} }}) {{
                orders {{
                    id
                    data {{
                        humanNameFields {{ value {{ firstName lastName }} }}
                        phoneFields {{ value {{ international raw national }} }}
                    }}
                }}
            }}
        }}
        """
    }
    try:
        response = requests.post(SALESRENDER_BASE_URL, headers=headers, json=query, timeout=10)
        response.raise_for_status()
        data = response.json().get("data", {}).get("ordersFetcher", {}).get("orders", [])
        return data[0] if data else None
    except Exception as e:
        print(f"❌ Ошибка получения из CRM: {e}")
        traceback.print_exc()
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

        # Проверка — есть ли клиент в CRM
        if client_exists(phone):
            print(f"⚠️ Клиент {phone} уже есть в CRM — заказ не создаём")
            return jsonify({"status": "client exists"}), 200

        # Создаём заказ в CRM
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
