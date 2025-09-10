from flask import Flask, request

app = Flask(__name__)

VERIFY_TOKEN = "leadbot"  # сюда вставь тот же токен, что в Meta

@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403
