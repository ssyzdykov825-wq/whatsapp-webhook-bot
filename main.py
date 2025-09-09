from flask import Flask, request, jsonify
import requests
import json

app = Flask(__name__)

FLOW_TOKEN = "f6bn0"
CLIENT_TOKEN = "Y2ZLN2YXYTKTMJVLMS00ZTG0LWI0NDETYWIWNZY2MZE3NMFH"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()

    try:
        # логируем весь JSON чтобы видеть что прилетает
        with open("log.txt", "a") as f:
            f.write("RAW: " + json.dumps(data, ensure_ascii=False) + "\n")

        value = data["entry"][0]["changes"][0]["value"]

        # пробуем достать из contacts
        phone = None
        name = ""

        if "contacts" in value and len(value["contacts"]) > 0:
            contact = value["contacts"][0]
            phone = contact.get("wa_id")
            name = contact.get("profile", {}).get("name", "")

        # если contacts пустой — берём из messages
        if not phone and "messages" in value and len(value["messages"]) > 0:
            phone = value["messages"][0].get("from")

        if phone:
            phone = "+" + phone  # добавляем плюс
        else:
            phone = "+0000000000"  # fallback, чтобы всегда был номер

        if not name:
            name = "No name"

        payload = {
            "stream_code": FLOW_TOKEN,
            "client": {
                "name": name,
                "phone": phone
            },
            "sub2": "1"
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CLIENT_TOKEN}"
        }

        r = requests.post(
            "https://affiliate.drcash.sh/v1/order",
            headers=headers,
            data=json.dumps(payload)
        )

        # логируем что реально уходит
        with open("log.txt", "a") as f:
            f.write(f"SEND: {phone} | {name} | {r.text}\n")

    except Exception as e:
        with open("log.txt", "a") as f:
            f.write(f"Error: {str(e)}\n")
        print("Error:", e)

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
