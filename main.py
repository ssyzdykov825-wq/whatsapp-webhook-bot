import requests
from flask import Flask, request, jsonify
import datetime
import random
import json

app = Flask(__name__)

# --- Конфиг Shakes ---
API_KEY = "77cc1878c20f827b870b0f13bc98de45"
DOMAIN = "shakes.pro"
OFFER_ID = "10363"
STREAM_CODE = "he8z"
LANDING_URL = "http://ph3.diabetinsale.com"

# Список реальных user-agent’ов (браузеры, мобилки)
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 11; SM-G991B) AppleWebKit/537.36 Chrome/98.0.4758.101 Mobile Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/114.0.0.0 Safari/537.36",
    "Mozilla/5.0 (iPad; CPU OS 14_0 like Mac OS X) AppleWebKit/605.1.15 Version/14.0 Mobile/15A5341f Safari/604.1",
]

def get_random_user_agent():
    return random.choice(USER_AGENTS)

def log_to_file(data: str):
    """Запись в лог"""
    with open("shakes.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now()} | {data}\n")

@app.route("/webhook", methods=["POST"])
def whatsapp_webhook():
    data = request.json

    try:
        # Забираем сообщение и телефон из структуры 360dialog
        changes = data["entry"][0]["changes"][0]["value"]
        message = changes["messages"][0]["text"]["body"]
        phone = changes["messages"][0]["from"]
        name = changes["contacts"][0]["profile"].get("name", "Клиент WhatsApp")
    except Exception as e:
        log_to_file(f"❌ Invalid webhook: {json.dumps(data, ensure_ascii=False)} | Error: {e}")
        return jsonify({"error": "Invalid webhook format", "details": str(e)}), 400

    # Собираем заказ под Shakes
    order = {
        "countryCode": "PH",
        "comment": message,
        "createdAt": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ip": "185.24.88.19",
        "landingUrl": LANDING_URL,
        "name": name,
        "offerId": OFFER_ID,
        "phone": phone,
        "referrer": None,
        "streamCode": STREAM_CODE,
        "sub1": "",
        "sub2": "",
        "sub3": "",
        "sub4": "",
        "userAgent": get_random_user_agent()
    }

    url = f"http://{DOMAIN}?r=/api/order/in&key={API_KEY}"

    try:
        response = requests.post(
            url,
            data=order,
            headers={"User-Agent": get_random_user_agent()}
        )
        log_to_file(f"➡️ ORDER SENT: {order}")
        log_to_file(f"⬅️ RAW RESPONSE: {response.text}")
        shakes_response = response.json()
    except Exception as e:
        shakes_response = {"error": str(e)}
        log_to_file(f"❌ ERROR sending order: {e}")

    return jsonify({
        "status": "ok",
        "sent_order": order,
        "shakes_response": shakes_response
    })

if __name__ == "__main__":
    app.run(port=5000, debug=True)
