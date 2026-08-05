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
    resp = requests.get(OPEN_METEO_URL)
    resp.raise_for_status()
    current = resp.json()["current_weather"]
    return {
        "temperature": current["temperature"],
        "windspeed": current["windspeed"],
        "weathercode": current["weathercode"]
    }

def generate_fallback_message(w):
    return (
        f"🌡 Температура: {w['temperature']}°C\n"
        f"💨 Вітер: {w['windspeed']} км/год\n"
        f"🌤 Код погоди: {w['weathercode']}"
    )

def generate_ai_message(w):
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
    resp = requests.post(GEMINI_URL, json=data)
    if resp.status_code != 200:
        print(f"Gemini error: {resp.status_code}")
        return None
    try:
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError):
        return None

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": CHANNEL_ID, "text": text})
    resp.raise_for_status()

def main():
    weather = None
    for attempt in range(2):
        try:
            weather = fetch_weather()
            break
        except Exception as e:
            print(f"Weather attempt {attempt+1}: {e}")
            time.sleep(5)
    if not weather:
        sys.exit(1)

    ai_text = None
    for attempt in range(2):
        try:
            ai_text = generate_ai_message(weather)
            if ai_text:
                break
        except Exception as e:
            print(f"AI attempt {attempt+1}: {e}")
            time.sleep(5)

    final_message = ai_text or generate_fallback_message(weather)
    
    for attempt in range(2):
        try:
            send_telegram_message(final_message)
            print("Sent!")
            break
        except Exception as e:
            print(f"Send attempt {attempt+1}: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
