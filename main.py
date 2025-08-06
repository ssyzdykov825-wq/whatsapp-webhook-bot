import requests

WHATSAPP_API_URL = "https://waba-v2.360dialog.io/messages"
WHATSAPP_TOKEN = "ASGoZdyRzzwoTVnk6Q1p4eRAAK"  # Замени на свой токен

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
        print("✅ Сообщение отправлено!")
        return response.json()
    else:
        print("❌ Ошибка при отправке:", response.status_code, response.text)
        return None
