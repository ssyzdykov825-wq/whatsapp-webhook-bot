import requests
from flask import Flask, request

app = Flask(__name__)

# --- Константы ---
API_URL = "https://api.kma.biz/lead/add"
API_KEY = "bj4x9DFUWECbPJJ-7m4rg_--lPDkmL-H"       # твой API-ключ из кабинета KMA
CHANNEL = "ZQHk1t"       # код потока в KMA

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json

    # --- Логируем весь входящий JSON ---
    print("=== RAW WEBHOOK DATA ===")
    print(data)

    try:
        # Достаём сообщения и контакты
        message = data["entry"][0]["changes"][0]["value"]["messages"][0]
        text = message.get("text", {}).get("body", "")
        user_phone = message["from"]

        contact = data["entry"][0]["changes"][0]["value"]["contacts"][0]
        name = contact["profile"]["name"]

        # --- Формируем данные для KMA ---
        payload = {
            "channel": CHANNEL,
            "name": name,
            "phone": user_phone,
            "ip": "85.117.122.182",       # пока заглушка, позже заменим
            "country": "KZ",
            "referer": "whatsapp://chat"
        }

        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/x-www-form-urlencoded"
        }

        # --- Отправка в KMA ---
        r = requests.post(API_URL, data=payload, headers=headers)

        print("=== KMA RESPONSE ===")
        print(r.status_code, r.text)

        return {"status": r.status_code, "response": r.json()}

    except Exception as e:
        # Если структура не совпала — возвращаем сырые данные
        return {"error": str(e), "raw_data": data}, 400


if __name__ == "__main__":
    app.run(port=5000)
