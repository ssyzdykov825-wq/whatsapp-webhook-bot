import requests
from flask import Flask, request

app = Flask(__name__)

# --- Константы ---
API_URL = "https://api.kma.biz/lead/add"
API_KEY = "bj4x9DFUWECbPJJ-7m4rg_--lPDkmL-H"  # сюда вставь ключ API из кабинета
CHANNEL = "ZQHk1t"

@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    message = data["messages"][0]["text"]["body"]
    user_phone = data["messages"][0]["from"]

    # --- Парсинг данных (тут можно сделать умнее через GPT) ---
    name = "Клиент"  # временно ставим "Клиент", можно доставать из текста
    phone = user_phone
    ip = request.remote_addr  # тут лучше передавать IP клиента, а не сервера
    country = "KZ"
    referer = "whatsapp://chat"

    # --- Формируем данные для KMA ---
    payload = {
        "channel": CHANNEL,
        "name": name,
        "phone": phone,
        "ip": "85.193.122.162",
        "country": country,
        "referer": referer
    }

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/x-www-form-urlencoded",
    }

    # --- Отправка в KMA ---
    r = requests.post(API_URL, data=payload, headers=headers)

    return {"status": r.status_code, "response": r.json()}

if __name__ == "__main__":
    app.run(port=5000)
