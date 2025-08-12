import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.ey..."

headers = {
    "Content-Type": "application/json",
    "Authorization": SALESRENDER_TOKEN
}

def create_order(full_name, phone):
    mutation = """
    mutation($name: String!, $phone: String!) {
      orderMutation {
        addOrder(
          input: {
            projectId: 1
            statusId: 1
            orderData: {
              humanNameFields: {
                field: "name",
                value: { lastName: $name }
              }
              phoneFields: {
                field: "phone",
                value: $phone
              }
            }
            cart: {
              items: [
                { itemId: 1, variation: 1, quantity: 1 }
              ]
            }
          }
        ) { id }
      }
    }
    """
    variables = {
        "name": full_name,
        "phone": phone
    }
    response = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
    data = response.json()
    print("📦 Ответ создания заказа:", data)
    if "errors" in data:
        return None
    return data["data"]["orderMutation"]["addOrder"]["id"]

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

        if not messages:
            return jsonify({"status": "no messages"}), 200

        phone = messages[0].get("from", "")
        name = contacts[0]["profile"].get("name", "Клиент") if contacts else "Клиент"

        order_id = create_order(name, phone)
        if not order_id:
            return jsonify({"status": "error creating order"}), 500

        print(f"✅ Заказ {order_id} создан ({name}, {phone})")

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
