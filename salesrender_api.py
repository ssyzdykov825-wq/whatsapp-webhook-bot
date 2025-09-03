import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# Настройки SalesRender
SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

def client_exists(phone):
    """Проверяет, есть ли клиент с таким телефоном в SalesRender"""
    url = f"{SALESRENDER_URL}/clients?search={phone}"
    headers = {
        "Authorization": SALESRENDER_TOKEN,
        "Content-Type": "application/json"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        exists = len(data.get("data", [])) > 0
        print(f"🔍 Клиент {'найден' if exists else 'не найден'} в CRM ({phone})")
        return exists
    except Exception as e:
        print(f"❌ Ошибка проверки клиента: {e}")
        return False

def create_order(full_name, phone, project_id):
    """Создаёт заказ в SalesRender"""
    mutation = """
    mutation($firstName: String!, $lastName: String!, $phone: String!, $projectId: Int!) {
      orderMutation {
        addOrder(
          input: {
            projectId: $projectId
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
        "Authorization": SALESRENDER_TOKEN
    }

    variables = {
        "firstName": first_name,
        "lastName": last_name,
        "phone": phone,
        "projectId": project_id
    }

    try:
        response = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
        data = response.json()
        print("📦 Ответ создания заказа:", data)
        if "errors" in data:
            return None
        return data["data"]["orderMutation"]["addOrder"]["id"]
    except Exception as e:
        print(f"❌ Ошибка создания заказа: {e}")
        return None

# ДОБАВЬ проверку ключевых слов перед вызовом create_order
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
        text = ""

        # Берём номер телефона и текст
        if messages:
            phone = messages[0].get("from")
            text = messages[0].get("text", {}).get("body", "").lower()  # Получаем текст сообщения
        elif contacts:
            phone = contacts[0].get("wa_id")

        # Берём имя
        if contacts and "profile" in contacts[0]:
            name = contacts[0]["profile"].get("name", "Клиент")

        if not phone:
            print("❌ Не удалось определить номер телефона")
            return jsonify({"status": "no phone"}), 200

        # ✅ Определяем projectId по тексту
        if "салем" in text:
            project_id = 1
        elif "здравствуйте" in text:
            project_id = 2
        else:
            project_id = 1  # по умолчанию

        print(f"📌 Текст: '{text}', выбран projectId: {project_id}")

        # Проверка — есть ли клиент в CRM
        if client_exists(phone):
            print(f"⚠️ Клиент {phone} уже есть в CRM — заказ не создаём")
            return jsonify({"status": "client exists"}), 200

        # Создаём заказ в CRM с нужным projectId
        order_id = create_order(name, phone, project_id)
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
