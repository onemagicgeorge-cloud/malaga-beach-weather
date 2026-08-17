import os
import sys
import time
import random
import requests
import datetime
import zoneinfo
import math
import json

# ==================== НАЛАШТУВАННЯ ====================
LATITUDE = 36.7200
LONGITUDE = -4.4100
BEACH_NAME = "Playa de la Malagueta"
AEMET_PLAYA_ID = "2906707"
# =====================================================

TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
AEMET_API_KEY = os.environ.get("AEMET_API_KEY", "").strip()
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

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
    f"&hourly=temperature_2m,apparent_temperature,weathercode,wind_speed_10m,wind_direction_10m,precipitation_probability,uv_index,sea_surface_temperature"
    f"&daily=temperature_2m_max,temperature_2m_min,weathercode,uv_index_max,sunrise,sunset,precipitation_probability_max,wind_speed_10m_max"
    f"&timezone=auto&forecast_days=7"
)

WEATHER_CODES_SHORT = {
    0: "☀️", 1: "🌤", 2: "⛅",
    3: "☁️", 45: "🌫", 48: "🌫",
    51: "🌦", 53: "🌧", 55: "🌧",
    56: "🌧", 57: "🌧",
    61: "🌧", 63: "🌧", 65: "🌧",
    66: "🌧", 67: "🌧",
    71: "❄️", 73: "❄️", 75: "❄️",
    77: "❄️",
    80: "🌧", 81: "🌧", 82: "🌧",
    85: "❄️", 86: "❄️",
    95: "⛈", 96: "⛈", 99: "⛈"
}

WEATHER_CODES = {
    0: "Ясно ☀️", 1: "Малохмарно 🌤", 2: "Хмарно ⛅",
    3: "Похмуро ☁️", 45: "Туман 🌫", 48: "Паморозь 🌫",
    51: "Легка мряка 🌦", 53: "Помірна мряка 🌧", 55: "Сильна мряка 🌧",
    56: "Крижана мряка 🌧", 57: "Сильна крижана мряка 🌧",
    61: "Невеликий дощ 🌧", 63: "Помірний дощ 🌧", 65: "Сильний дощ 🌧",
    66: "Крижаний дощ 🌧", 67: "Сильний крижаний дощ 🌧",
    71: "Невеликий сніг ❄️", 73: "Помірний сніг ❄️", 75: "Сильний сніг ❄️",
    77: "Сніг з дощем ❄️",
    80: "Зливовий дощ 🌧", 81: "Помірна злива 🌧", 82: "Сильна злива 🌧",
    85: "Снігова злива ❄️", 86: "Сильна снігова злива ❄️",
    95: "Гроза ⛈", 96: "Гроза з градом ⛈", 99: "Сильна гроза з градом ⛈"
}

DAYS_UA = {
    0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт", 5: "Сб", 6: "Нд"
}

WIND_DIRECTIONS = [
    (0, 22.5, "Пн"), (22.5, 67.5, "ПнСх"), (67.5, 112.5, "Сх"),
    (112.5, 157.5, "ПдСх"), (157.5, 202.5, "Пд"), (202.5, 247.5, "ПдЗх"),
    (247.5, 292.5, "Зх"), (292.5, 337.5, "ПнЗх"), (337.5, 360.1, "Пн")
]


def rnd(val):
    if val is None:
        return None
    return int(math.floor(val + 0.5))


def wind_direction(deg):
    if deg is None:
        return "?"
    for lo, hi, label in WIND_DIRECTIONS:
        if lo <= deg < hi:
            return label
    return "Пн"


def wind_speed_level(speed):
    if speed is None:
        return 0, ""
    if speed < 6:
        return 0, "штиль"
    elif speed < 20:
        return 1, "легкий"
    elif speed < 40:
        return 2, "помірний"
    elif speed < 60:
        return 3, "сильний"
    else:
        return 4, "шторм"


def heat_index(temp, humidity=None):
    if temp is None:
        return None
    if humidity is None or humidity < 0:
        humidity = 50
    if temp < 27:
        return temp
    hi = (-8.7847 + 1.6114 * temp + 2.3385 * humidity
          - 0.1461 * temp * humidity - 0.0068 * temp ** 2
          - 0.0548 * humidity ** 2 + 0.0012 * temp ** 2 * humidity
          + 0.0008 * temp * humidity ** 2 - 0.000002 * temp ** 2 * humidity ** 2)
    return rnd(hi)


def beach_safety_score(uv, wind_speed, waves_desc, precip_prob):
    score = 100
    reasons = []

    if uv is not None:
        if uv >= 11:
            score -= 30
            reasons.append("extreme_uv")
        elif uv >= 8:
            score -= 20
            reasons.append("high_uv")
        elif uv >= 6:
            score -= 10
            reasons.append("moderate_uv")

    if wind_speed is not None:
        if wind_speed >= 60:
            score -= 30
            reasons.append("storm_wind")
        elif wind_speed >= 40:
            score -= 20
            reasons.append("strong_wind")
        elif wind_speed >= 20:
            score -= 5

    if waves_desc:
        if "сильні" in waves_desc or "fuerte" in waves_desc:
            score -= 25
            reasons.append("high_waves")
        elif "помірні" in waves_desc or "moderado" in waves_desc:
            score -= 10

    if precip_prob is not None and precip_prob >= 70:
        score -= 15
        reasons.append("rain")

    score = max(0, min(100, score))

    if score >= 80:
        emoji = "🟢"
        label = "Ідеально для пляжу!"
    elif score >= 60:
        emoji = "🟡"
        label = "Добре, але будь обережний"
    elif score >= 40:
        emoji = "🟠"
        label = "Не ідеально, краще обмежити час"
    else:
        emoji = "🔴"
        label = "Краще не йти на пляж"

    return score, emoji, label, reasons


def alerts(uv, wind_speed, waves_desc, precip_prob, weather_code, alerts_list):
    if uv is not None and uv >= 8:
        alerts_list.append(f"⚠️ ВИСОКИЙ UV ({uv}) — нанеси сонцезахисний крем SPF50+!")

    if wind_speed is not None and wind_speed >= 40:
        alerts_list.append(f"⚠️ СИЛЬНИЙ ВІТЕР ({wind_speed} км/г) — небезпечно для купання!")

    if waves_desc and ("сильні" in waves_desc or "fuerte" in waves_desc):
        alerts_list.append("⚠️ ВИСОКІ ХВИЛІ — купання небезпечне!")

    if weather_code is not None and weather_code >= 95:
        alerts_list.append("⛈ ГРОЗА — негайно залиш пляж!")

    if precip_prob is not None and precip_prob >= 80:
        alerts_list.append(f"🌧 ВИСОКА ЙМОВІРНІСТЬ ДОЩУ ({precip_prob}%)")

    if weather_code is not None and weather_code in (45, 48):
        alerts_list.append("🌫 ТУМАН — обережно на воді")


# ==================== КОМЕНТАР ДО ПОГОДИ ====================


def generate_commentary(d):
    c = d["current"]
    temp = c.get("temp", 20)
    uv = d.get("uv_now", 0)
    wind = c.get("wind", 0)
    wind_dir = c.get("wind_dir", "")
    waves = d.get("waves")
    precip = d.get("precip_now", 0)
    water = d.get("water_temp")
    tod = d.get("time_of_day", "midday")
    code = c.get("code", 0)
    hourly = d.get("hourly", [])

    lines = []

    # --- Коротко про зараз ---
    sky_desc = WEATHER_CODES.get(code, "невідомо").split(" ")[0]
    lines.append(f"Зараз {sky_desc.lower()}, {temp}°C, вітер {wind} км/г.")

    # --- Авто-попередження про дощ ---
    rain_hours = []
    for h in hourly[:12]:
        pp = h.get("precip_prob")
        if pp is not None and pp > 20:
            rain_hours.append(f"{h['hour']:02d}:00 ({pp}%)")

    if rain_hours:
        hours_str = ", ".join(rain_hours[:3])
        lines.append(f"Увага: очікується дощ о {hours_str} 🌧️")

    # --- Опис хвиль ---
    if waves:
        if "слабкі" in waves or "спокійн" in waves:
            lines.append(f"Хвилі слабкі ({waves}) — ідеально для купання.")
        elif "помірні" in waves:
            lines.append(f"Хвилі помірні ({waves}) — обережно з малими дітьми.")
        elif "сильні" in waves or "високі" in waves:
            lines.append(f"Хвилі сильні ({waves}) — краще не заходити глибоко.")
        else:
            lines.append(f"Хвилі: {waves}.")

    # --- Зміни протягом доби ---
    if hourly:
        max_temp_h = max((h.get("temp", 0) for h in hourly), default=temp)
        min_temp_h = min((h.get("temp", 100) for h in hourly), default=temp)
        max_wind_h = max((h.get("wind", 0) for h in hourly), default=wind)
        max_uv_h = max((h.get("uv", 0) for h in hourly), default=uv or 0)

        changes = []

        if max_temp_h > temp + 2:
            changes.append(f" температура підніметься до {max_temp_h}°C")
        elif min_temp_h < temp - 3:
            changes.append(f" температура опуститься до {min_temp_h}°C")

        if max_wind_h > wind + 15:
            changes.append(f" вітер посилиться до {max_wind_h} км/г")

        if max_uv_h >= 8:
            changes.append(f" UV-індекс сягне {max_uv_h}")

        if changes:
            lines.append("Зміни:" + ",".join(changes) + ".")

    # --- Порада ---
    safety = beach_safety_score(uv, wind, waves, precip)
    if safety[0] >= 80:
        lines.append("Ідеальний день для пляжу — користуйся!")
    elif safety[0] >= 60:
        lines.append("Добре для пляжу, але будь уважний.")
    elif safety[0] >= 40:
        lines.append("Не найкращий день — обмеж час на сонці.")
    else:
        lines.append("Краще не йти на пляж сьогодні.")

    return "\n".join(lines)


# ==================== ОПИС ПОГОДИ НА ДОБУ (GROQ) ====================

def generate_daily_description(d):
    if not GROQ_API_KEY:
        return None

    c = d["current"]
    hourly = d.get("hourly", [])

    current_summary = (
        f"Поточна погода: температура {c['temp']}°C (відчувається як {c.get('apparent', c['temp'])}°C), "
        f"вітер {c['wind']} км/г {c['wind_dir']}, небо: {WEATHER_CODES.get(c['code'], 'невідомо')}, "
        f"вода: {d.get('water_temp', '?')}°C, UV: {d.get('uv_now', '?')}, "
        f"хвилі: {d.get('waves', 'невідомо')}, ймовірність дощу: {d.get('precip_now', '?')}%"
    )

    hourly_summary = "Погодинний прогноз:\n"
    for h in hourly[:12]:
        hc = WEATHER_CODES.get(h.get("code"), "?")
        hourly_summary += (
            f"  {h['hour']:02d}:00 - {h['temp']}°C, {hc}, "
            f"вітер {h.get('wind', '?')} км/г, "
            f"UV: {h.get('uv', '?')}\n"
        )

    prompt = f"""Ти — бот пляжного погоди в Малазі, Іспанія. Пиши українською мовою.
Напиши короткий (3-5 речень) опис погоди на наступні 12 годин на пляжі Playa de la Malagueta.
Будь креативним, дотепним, але корисним. Порадь, чи варто йти на пляж.
Не використовуй емодзі. Пиши як розмовна людина.

{current_summary}

{hourly_summary}"""

    try:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "openai/gpt-oss-20b",
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "max_tokens": 500
        }
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=30
        )
        if r.status_code == 200:
            data = r.json()
            return data["choices"][0]["message"]["content"].strip()
        else:
            print(f"GROQ API error {r.status_code}: {r.text[:200]}")
            return None
    except Exception as e:
        print(f"GROQ error: {e}")
        return None


# ==================== КІНЕЦЬ ====================


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

            times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            apparent = hourly.get("apparent_temperature", [])
            codes = hourly.get("weathercode", [])
            winds = hourly.get("wind_speed_10m", [])
            wind_dirs = hourly.get("wind_direction_10m", [])
            precip_probs = hourly.get("precipitation_probability", [])
            uvs = hourly.get("uv_index", [])
            sea_temps = hourly.get("sea_surface_temperature", [])

            target_time = spain_now.strftime("%Y-%m-%dT%H:00")

            # Поточна температура води
            water_now = None
            for i, t in enumerate(times):
                if t == target_time:
                    if i < len(sea_temps) and sea_temps[i] is not None:
                        water_now = sea_temps[i]
                    break
            if water_now is None and sea_temps:
                for i, t in enumerate(times):
                    if t.startswith(today_str) and i < len(sea_temps) and sea_temps[i] is not None:
                        water_now = sea_temps[i]
                        break

            # Поточний UV
            uv_now = None
            for i, t in enumerate(times):
                if t == target_time and i < len(uvs) and uvs[i] is not None:
                    uv_now = uvs[i]
                    break
            if uv_now is None and uvs:
                for i, t in enumerate(times):
                    if t.startswith(today_str) and i < len(uvs) and uvs[i] is not None:
                        uv_now = uvs[i]
                        break

            # Поточний apparent temperature
            apparent_now = None
            for i, t in enumerate(times):
                if t == target_time and i < len(apparent) and apparent[i] is not None:
                    apparent_now = apparent[i]
                    break
            if apparent_now is None and apparent:
                for i, t in enumerate(times):
                    if t.startswith(today_str) and i < len(apparent) and apparent[i] is not None:
                        apparent_now = apparent[i]
                        break

            # Поточний precip probability
            precip_now = None
            for i, t in enumerate(times):
                if t == target_time and i < len(precip_probs) and precip_probs[i] is not None:
                    precip_now = precip_probs[i]
                    break
            if precip_now is None and precip_probs:
                for i, t in enumerate(times):
                    if t.startswith(today_str) and i < len(precip_probs) and precip_probs[i] is not None:
                        precip_now = precip_probs[i]
                        break

            # Поточний вітер (напрямок)
            wind_dir_now = None
            for i, t in enumerate(times):
                if t == target_time and i < len(wind_dirs) and wind_dirs[i] is not None:
                    wind_dir_now = wind_dirs[i]
                    break

            # 24-годинний прогноз
            start_index = None
            for i, t in enumerate(times):
                if t >= target_time:
                    start_index = i
                    break
            if start_index is None:
                start_index = 0

            hourly_list = []
            for i in range(start_index, min(start_index + 24, len(times))):
                t = times[i]
                h = int(t.split("T")[1].split(":")[0])
                hourly_list.append({
                    "hour": h,
                    "temp": rnd(temps[i]) if i < len(temps) else None,
                    "apparent": rnd(apparent[i]) if i < len(apparent) and apparent[i] is not None else None,
                    "code": codes[i] if i < len(codes) else None,
                    "wind": rnd(winds[i]) if i < len(winds) else None,
                    "wind_dir": wind_direction(wind_dirs[i] if i < len(wind_dirs) else None),
                    "precip_prob": precip_probs[i] if i < len(precip_probs) and precip_probs[i] is not None else None,
                    "uv": rnd(uvs[i]) if i < len(uvs) else None,
                    "water": rnd(sea_temps[i]) if i < len(sea_temps) and sea_temps[i] is not None else None
                })

            # 7-денний прогноз
            daily_dates = daily.get("time", [])
            daily_max = daily.get("temperature_2m_max", [])
            daily_min = daily.get("temperature_2m_min", [])
            daily_codes = daily.get("weathercode", [])
            daily_uv_max = daily.get("uv_index_max", [])
            daily_sunrise = daily.get("sunrise", [])
            daily_sunset = daily.get("sunset", [])
            daily_precip_max = daily.get("precipitation_probability_max", [])
            daily_wind_max = daily.get("wind_speed_10m_max", [])

            daily_list = []
            for i in range(len(daily_dates)):
                date = daily_dates[i]
                dt = datetime.datetime.strptime(date, "%Y-%m-%d")
                dow = DAYS_UA[dt.weekday()]

                sunrise_str = None
                sunset_str = None
                if i < len(daily_sunrise) and daily_sunrise[i]:
                    try:
                        sr = datetime.datetime.fromisoformat(daily_sunrise[i])
                        sunrise_str = sr.strftime("%H:%M")
                    except:
                        pass
                if i < len(daily_sunset) and daily_sunset[i]:
                    try:
                        ss = datetime.datetime.fromisoformat(daily_sunset[i])
                        sunset_str = ss.strftime("%H:%M")
                    except:
                        pass

                daily_list.append({
                    "date": date,
                    "day": dow,
                    "max": rnd(daily_max[i]) if i < len(daily_max) else None,
                    "min": rnd(daily_min[i]) if i < len(daily_min) else None,
                    "code": daily_codes[i] if i < len(daily_codes) else None,
                    "uv_max": rnd(daily_uv_max[i]) if i < len(daily_uv_max) else None,
                    "precip_max": daily_precip_max[i] if i < len(daily_precip_max) and daily_precip_max[i] is not None else None,
                    "wind_max": rnd(daily_wind_max[i]) if i < len(daily_wind_max) else None,
                    "sunrise": sunrise_str,
                    "sunset": sunset_str
                })

            waves = get_aemet_waves()

            return {
                "current": {
                    "temp": rnd(cur["temperature"]),
                    "apparent": rnd(apparent_now),
                    "wind": rnd(cur["windspeed"]),
                    "wind_dir": wind_direction(wind_dir_now),
                    "code": cur["weathercode"]
                },
                "water_temp": rnd(water_now),
                "uv_now": rnd(uv_now),
                "precip_now": precip_now,
                "waves": waves,
                "hourly": hourly_list,
                "daily": daily_list,
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
    tod = d["time_of_day"]
    wave_val = d.get("waves")
    water_val = d.get("water_temp")
    uv_val = d.get("uv_now")
    precip_val = d.get("precip_now")
    hourly = d.get("hourly", [])

    # === ЗАГОЛОВОК ===
    date_str = spain_now.strftime("%d.%m.%Y")
    msg = f"🌊 {BEACH_NAME} — {date_str}\n\n"

    # === ПОГОДА ЗАРАЗ ===
    msg += "🔵 Погода зараз:\n"
    msg += f"🌡 Температура: {c['temp']}°C (відчувається як {c.get('apparent', c['temp'])}°C)\n"
    msg += f"☁️ Небо: {WEATHER_CODES.get(c['code'], 'невідомо').split(' ')[0]}\n"
    msg += f"💨 Вітер: {c['wind']} км/г {c['wind_dir']}\n"
    if wave_val:
        msg += f"🌊 Хвилі: {wave_val}\n"
    if uv_val is not None:
        msg += f"☀️ UV-індекс: {uv_label(uv_val)}\n"
    if precip_val is not None:
        rain_status = "без опадів" if precip_val < 20 else "можливий дощ" if precip_val < 50 else "ймовірний дощ"
        msg += f"🌧 Опади: {precip_val}% ({rain_status})\n"

    # === РЕЙТИНГ БЕЗПЕКИ ===
    safety_score, safety_emoji, safety_label, _ = beach_safety_score(
        uv_val, c['wind'], wave_val, precip_val
    )
    msg += f"🟢 Рейтинг пляжу: {safety_score}/100 ({safety_label})\n\n"

    # === КОРОТКО ПРО ПОГОДУ ===
    commentary = generate_commentary(d)
    msg += f"💡 Коротко про погоду:\n{commentary}\n\n"

    # === ПОГОДИННИЙ ПРОГНОЗ ===
    msg += "📋 Погодинний прогноз:\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for h in hourly:
        hc = WEATHER_CODES_SHORT.get(h["code"], "?")
        precip_h = h.get("precip_prob")
        if precip_h is not None and precip_h > 0:
            hc = "🌧" if precip_h < 70 else "⛈"
        wind_str = f"{h.get('wind', 0):>2}" if h.get('wind') is not None else " ?"
        msg += f"{h['hour']:02d}:00 │ {h['temp']}° {hc} │ 💨{wind_str} │ UV {h.get('uv', '?')}\n"

    # === 7-ДЕННИЙ ПРОГНОЗ ===
    msg += "\n📅 Прогноз на тиждень:\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for day in d["daily"]:
        dc = WEATHER_CODES_SHORT.get(day["code"], "?")
        date_parts = day["date"].split("-")
        short_date = f"{date_parts[2]}.{date_parts[1]}"
        wind_str = f"{day['wind_max']:>2}" if day.get('wind_max') is not None else " ?"
        msg += f"{day['day']} {short_date} │ {day['min']}°/{day['max']}° │ {dc} │ 💨{wind_str} │ UV {day.get('uv_max', '?')}\n"

    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🤖 @malaga_beach_weather"

    return msg


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(2):
        try:
            r = requests.post(url, json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}, timeout=10)
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

    print(f"Temp: {d['current']['temp']}°C, Water: {d.get('water_temp', '?')}°C, UV: {d.get('uv_now', '?')}, Waves: {d.get('waves', 'no')}")

    msg = build_message(d)
    print(f"Message length: {len(msg)} chars")

    if not send_telegram(msg):
        print("FAIL: send")
        sys.exit(1)

    print("=== Done ===")


if __name__ == "__main__":
    main()
