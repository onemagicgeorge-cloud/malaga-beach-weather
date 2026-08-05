import os
import sys
import time
import requests
import datetime
import zoneinfo

# ==================== НАЛАШТУВАННЯ ====================
LATITUDE = 36.6657
LONGITUDE = -4.4534
BEACH_NAME = "Playa Guadalhorce"
# =====================================================

TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
AEMET_API_KEY = os.environ.get("AEMET_API_KEY", "").strip()

# --- Час ---
spain_tz = zoneinfo.ZoneInfo("Europe/Madrid")
spain_now = datetime.datetime.now(spain_tz)
current_hour = spain_now.hour

# Визначаємо час доби
if 5 <= current_hour < 12:
    time_of_day = "morning"
elif 12 <= current_hour < 18:
    time_of_day = "midday"
else:
    time_of_day = "evening"

# --- URL-и ---
OPEN_METEO_URL = (
    f"https://api.open-meteo.com/v1/forecast?"
    f"latitude={LATITUDE}&longitude={LONGITUDE}"
    f"&current_weather=true"
    f"&hourly=temperature_2m,weathercode,sea_surface_temperature"
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


def fetch_aemet_waves():
    """Отримує опис хвиль через AEMET API (двоетапний запит)."""
    if not AEMET_API_KEY:
        print("AEMET: no API key")
        return None

    coast_url = (
        "https://opendata.aemet.es/opendata/api/prediccion/especifica/playa/"
        f"5429001/?api_key={AEMET_API_KEY}"
    )
    try:
        # Крок 1: отримуємо URL даних
        res1 = requests.get(coast_url, headers={"cache-control": "no-cache"}, timeout=10)
        if res1.status_code != 200:
            print(f"AEMET step1 error: {res1.status_code}")
            return None
        data1 = res1.json()
        if data1.get("estado") != 200:
            print(f"AEMET estado: {data1.get('estado')}")
            return None

        data_url = data1.get("datos")
        if not data_url:
            print("AEMET: no data URL")
            return None

        # Крок 2: отримуємо дані
        res2 = requests.get(data_url, headers={"cache-control": "no-cache"}, timeout=10)
        if res2.status_code != 200:
            print(f"AEMET step2 error: {res2.status_code}")
            return None

        playa_data = res2.json()
        today_str = datetime.date.today().strftime("%Y%m%d")  # AEMET формат: 20260805

        # Шукаємо прогноз на сьогодні
        for pred in playa_data:
            prediccion = pred.get("prediccion", {})
            for dia in prediccion.get("dia", []):
                fecha = str(dia.get("fecha", ""))
                if fecha == today_str:
                    oleaje = dia.get("oleaje", {})
                    desc1 = oleaje.get("descripcion1", "")
                    # Перекладаємо опис українською
                    traducciones = {
                        "débil": "слабкі 🌊",
                        "moderado": "помірні 🌊🌊",
                        "fuerte": "сильні 🌊🌊🌊"
                    }
                    return traducciones.get(desc1, desc1)
        return None
    except Exception as e:
        print(f"AEMET exception: {e}")
        return None


def fetch_all_data():
    for attempt in range(2):
        try:
            resp = requests.get(OPEN_METEO_URL, timeout=15)
            resp.raise_for_status()
            data = resp.json()

            current = data["current_weather"]
            hourly = data.get("hourly", {})
            daily = data.get("daily", {})

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            current_hour_utc = now_utc.hour

            times = hourly.get("time", [])
            water_temps = hourly.get("sea_surface_temperature", [])

            water_now = None
            target_time = now_utc.strftime("%Y-%m-%dT%H:00")
            for i, t in enumerate(times):
                if t == target_time:
                    if i < len(water_temps):
                        water_now = water_temps[i]
                    break

            if water_now is None and water_temps:
                water_now = water_temps[min(current_hour_utc, len(water_temps)-1)]

            today_str = now_utc.strftime("%Y-%m-%d")
            hourly_forecast = []
            for i, t in enumerate(times):
                if t.startswith(today_str):
                    h = int(t.split("T")[1].split(":")[0])
                    if 6 <= h <= 23:
                        hour_temp = hourly["temperature_2m"][i] if i < len(hourly["temperature_2m"]) else None
                        hour_code = hourly["weathercode"][i] if i < len(hourly["weathercode"]) else None
                        hourly_forecast.append({"hour": h, "temp": hour_temp, "code": hour_code})

            tomorrow_date = (now_utc + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
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

            # Отримуємо хвилі з AEMET
            wave_aemet = fetch_aemet_waves()

            return {
                "current": {
                    "temperature": current["temperature"],
                    "windspeed": current["windspeed"],
                    "weathercode": current["weathercode"]
                },
                "wave_now": wave_aemet,
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

    water_block = ""
    if d.get("water_now") is not None:
        water_block = f"🌊 Вода: {d['water_now']}°C"
        if d.get("wave_now") is not None:
            water_block += f", хвилі: {d['wave_now']}"
        water_block += "\n"

    hourly = d.get("hourly_forecast", [])
    trend_text = ""
    if len(hourly) >= 3:
        temps = [h["temp"] for h in hourly if h["temp"] is not None]
        codes = [h["code"] for h in hourly if h["code"] is not None]
        if temps:
            if max(temps) - min(temps) <= 3:
                temp_trend = "температура стабільна"
            elif temps[-1] > temps[0]:
                temp_trend = "потеплішає"
            else:
                temp_trend = "похолоднішає"
            if codes:
                sunny = sum(1 for c in codes if c in [0, 1])
                cloudy = sum(1 for c in codes if c in [2, 3])
                rainy = sum(1 for c in codes if c in [51, 61, 95])
                if rainy > len(codes)//2:
                    weather_trend = "очікується дощова погода"
                elif cloudy > sunny:
                    weather_trend = "буде хмарно"
                elif sunny > cloudy:
                    weather_trend = "переважно сонячно"
                else:
                    weather_trend = "мінлива хмарність"
                trend_text = f"📊 Загалом: {weather_trend}, {temp_trend}\n"

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
        if trend_text:
            msg += trend_text
        msg += "\n📋 Погодинно:\n"
        for h in hourly[::3]:
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
        afternoon = [h for h in hourly if h["hour"] >= 12]
        if len(afternoon) >= 2:
            temps_a = [h["temp"] for h in afternoon if h["temp"] is not None]
            if temps_a:
                if max(temps_a) - min(temps_a) <= 2:
                    msg += "📊 До вечора температура стабільна\n"
                elif temps_a[-1] < temps_a[0]:
                    msg += "📊 До вечора поступово похолоднішає\n"
                else:
                    msg += "📊 Температура протримається\n"
        msg += "\n📋 Друга половина дня:\n"
        for h in hourly:
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
            water_info += f", хвилі: {d['wave_now']}"
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

    # Retry-логіка з backoff для Gemini 429
    for attempt in range(3):
        try:
            resp = requests.post(GEMINI_URL, json=data, timeout=20)
            if resp.status_code == 200:
                result = resp.json()
                text = result["candidates"][0]["content"]["parts"][0]["text"]
                print(f"Gemini OK on attempt {attempt+1}")
                return text.strip()
            elif resp.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"Gemini 429 — retry in {wait}s (attempt {attempt+1}/3)")
                time.sleep(wait)
            else:
                print(f"Gemini error {resp.status_code}: {resp.text[:100]}")
                return None
        except Exception as e:
            print(f"Gemini attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
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
    print(f"=== Beach Weather Bot ===")
    print(f"Spain time: {spain_now.strftime('%H:%M')}, Time of day: {time_of_day}")

    d = fetch_all_data()
    if not d:
        print("FAIL: no data")
        sys.exit(1)

    print(f"Temp: {d['current']['temperature']}°C")
    if d.get("wave_now") is not None:
        print(f"Waves (AEMET): {d['wave_now']}")
    else:
        print("Waves: no data")

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
