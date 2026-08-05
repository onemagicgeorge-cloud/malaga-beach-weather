import os
import sys
import time
import requests
import datetime

# ==================== НАЛАШТУВАННЯ ====================
LATITUDE = 36.6665
LONGITUDE = -4.4534
BEACH_NAME = "Пляж Малагуета"
# =====================================================

TELEGRAM_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

OPEN_METEO_URL = (
    f"https://api.open-meteo.com/v1/forecast?"
    f"latitude={LATITUDE}&longitude={LONGITUDE}"
    f"&current_weather=true"
    f"&hourly=temperature_2m,weathercode,wave_height,sea_surface_temperature"
    f"&daily=temperature_2m_max,temperature_2m_min,weathercode,uv_index_max"
    f"&timezone=auto"
    f"&forecast_days=2"
)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.0-flash:generateContent"
    f"?key={GEMINI_API_KEY}"
)

WEATHER_CODES = {
    0: "Ясно ☀️", 1: "Малохмарно 🌤", 2: "Хмарно ⛅",
    3: "Похмуро ☁️", 45: "Туман 🌫", 51: "Мряка 🌧",
    61: "Дощ 🌧", 71: "Сніг ❄️", 95: "Гроза ⛈"
}

def fetch_all_data():
    for attempt in range(2):
        try:
            resp = requests.get(OPEN_METEO_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            current = data["current_weather"]
            hourly = data.get("hourly", {})
            daily = data.get("daily", {})

            now = datetime.datetime.now(datetime.timezone.utc)
            current_hour = now.hour

            times = hourly.get("time", [])
            waves = hourly.get("wave_height", [])
            water_temps = hourly.get("sea_surface_temperature", [])

            wave_now = None
            water_now = None
            target_time = now.strftime("%Y-%m-%dT%H:00")
            for i, t in enumerate(times):
                if t == target_time:
                    if i < len(waves):
                        wave_now = waves[i]
                    if i < len(water_temps):
                        water_now = water_temps[i]
                    break

            if wave_now is None and waves:
                wave_now = waves[min(current_hour, len(waves)-1)]
            if water_now is None and water_temps:
                water_now = water_temps[min(current_hour, len(water_temps)-1)]

            today_str = now.strftime("%Y-%m-%d")
            hourly_forecast = []
            for i, t in enumerate(times):
                if t.startswith(today_str):
                    h = int(t.split("T")[1].split(":")[0])
                    if 6 <= h <= 23:
                        hour_temp = hourly["temperature_2m"][i] if i < len(hourly["temperature_2m"]) else None
                        hour_code = hourly["weathercode"][i] if i < len(hourly["weathercode"]) else None
                        hourly_forecast.append({"hour": h, "temp": hour_temp, "code": hour_code})

            tomorrow_date = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            tomorrow_forecast = None
            daily_times = daily.get("time", [])
            for i, t in enumerate(daily_times):
                if t == tomorrow_date:
                    tomorrow_forecast = {
                        "temp_max": daily["temperature_2m_max"][i] if i < len(daily["temperature_2m_max"]) else None,
                        "temp_min": daily["temperature_2m_min"][i] if i < len(daily["temperature_2m_min"]) else None,
                        "code": daily["weathercode"][i] if i < len(daily["weathercode"]) else None,
                        "uv": daily["uv_index_max"][i] if i < len(daily["uv_index_max"]) else None
                    }
                    break

            uv_today = daily.get("uv_index_max", [None])[0]

            if 5 <= current_hour < 12:
                time_of_day = "morning"
            elif 12 <= current_hour < 17:
                time_of_day = "midday"
            else:
                time_of_day = "evening"

            return {
                "current": {
                    "temperature": current["temperature"],
                    "windspeed": current["windspeed"],
                    "weathercode": current["weathercode"]
                },
                "wave_now": wave_now,
                "water_now": water_now,
                "uv_today": uv_today,
                "hourly_forecast": hourly_forecast,
                "tomorrow": tomorrow_forecast,
                "time_of_day": time_of_day
            }
        except Exception as e:
            print(f"Fetch attempt {attempt+1}: {e}")
            if attempt < 1:
                time.sleep(10)
    return None

def generate_fallback_message(d):
    c = d["current"]
    code_desc = WEATHER_CODES.get(c["weathercode"], f"Код {c['weathercode']}")
    tod = d["time_of_day"]

    # Загальний блок з водою та хвилями
    water_block = ""
    if d.get("water_now") is not None:
        water_block = f"🌊 Вода: {d['water_now']}°C"
        if d.get("wave_now") is not None:
            water_block += f", хвилі: {d['wave_now']} м"
        water_block += "\n"

    if tod == "morning":
        msg = f"🌅 {BEACH_NAME} — доброго ранку!\n\n"
        msg += f"🌡 Зараз: {c['temperature']}°C\n"
        msg += f"💨 Вітер: {c['windspeed']} км/год\n"
        msg += f"🌤 {code_desc}\n"
        msg += water_block
        if d.get("uv_today") is not None:
            uv = d["uv_today"]
            uv_note = "низький" if uv <= 2 else "помірний" if uv <= 5 else "високий" if uv <= 7 else "дуже високий" if uv <= 10 else "екстремальний"
            msg += f"☀️ UV: {uv} ({uv_note})\n"
        msg += "\n📋 Сьогодні:\n"
        for h in d.get("hourly_forecast", [])[::3]:
            h_code = WEATHER_CODES.get(h["code"], "?")
            msg += f"  {h['hour']:02d}:00 — {h['temp']}°C, {h_code}\n"

    elif tod == "midday":
        msg = f"☀️ {BEACH_NAME} — день!\n\n"
        msg += f"🌡 Зараз: {c['temperature']}°C\n"
        msg += f"💨 Вітер: {c['windspeed']} км/год\n"
        msg += f"🌤 {code_desc}\n"
        msg += water_block
        if d.get("uv_today") is not None:
            uv = d["uv_today"]
            uv_note = "низький" if uv <= 2 else "помірний" if uv <= 5 else "високий" if uv <= 7 else "дуже високий" if uv <= 10 else "екстремальний"
            msg += f"☀️ UV: {uv} ({uv_note})\n"
        msg += "\n📋 Друга половина дня:\n"
        for h in d.get("hourly_forecast", []):
            if h["hour"] >= 12:
                h_code = WEATHER_CODES.get(h["code"], "?")
                msg += f"  {h['hour']:02d}:00 — {h['temp']}°C, {h_code}\n"

    else:
        msg = f"🌙 {BEACH_NAME} — добрий вечір!\n\n"
        msg += f"🌡 Зараз: {c['temperature']}°C\n"
        msg += f"💨 Вітер: {c['windspeed']} км/год\n"
        msg += f"🌤 {code_desc}\n"
        msg += water_block
        if d.get("tomorrow"):
            t = d["tomorrow"]
            t_code = WEATHER_CODES.get(t["code"], "?")
            msg += f"\n📋 Завтра: {t['temp_min']}…{t['temp_max']}°C, {t_code}\n"
            if t.get("uv") is not None:
                uv = t["uv"]
                uv_note = "низький" if uv <= 2 else "помірний" if uv <= 5 else "високий" if uv <= 7 else "дуже високий" if uv <= 10 else "екстремальний"
                msg += f"☀️ UV завтра: {uv} ({uv_note})\n"

    msg += "\n⚠️ Перевірте прапори на пляжі!"
    return msg

def generate_ai_message(d):
    c = d["current"]
    tod = d["time_of_day"]

    water_info = ""
    if d.get("water_now") is not None:
        water_info = f"Вода: {d['water_now']}°C"
        if d.get("wave_now") is not None:
            water_info += f", хвилі: {d['wave_now']} м"
        water_info += "\n"

    if tod == "morning":
        prompt = (
            "Ти — дружній пляжний експерт. Напиши ранкове повідомлення "
            f"українською (до 400 символів) для пляжу {BEACH_NAME}.\n"
            f"Зараз: {c['temperature']}°C, вітер {c['windspeed']} км/год, "
            f"код погоди {c['weathercode']}\n"
            f"{water_info}"
        )
        if d.get("uv_today") is not None:
            prompt += f"UV сьогодні: {d['uv_today']} (0-2=низький, 3-5=помірний, 6-7=високий, 8+=дуже високий)\n"
        prompt += "Погодинний прогноз на сьогодні (вибірково):\n"
        for h in d.get("hourly_forecast", [])[::4]:
            prompt += f"  {h['hour']}:00 — {h['temp']}°C, код {h['code']}\n"
        prompt += (
            "Дай вердикт: чи йти на пляж сьогодні, коли найкраще купатися, "
            "чи потрібен крем. Почни з привітання та назви пляжу. Додай "
            "нагадування про прапори. Використовуй емодзі."
        )
    elif tod == "midday":
        prompt = (
            "Ти — дружній пляжний експерт. Напиши денне повідомлення "
            f"українською (до 350 символів) для пляжу {BEACH_NAME}.\n"
            f"Зараз: {c['temperature']}°C, вітер {c['windspeed']} км/год, "
            f"код погоди {c['weathercode']}\n"
            f"{water_info}"
        )
        if d.get("uv_today") is not None:
            prompt += f"UV: {d['uv_today']} (0-2=низький, 3-5=помірний, 6-7=високий, 8+=дуже високий)\n"
        prompt += "Прогноз на другу половину дня:\n"
        for h in d.get("hourly_forecast", []):
            if h["hour"] >= 12:
                prompt += f"  {h['hour']}:00 — {h['temp']}°C, код {h['code']}\n"
        prompt += (
            "Оціни умови для купання зараз і до вечора. Порадь щодо UV-захисту. "
            "Почни з «Добрий день!» та назви пляжу. Використовуй емодзі."
        )
    else:
        prompt = (
            "Ти — дружній пляжний експерт. Напиши вечірнє повідомлення "
            f"українською (до 350 символів) для пляжу {BEACH_NAME}.\n"
            f"Зараз: {c['temperature']}°C, вітер {c['windspeed']} км/год, "
            f"код погоди {c['weathercode']}\n"
            f"{water_info}"
        )
        if d.get("tomorrow"):
            t = d["tomorrow"]
            prompt += (
                f"Прогноз на завтра: {t['temp_min']}…{t['temp_max']}°C, "
                f"код {t['code']}, UV {t.get('uv', '?')}\n"
            )
        prompt += (
            "Опиши поточну погоду, прогноз на ніч, перспективи на завтра "
            "для пляжу. Почни з «Добрий вечір!» та назви пляжу. Використовуй емодзі."
        )

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 300}
    }

    for attempt in range(3):
        try:
            resp = requests.post(GEMINI_URL, json=data, timeout=20)
            if resp.status_code == 200:
                result = resp.json()
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                print(f"Gemini OK on attempt {attempt+1}")
                return text.strip()
            elif resp.status_code == 429:
                wait = (attempt + 1) * 10
                print(f"Gemini 429 — retry in {wait}s")
                time.sleep(wait)
            else:
                print(f"Gemini error {resp.status_code}: {resp.text[:100]}")
                return None
        except Exception as e:
            print(f"Gemini attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(10)
    return None

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(2):
        try:
            resp = requests.post(url, json={"chat_id": CHANNEL_ID, "text": text}, timeout=10)
            resp.raise_for_status()
            print("Sent!")
            return True
        except Exception as e:
            print(f"Telegram attempt {attempt+1}: {e}")
            if attempt < 1:
                time.sleep(5)
    return False

def main():
    print("=== Beach Weather Bot ===")
    d = fetch_all_data()
    if not d:
        print("FAIL: no data")
        sys.exit(1)

    print(f"Time of day: {d['time_of_day']}, Temp: {d['current']['temperature']}°C")

    ai_text = generate_ai_message(d)
    final = ai_text or generate_fallback_message(d)
    if not ai_text:
        print("Using fallback")

    ok = send_telegram_message(final)
    if not ok:
        print("FAIL: send")
        sys.exit(1)

    print("=== Done ===")

if __name__ == "__main__":
    main()
