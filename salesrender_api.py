import requests

SALESRENDER_URL = "https://de.backend.salesrender.com/companies/1123/CRM"
SALESRENDER_TOKEN = "Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiJodHRwczovL2RlLmJhY2tlbmQuc2FsZXNyZW5kZXIuY29tLyIsImF1ZCI6IkNSTSIsImp0aSI6ImI4MjZmYjExM2Q4YjZiMzM3MWZmMTU3MTMwMzI1MTkzIiwiaWF0IjoxNzU0NzM1MDE3LCJ0eXBlIjoiYXBpIiwiY2lkIjoiMTEyMyIsInJlZiI6eyJhbGlhcyI6IkFQSSIsImlkIjoiMiJ9fQ.z6NiuV4g7bbdi_1BaRfEqDj-oZKjjniRJoQYKgWsHcc"

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": SALESRENDER_TOKEN
}

def create_order(full_name, phone):
    """Создаёт заказ в SalesRender с телефоном и ФИО"""
    mutation = """
    mutation($firstName: String!, $lastName: String!, $phone: String!) {
      orderMutation {
        addOrder(
          input: {
            projectId: 1
            statusId: 1
            orderData: {
              humanNameFields: [
                { field: "name", value: { firstName: $firstName, lastName: $lastName } }
              ]
              phoneFields: [
                { field: "phone", value: $phone }
              ]
            }
          }
        ) {
          id
        }
      }
    }
    """

    # Разделяем имя на имя/фамилию
    name_parts = full_name.strip().split(" ", 1)
    first_name = name_parts[0]
    last_name = name_parts[1] if len(name_parts) > 1 else ""

    variables = {
        "firstName": first_name,
        "lastName": last_name,
        "phone": phone
    }

    try:
        response = requests.post(
            SALESRENDER_URL,
            json={"query": mutation, "variables": variables},
            headers=HEADERS
        )
        data = response.json()
        print("📦 Ответ создания заказа:", data)

        if "errors" in data:
            return None

        return data["data"]["orderMutation"]["addOrder"]["id"]

    except Exception as e:
        print(f"❌ Ошибка при создании заказа: {e}")
        return None
