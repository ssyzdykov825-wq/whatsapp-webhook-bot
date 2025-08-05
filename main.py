from flask import Flask, request

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    print("🔔 POST-запрос получен")
    try:
        data = request.get_json(force=True)
        print("📩 JSON:", data)
    except Exception as e:
        print("❌ Ошибка при получении JSON:", str(e))
    return "ok", 200

@app.route('/')
def index():
    return "Webhook is running!", 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
