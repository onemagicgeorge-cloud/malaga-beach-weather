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
AEMET_PLAYA_ID = "2906707"
# =====================================================

TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
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


def build_message(d):
    c = d["current"]
    cd = WEATHER_CODES.get(c["code"], f"Код {c['code']}")
    tod = d["time_of_day"]
    wave_val = d.get("waves")

    wave_line = f"🌊 Хвилі сьогодні: {wave_val}\n" if wave_val else ""
    wave_short = f" | 🌊{wave_val}" if wave_val else ""

    if tod == "morning":
        msg = f"🌅 {BEACH_NAME} — доброго ранку!\n\n"
        msg += f"🌡 Температура: {c['temp']}°C\n"
        msg += f"💨 Вітер: {c['wind']} км/год\n"
        msg += f"🌤 Небо: {cd}\n"
        if d.get("uv_today"):
            msg += f"☀️ UV сьогодні: {uv_label(d['uv_today'])}\n"
        msg += wave_line
        msg += "\n📋 Погодинний прогноз:\n"
        for h in d["hourly"][::2]:
            hc = WEATHER_CODES.get(h["code"], "?")
            msg += f"  {h['hour']:02d}:00 | {h['temp']}°C | {hc} | 💨{h.get('wind','?')} км/год | ☀️UV {h.get('uv','?')}{wave_short}\n"

    elif tod == "midday":
        msg = f"☀️ {BEACH_NAME} — день!\n\n"
        msg += f"🌡 Температура: {c['temp']}°C\n"
        msg += f"💨 Вітер: {c['wind']} км/год\n"
        msg += f"🌤 Небо: {cd}\n"
        if d.get("uv_today"):
            msg += f"☀️ UV зараз: {uv_label(d['uv_today'])}\n"
        msg += wave_line
        msg += "\n📋 Друга половина дня:\n"
        for h in d["hourly"]:
            if h["hour"] >= 12:
                hc = WEATHER_CODES.get(h["code"], "?")
                msg += f"  {h['hour']:02d}:00 | {h['temp']}°C | {hc} | 💨{h.get('wind','?')} км/год | ☀️UV {h.get('uv','?')}{wave_short}\n"

    else:
        msg = f"🌙 {BEACH_NAME} — добрий вечір!\n\n"
        msg += f"🌡 Температура: {c['temp']}°C\n"
        msg += f"💨 Вітер: {c['wind']} км/год\n"
        msg += f"🌤 Небо: {cd}\n"
        msg += wave_line
        if d.get("tomorrow"):
            t = d["tomorrow"]
            tc = WEATHER_CODES.get(t["code"], "?")
            msg += f"\n📋 Прогноз на завтра:\n"
            msg += f"  🌡 {t['tmin']}…{t['tmax']}°C\n"
            msg += f"  🌤 {tc}\n"
            msg += f"  ☀️ UV: {uv_label(t.get('uv'))}\n"

    return msg


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

    msg = build_message(d)
    if not send_telegram(msg):
        print("FAIL: send")
        sys.exit(1)

    print("=== Done ===")


if __name__ == "__main__":
    main()
