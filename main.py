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
        # логируем сырой вебхук
        with open("log.txt", "a", encoding="utf-8") as f:
            f.write("===== Incoming WhatsApp message =====\n")
            f.write(json.dumps(data, ensure_ascii=False, indent=2))
            f.write("\n\n")

        # пробуем вытащить номер и имя
        contact = data["entry"][0]["changes"][0]["value"]["contacts"][0]
        phone = contact.get("wa_id")
        name = contact.get("profile", {}).get("name", "")

        # если вдруг contacts пустые, берем номер из messages["from"]
        if not phone:
            phone = data["entry"][0]["changes"][0]["value"]["messages"][0].get("from")

        # добавляем + если нет
        if phone and not phone.startswith("+"):
            phone = f"+{phone}"

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

        # логируем payload перед отправкой
        with open("log.txt", "a", encoding="utf-8") as f:
            f.write("===== Payload to Dr.Cash =====\n")
            f.write(json.dumps(payload, ensure_ascii=False, indent=2))
            f.write("\n\n")

        r = requests.post(
            "https://affiliate.drcash.sh/v1/order",
            headers=headers,
            data=json.dumps(payload)
        )

        # логируем ответ от Dr.Cash
        with open("log.txt", "a", encoding="utf-8") as f:
            f.write("===== Response from Dr.Cash =====\n")
            f.write(r.text)
            f.write("\n\n")

    except Exception as e:
        with open("log.txt", "a", encoding="utf-8") as f:
            f.write("===== ERROR =====\n")
            f.write(str(e))
            f.write("\n\n")
        print("Error:", e)

    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
