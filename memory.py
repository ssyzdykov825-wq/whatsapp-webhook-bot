import json
import os

MEMORY_FILE = "chat_memory.json"

def load_all_memory():
    print(f"[load_all_memory] Читаем из файла: {os.path.abspath(MEMORY_FILE)}")
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"[load_all_memory] Данные успешно загружены, ключей: {len(data)}")
            return data
        except json.JSONDecodeError as e:
            print(f"[load_all_memory] Ошибка JSON: {e}")
            return {}
        except Exception as e:
            print(f"[load_all_memory] Другая ошибка при чтении файла: {e}")
            return {}
    else:
        print("[load_all_memory] Файл не найден, возвращаем пустой словарь")
    return {}

def save_all_memory(memory):
    print(f"[save_all_memory] Сохраняем память в файл: {os.path.abspath(MEMORY_FILE)}")
    try:
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)
        print("[save_all_memory] Успешно сохранено")
    except Exception as e:
        print(f"[save_all_memory] Ошибка при сохранении: {e}")

def load_memory(phone):
    memory = load_all_memory()
    return memory.get(phone, [])

def save_memory(phone, history):
    memory = load_all_memory()
    memory[phone] = history
    save_all_memory(memory)
