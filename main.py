from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")  # Храним токен безопасно через env-переменные

def send_whatsapp_text(to_number: str, message: str, preview_url: bool = False):
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "text",
        "text": {
            "body": message,
            "preview_url": preview_url
        }
    }

    response = requests.post(WHATSAPP_API_URL, json=payload, headers=headers)

    if response.status_code == 201:
        return {"status": "success", "response": response.json()}
    else:
        return {"status": "error", "code": response.status_code, "message": response.text}

@app.route('/', methods=['GET'])
def home():
    return "✅ WhatsApp бот работает"

@app.route('/send', methods=['POST'])
def send():
    data = request.get_json()
    to = data.get("to")
    message = data.get("message")
    preview = data.get("preview_url", False)

    if not to or not message:
        return jsonify({"error": "Missing 'to' or 'message'"}), 400

    result = send_whatsapp_text(to, message, preview)
    return jsonify(result)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
