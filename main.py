from flask import Flask, request

app = Flask(__name__)

@app.route('/', methods=['GET', 'POST', 'HEAD'])
def webhook():
    if request.method == 'GET':
        return "Webhook is running!", 200
    elif request.method == 'POST':
        data = request.json
        print("Received message:", data)
        return "OK", 200
    elif request.method == 'HEAD':
        return '', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
