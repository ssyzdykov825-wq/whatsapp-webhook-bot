import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

headers = {
    "Content-Type": "application/json",
    "Authorization": SALESRENDER_TOKEN
}

def create_lead(full_name, phone):
    mutation = """
    mutation($firstName: String!, $lastName: String!, $phone: String!) {
      leadMutation {
        addLead(
          input: {
            offerId: 1
            externalTag: "whatsapp"
            externalId: $phone
            data: {
              phone_1: $phone
              humanName_1: {
                firstName: $firstName
                lastName: $lastName
              }
            }
            source: {
              utm_source: "whatsapp"
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

    variables = {
        "firstName": first_name,
        "lastName": last_name,
        "phone": phone
    }
    response = requests.post(SALESRENDER_URL, json={"query": mutation, "variables": variables}, headers=headers)
    data = response.json()
    print("📦 Ответ создания лида:", data)
    if "errors" in data:
        return None
    return data["data"]["leadMutation"]["addLead"]["id"]

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

        lead_id = create_lead(name, phone)
        if not lead_id:
            return jsonify({"status": "error creating lead"}), 500

        print(f"✅ Лид {lead_id} создан ({name}, {phone})")

    except Exception as e:
        print(f"❌ Ошибка в webhook: {e}")
        return jsonify({"status": "error"}), 500

    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
