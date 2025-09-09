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
        contact = data["entry"][0]["changes"][0]["value"]["contacts"][0]

        phone = contact["wa_id"]
        name = contact.get("profile", {}).get("name", "")

        payload = {
            "stream_code": FLOW_TOKEN,
            "client": {
                "name": name,
                "phone": phone
            },
            "sub2": "whatsapp"
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {CLIENT_TOKEN}"
        }

        r = requests.post("https://affiliate.drcash.sh/v1/order",
                          headers=headers,
                          data=json.dumps(payload))

        # логируем для проверки
        with open("log.txt", "a") as f:
            f.write(f"{phone} | {name} | {r.text}\n")

    except Exception as e:
        print("Error:", e)

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
