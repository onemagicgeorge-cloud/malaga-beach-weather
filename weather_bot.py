import os
import sys
import time
import requests

# ==================== НАЛАШТУВАННЯ ====================
LATITUDE = 36.6665
LONGITUDE = -4.4534
# =====================================================

TELEGRAM_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

OPEN_METEO_URL = (
    f"https://api.open-meteo.com/v1/forecast?"
    f"latitude={LATITUDE}&longitude={LONGITUDE}"
    f"&current_weather=true&timezone=auto"
)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.0-flash:generateContent"
    f"?key={GEMINI_API_KEY}"
)

def fetch_weather():
    """Отримує погоду (2 спроби з паузою 10 сек)."""
    for attempt in range(2):
        try:
            resp = requests.get(OPEN_METEO_URL, timeout=10)
            resp.raise_for_status()
            current = resp.json()["current_weather"]
            return {
                "temperature": current["temperature"],
                "windspeed": current["windspeed"],
                "weathercode": current["weathercode"]
            }
        except Exception as e:
            print(f"Weather attempt {attempt+1}: {e}")
            if attempt < 1:
                time.sleep(10)
    return None

def generate_fallback_message(w):
    """Просте повідомлення, якщо AI не відповів."""
    codes = {0: "Ясно ☀️", 1: "Малохмарно 🌤", 2: "Хмарно ⛅",
             3: "Похмуро ☁️", 45: "Туман 🌫", 51: "Мряка 🌧",
             61: "Дощ 🌧", 71: "Сніг ❄️", 95: "Гроза ⛈"}
    desc = codes.get(w["weathercode"], f"Код {w['weathercode']}")
    return (
        f"🌡 Температура: {w['temperature']}°C\n"
        f"💨 Вітер: {w['windspeed']} км/год\n"
        f"🌤 {desc}"
    )

def generate_ai_message(w):
    """Генерує AI-повідомлення (3 спроби з паузами)."""
    prompt = (
        "Ти — дружній пляжний метеоролог. "
        "Сформулюй коротке повідомлення українською мовою (до 250 символів) "
        "про поточну погоду, використовуючи ці дані: "
        f"температура {w['temperature']}°C, "
        f"швидкість вітру {w['windspeed']} км/год, "
        f"код погоди {w['weathercode']}. "
        "Коди: 0-ясно, 1-малохмарно, 2-хмарно, 3-похмуро, "
        "45-туман, 51-мряка, 61-дощ, 71-сніг, 95-гроза. "
        "Додай емодзі, будь позитивним."
    )
    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 200}
    }

    for attempt in range(3):
        try:
            resp = requests.post(GEMINI_URL, json=data, timeout=15)
            if resp.status_code == 200:
                result = resp.json()
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                print(f"Gemini OK on attempt {attempt+1}")
                return text.strip()
            elif resp.status_code == 429:
                wait = (attempt + 1) * 10  # 10, 20, 30 секунд
                print(f"Gemini 429 — retry in {wait}s (attempt {attempt+1}/3)")
                time.sleep(wait)
            else:
                print(f"Gemini error {resp.status_code}: {resp.text[:100]}")
                return None
        except Exception as e:
            print(f"Gemini attempt {attempt+1} exception: {e}")
            if attempt < 2:
                time.sleep(10)
    return None

def send_telegram_message(text):
    """Відправляє повідомлення в канал (2 спроби)."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(2):
        try:
            resp = requests.post(
                url,
                json={"chat_id": CHANNEL_ID, "text": text},
                timeout=10
            )
            resp.raise_for_status()
            print("Sent to Telegram!")
            return True
        except Exception as e:
            print(f"Telegram attempt {attempt+1}: {e}")
            if attempt < 1:
                time.sleep(5)
    return False

def main():
    print("=== Weather Bot Start ===")

    # 1. Погода
    weather = fetch_weather()
    if not weather:
        print("FAIL: Cannot fetch weather")
        sys.exit(1)
    print(f"Weather: {weather['temperature']}°C, wind {weather['windspeed']} km/h, code {weather['weathercode']}")

    # 2. Повідомлення (AI або fallback)
    ai_text = generate_ai_message(weather)
    final_message = ai_text or generate_fallback_message(weather)
    if not ai_text:
        print("Using fallback message")

    # 3. Відправка
    ok = send_telegram_message(final_message)
    if not ok:
        print("FAIL: Cannot send to Telegram")
        sys.exit(1)

    print("=== Weather Bot Done ===")

if __name__ == "__main__":
    main()
