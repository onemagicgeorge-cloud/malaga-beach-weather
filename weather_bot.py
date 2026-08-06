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
AEMET_PLAYA_ID = "2906707"  # La Malagueta, Málaga
# =====================================================

TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
AEMET_API_KEY = os.environ.get("AEMET_API_KEY", "").strip()

spain_tz = zoneinfo.ZoneInfo("Europe/Madrid")
spain_now = datetime.datetime.now(spain_tz)
current_hour = spain_now.hour

if 5 <= current_hour < 12:
    time_of_day = "morning"
elif 12 <= current_hour < 18:
    time_of_day = "midday"
else:
    time_of_day = "evening"

OPEN_METEO_URL = (
    f"https://api.open-meteo.com/v1/forecast?"
    f"latitude={LATITUDE}&longitude={LONGITUDE}"
    f"&current_weather=true"
    f"&hourly=temperature_2m,weathercode,wind_speed_10m,uv_index"
    f"&daily=temperature_2m_max,temperature_2m_min,weathercode,uv_index_max"
    f"&timezone=auto&forecast_days=2"
)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-2.5-flash:generateContent"
    f"?key={GEMINI_API_KEY}"
)

WEATHER_CODES = {
    0: "Ясно ☀️", 1: "Малохмарно 🌤", 2: "Хмарно ⛅",
    3: "Похмуро ☁️", 45: "Туман 🌫", 51: "Мряка 🌧",
    61: "Дощ 🌧", 71: "Сніг ❄️", 95: "Гроза ⛈"
}


def get_aemet_waves():
    if not AEMET_API_KEY:
        return None
    url = f"https://opendata.aemet.es/opendata/api/prediccion/especifica/playa/{AEMET_PLAYA_ID}/?api_key={AEMET_API_KEY}"
    try:
        r = requests.get(url, headers={"cache-control": "no-cache"}, timeout=10)
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get("estado") != 200:
            return None
        data_url = d.get("datos")
        if not data_url:
            return None
        r2 = requests.get(data_url, headers={"cache-control": "no-cache"}, timeout=10)
        if r2.status_code != 200:
            return None
        data = r2.json()
        today = datetime.date.today().strftime("%Y%m%d")
        for item in data:
            for dia in item.get("prediccion", {}).get("dia", []):
                if str(dia.get("fecha")) == today:
                    oleaje = dia.get("oleaje", {}).get("descripcion1", "")
                    if oleaje == "débil":
                        return "слабкі 🌊"
                    elif oleaje == "moderado":
                        return "помірні 🌊🌊"
                    elif oleaje == "fuerte":
                        return "сильні 🌊🌊🌊"
                    elif oleaje:
                        return oleaje
        return None
    except:
        return None


def get_all_data():
    for attempt in range(2):
        try:
            r = requests.get(OPEN_METEO_URL, timeout=15)
            r.raise_for_status()
            j = r.json()

            cur = j["current_weather"]
            hourly = j.get("hourly", {})
            daily = j.get("daily", {})

            now = datetime.datetime.now(datetime.timezone.utc)
            today_str = now.strftime("%Y-%m-%d")
            tomorrow_str = (now + datetime.timedelta(days=1)).strftime("%Y-%m-%d")

            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            codes = hourly.get("weathercode", [])
            winds = hourly.get("wind_speed_10m", [])
            uvs = hourly.get("uv_index", [])

            hourly_list = []
            for i, t in enumerate(times):
                if t.startswith(today_str):
                    h = int(t.split("T")[1].split(":")[0])
                    if 6 <= h <= 23:
                        hourly_list.append({
                            "hour": h,
                            "temp": temps[i] if i < len(temps) else None,
                            "code": codes[i] if i < len(codes) else None,
                            "wind": winds[i] if i < len(winds) else None,
                            "uv": uvs[i] if i < len(uvs) else None
                        })

            tomorrow = None
            for i, t in enumerate(daily.get("time", [])):
                if t == tomorrow_str:
                    tomorrow = {
                        "tmax": daily["temperature_2m_max"][i],
                        "tmin": daily["temperature_2m_min"][i],
                        "code": daily["weathercode"][i],
                        "uv": daily["uv_index_max"][i]
                    }
                    break

            uv_today = daily.get("uv_index_max", [None])[0]
            waves = get_aemet_waves()

            return {
                "current": {
                    "temp": cur["temperature"],
                    "wind": cur["windspeed"],
                    "code": cur["weathercode"]
                },
                "waves": waves,
                "uv_today": uv_today,
                "hourly": hourly_list,
                "tomorrow": tomorrow,
                "time_of_day": time_of_day
            }
        except Exception as e:
            print(f"Fetch error {attempt+1}: {e}")
            if attempt < 1:
                time.sleep(10)
    return None


def uv_label(val):
    if val is None:
        return ""
    if val <= 2:
        return f"{val} (низький)"
    elif val <= 5:
        return f"{val} (помірний)"
    elif val <= 7:
        return f"{val} (високий)"
    elif val <= 10:
        return f"{val} (дуже високий)"
    else:
        return f"{val} (екстремальний)"


def build_fallback(d):
    c = d["current"]
    cd = WEATHER_CODES.get(c["code"], f"Код {c['code']}")
    tod = d["time_of_day"]

    wave_str = f", хвилі: {d['waves']}" if d.get("waves") else ""

    if tod == "morning":
        msg = f"🌅 {BEACH_NAME} — доброго ранку!\n\n"
        msg += f"🌡 {c['temp']}°C, 💨 {c['wind']} км/год, 🌤 {cd}\n"
        if d.get("uv_today"):
            msg += f"☀️ UV: {uv_label(d['uv_today'])}\n"
        if wave_str:
            msg += f"🌊{wave_str}\n"
        msg += "\n📋 Погодинно:\n"
        for h in d["hourly"][::2]:
            hc = WEATHER_CODES.get(h["code"], "?")
            msg += f"  {h['hour']:02d}:00  {h['temp']}°C  {hc}  💨{h.get('wind','?')} км/год  ☀️UV{h.get('uv','?')}\n"

    elif tod == "midday":
        msg = f"☀️ {BEACH_NAME} — день!\n\n"
        msg += f"🌡 {c['temp']}°C, 💨 {c['wind']} км/год, 🌤 {cd}\n"
        if d.get("uv_today"):
            msg += f"☀️ UV: {uv_label(d['uv_today'])}\n"
        if wave_str:
            msg += f"🌊{wave_str}\n"
        msg += "\n📋 Друга половина дня:\n"
        for h in d["hourly"]:
            if h["hour"] >= 12:
                hc = WEATHER_CODES.get(h["code"], "?")
                msg += f"  {h['hour']:02d}:00  {h['temp']}°C  {hc}  💨{h.get('wind','?')} км/год  ☀️UV{h.get('uv','?')}\n"

    else:
        msg = f"🌙 {BEACH_NAME} — добрий вечір!\n\n"
        msg += f"🌡 {c['temp']}°C, 💨 {c['wind']} км/год, 🌤 {cd}\n"
        if wave_str:
            msg += f"🌊{wave_str}\n"
        if d.get("tomorrow"):
            t = d["tomorrow"]
            tc = WEATHER_CODES.get(t["code"], "?")
            msg += f"\n📋 Завтра: {t['tmin']}…{t['tmax']}°C, {tc}, UV {uv_label(t.get('uv'))}\n"

    msg += "\n⚠️ Перевірте прапори на пляжі!"
    return msg


def build_ai_message(d):
    c = d["current"]
    tod = d["time_of_day"]
    wave_str = f", хвилі: {d['waves']}" if d.get("waves") else ""

    if tod == "morning":
        prompt = f"Ти — пляжний експерт. Ранкове повідомлення українською (до 500 символів). Пляж: {BEACH_NAME}. Зараз: {c['temp']}°C, вітер {c['wind']} км/год, код {c['code']}{wave_str}. UV сьогодні: {d.get('uv_today','?')}. Прогноз:\n"
        for h in d["hourly"][::3]:
            prompt += f"  {h['hour']}:00 — {h['temp']}°C, вітер {h.get('wind','?')}, UV {h.get('uv','?')}, код {h['code']}\n"
        prompt += "Дай вердикт: чи йти на пляж, коли купатися, чи потрібен крем. Почни з привітання. Додай прапори. Емодзі."
    elif tod == "midday":
        prompt = f"Ти — пляжний експерт. Денне повідомлення українською (до 450 символів). Пляж: {BEACH_NAME}. Зараз: {c['temp']}°C, вітер {c['wind']} км/год, код {c['code']}{wave_str}. UV: {d.get('uv_today','?')}. Друга половина дня:\n"
        for h in d["hourly"]:
            if h["hour"] >= 12:
                prompt += f"  {h['hour']}:00 — {h['temp']}°C, вітер {h.get('wind','?')}, UV {h.get('uv','?')}, код {h['code']}\n"
        prompt += "Оціни умови для купання до вечора, UV-захист. Почни з «Добрий день!». Емодзі."
    else:
        prompt = f"Ти — пляжний експерт. Вечірнє повідомлення українською (до 450 символів). Пляж: {BEACH_NAME}. Зараз: {c['temp']}°C, вітер {c['wind']} км/год, код {c['code']}{wave_str}."
        if d.get("tomorrow"):
            t = d["tomorrow"]
            prompt += f" Завтра: {t['tmin']}…{t['tmax']}°C, код {t['code']}, UV {t.get('uv','?')}."
        prompt += " Опиши вечір, ніч, перспективи на завтра. Почни з «Добрий вечір!». Емодзі."

    data = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 500}
    }

    for attempt in range(3):
        try:
            r = requests.post(GEMINI_URL, json=data, timeout=20)
            if r.status_code == 200:
                return r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
            elif r.status_code == 429:
                wait = 5 * (attempt + 1)
                print(f"Gemini 429 — wait {wait}s")
                time.sleep(wait)
            else:
                print(f"Gemini error {r.status_code}")
                return None
        except Exception as e:
            print(f"Gemini attempt {attempt+1}: {e}")
            if attempt < 2:
                time.sleep(5 * (attempt + 1))
    return None


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(2):
        try:
            r = requests.post(url, json={"chat_id": CHANNEL_ID, "text": text}, timeout=10)
            r.raise_for_status()
            print("Sent!")
            return True
        except Exception as e:
            print(f"Telegram error {attempt+1}: {e}")
            if attempt < 1:
                time.sleep(5)
    return False


def main():
    print(f"=== Beach Weather Bot === {spain_now.strftime('%H:%M')} | {time_of_day}")
    d = get_all_data()
    if not d:
        print("FAIL: no data")
        sys.exit(1)

    print(f"Temp: {d['current']['temp']}°C, Waves: {d.get('waves', 'no')}")

    msg = build_ai_message(d) or build_fallback(d)
    if not msg:
        print("FAIL: empty message")
        sys.exit(1)

    if not send_telegram(msg):
        print("FAIL: send")
        sys.exit(1)

    print("=== Done ===")


if __name__ == "__main__":
    main()
