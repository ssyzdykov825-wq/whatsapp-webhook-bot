import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_BASE_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_API_KEY = "Bearer YOUR_API_KEY_HERE"

def client_exists(phone):
    """Проверяет, есть ли клиент с таким телефоном в SalesRender и не в статусе 'в обработке'"""
    url = f"{SALESRENDER_BASE_URL}/clients?search={phone}"
    headers = {
        "Authorization": SALESRENDER_API_KEY,
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        clients = data.get("data", [])
        
        if not clients:
            print(f"🔍 Клиент не найден в CRM ({phone})")
            return False

        # Проверяем статус лида, если он существует
        client = clients[0]  # Берем первого клиента (предполагаем, что телефон уникален)
        lead_status = client.get("status")  # Допустим, статус находится в поле 'status'

        if lead_status in ['Недозвон', 'Отменен', 'Принят', 'Перезвонить']:
            print(f"⚠️ Клиент {phone} найден в CRM, но его статус: {lead_status}. Новый заказ не создаем.")
            return False

        print(f"🔍 Клиент найден и его статус: {lead_status}. Заказ можно создать.")
        return True
    except Exception as e:
        print(f"❌ Ошибка проверки клиента: {e}")
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

        # Проверка — есть ли клиент в CRM и можно ли повторно отправить
        if client_exists_and_is_not_in_progress(phone):
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
