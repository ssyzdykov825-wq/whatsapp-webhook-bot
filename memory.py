import json
import os
from datetime import datetime, timedelta

MEMORY_FILE = "chat_memory.json"

# Загружаем память при старте или создаём пустую
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        try:
            chat_memory = json.load(f)
            # Конвертируем строки времени обратно в datetime
            for phone in chat_memory:
                chat_memory[phone] = [
                    (sender, text, datetime.fromisoformat(time_str))
                    for sender, text, time_str in chat_memory[phone]
                ]
        except json.JSONDecodeError:
            chat_memory = {}
else:
    chat_memory = {}

def save_to_file():
    """Сохраняем память в файл"""
    serializable_data = {
        phone: [(sender, text, time.isoformat()) for sender, text, time in messages]
        for phone, messages in chat_memory.items()
    }
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(serializable_data, f, ensure_ascii=False, indent=2)

def save_message(phone, sender, text):
    """Сохраняем сообщение клиента или бота"""
    now = datetime.now()
    if phone not in chat_memory:
        chat_memory[phone] = []
    chat_memory[phone].append((sender, text, now))
    save_to_file()

def load_memory(phone):
    """Загружает историю в формате GPT (list of dicts)"""
    if phone not in chat_memory or not chat_memory[phone]:
        return []
    raw_msgs = chat_memory[phone][-40:]  # последние 40 сообщений
    result = []
    for sender, text, _ in raw_msgs:
        role = "user" if sender == "client" else "assistant"
        result.append({"role": role, "content": text})
    return result

def save_memory(phone, history):
    """Сохраняет историю из формата GPT в локальное хранилище"""
    now = datetime.now()
    chat_memory[phone] = []
    for msg in history:
        sender = "client" if msg["role"] == "user" else "assistant"
        chat_memory[phone].append((sender, msg["content"], now))
    save_to_file()

def get_recent_history(phone, hours=48):
    """Возвращает историю в виде строки (если нужна)"""
    if phone not in chat_memory or not chat_memory[phone]:
        return ""

    last_time = chat_memory[phone][-1][2]
    if datetime.now() - last_time > timedelta(hours=hours):
        chat_memory[phone] = []
        save_to_file()
        return ""

    history = []
    for sender, text, _ in chat_memory[phone]:
        role = "Клиент" if sender == "client" else "Бот"
        history.append(f"{role}: {text}")
    return "\n".join(history)
