from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# Токен и поток Introphin
INTROPHIN_TOKEN = "Y2ZLN2YXYTKTMJVLMS00ZTG0LWI0NDETYWIWNZY2MZE3NMFH"
STREAM_CODE = "f6bn0"

# API URL Introphin
INTROPHIN_API_URL = "https://introphin.com/api/lead"

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    data = request.json
    print("Incoming WhatsApp message:", data)

    # Получаем телефон
    try:
        phone = data["contacts"][0]["wa_id"]
    except KeyError:
        return jsonify({"status": "error", "message": "Phone not found"}), 400

    # Проверяем имя
    name = None
    try:
        name = data["contacts"][0].get("profile", {}).get("name")
    except KeyError:
        pass

    # Формируем payload
    payload = {
        "token": INTROPHIN_TOKEN,
        "stream_code": STREAM_CODE,
        "phone": phone
    }

    if name:  # Если имя есть, добавляем
        payload["name"] = name

    # Отправляем лид в Introphin
    try:
        response = requests.post(INTROPHIN_API_URL, data=payload)
        return jsonify({"status": "success", "introphin_response": response.json()})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
