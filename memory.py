import json
import os

MEMORY_FILE = "chat_memory.json"

# Загружаем всю память из файла или создаём пустую
def load_all_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

# Сохраняем всю память в файл
def save_all_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

# Загружаем историю пользователя (телефон) — список сообщений GPT формата
def load_memory(phone):
    memory = load_all_memory()
    return memory.get(phone, [])

# Сохраняем историю пользователя (телефон)
def save_memory(phone, history):
    memory = load_all_memory()
    memory[phone] = history
    save_all_memory(memory)
