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
        value = data["entry"][0]["changes"][0]["value"]

        # номер и имя
        phone = None
        name = None

        if "contacts" in value and value["contacts"]:
            phone = value["contacts"][0].get("wa_id")
            name = value["contacts"][0].get("profile", {}).get("name")

        if not phone and "messages" in value and value["messages"]:
            phone = value["messages"][0].get("from")

        if phone:
            phone = "+" + phone  # добавляем "+"
        else:
            phone = "+0000000000"

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

        # пишем в лог то что реально ушло
        with open("log.txt", "a") as f:
            f.write("SEND >>> " + json.dumps(payload, ensure_ascii=False) + "\n")
            f.write("RESPONSE >>> " + r.text + "\n")

    except Exception as e:
        with open("log.txt", "a") as f:
            f.write(f"Error: {str(e)}\n")

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
