from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

INTROPHIN_TOKEN = "Y2ZLN2YXYTKTMJVLMS00ZTG0LWI0NDETYWIWNZY2MZE3NMFH"
STREAM_CODE = "f6bn0"
INTROPHIN_API_URL = "https://introphin.com/api/lead"

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    data = request.json
    print("Incoming WhatsApp message:", data)

    try:
        value = data["entry"][0]["changes"][0]["value"]

        # Достаём контактные данные
        contact = value["contacts"][0]
        phone = contact.get("wa_id")
        name = contact.get("profile", {}).get("name")  # если имени нет → None

        if not phone:
            return jsonify({"status": "error", "message": "No phone in payload"}), 400

        # Формируем payload для Introphin
        payload = {
            "token": INTROPHIN_TOKEN,
            "stream_code": STREAM_CODE,
            "phone": phone
        }
        if name:
            payload["name"] = name

        # Отправляем лид
        response = requests.post(INTROPHIN_API_URL, data=payload)
        print("Introphin response:", response.text)

        return jsonify({"status": "success", "introphin_response": response.json()})

    except Exception as e:
        print("Error:", e)
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
