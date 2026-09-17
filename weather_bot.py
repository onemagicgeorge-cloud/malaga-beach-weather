import os
import sys
import time
import requests
import datetime
import zoneinfo
import math

# ==================== НАЛАШТУВАННЯ ====================
LATITUDE = 37.1919444444
LONGITUDE = -6.9961111111
BEACH_NAME = "Playa de Punta Umbría"

# Координати для температури води (ближче до берега пляжу)
WATER_LATITUDE = 37.18
WATER_LONGITUDE = -6.996
# =====================================================

TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

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
    f"&current=temperature_2m,apparent_temperature,weathercode,wind_speed_10m,wind_direction_10m,relative_humidity_2m"
    f"&hourly=temperature_2m,apparent_temperature,weathercode,wind_speed_10m,wind_direction_10m,precipitation_probability,uv_index,sea_surface_temperature"
    f"&daily=temperature_2m_max,temperature_2m_min,weathercode,uv_index_max,sunrise,sunset,precipitation_probability_max,wind_speed_10m_max"
    f"&timezone=auto&forecast_days=7"
)

MARINE_URL = (
    f"https://marine-api.open-meteo.com/v1/marine?"
    f"latitude={LATITUDE}&longitude={LONGITUDE}"
    f"&hourly=wave_height,wave_period"
    f"&timezone=auto&forecast_days=2"
)

WATER_URL = (
    f"https://api.open-meteo.com/v1/forecast?"
    f"latitude={WATER_LATITUDE}&longitude={WATER_LONGITUDE}"
    f"&hourly=sea_surface_temperature"
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
    0: "Despejado ☀️", 1: "Poco nuboso 🌤", 2: "Nublado ⛅",
    3: "Cubierto ☁️", 45: "Niebla 🌫", 48: "Niebla con escarcha 🌫",
    51: "Llovizna débil 🌦", 53: "Llovizna moderada 🌧", 55: "Llovizna intensa 🌧",
    56: "Llovizna helada 🌧", 57: "Llovizna helada intensa 🌧",
    61: "Lluvia débil 🌧", 63: "Lluvia moderada 🌧", 65: "Lluvia intensa 🌧",
    66: "Lluvia helada 🌧", 67: "Lluvia helada intensa 🌧",
    71: "Nieve débil ❄️", 73: "Nieve moderada ❄️", 75: "Nieve intensa ❄️",
    77: "Aguanieve ❄️",
    80: "Chubascos 🌧", 81: "Chubascos moderados 🌧", 82: "Chubascos fuertes 🌧",
    85: "Chubascos de nieve ❄️", 86: "Chubascos de nieve fuertes ❄️",
    95: "Tormenta ⛈", 96: "Tormenta con granizo ⛈", 99: "Tormenta fuerte con granizo ⛈"
}

DAYS_ES = {
    0: "Lun", 1: "Mar", 2: "Mié", 3: "Jue", 4: "Vie", 5: "Sáb", 6: "Dom"
}

WIND_DIRECTIONS = [
    (0, 22.5, "N"), (22.5, 67.5, "NE"), (67.5, 112.5, "E"),
    (112.5, 157.5, "SE"), (157.5, 202.5, "S"), (202.5, 247.5, "SO"),
    (247.5, 292.5, "O"), (292.5, 337.5, "NO"), (337.5, 360.1, "N")
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
    return "N"


def wind_description(speed):
    """Людський опис вітру (км/г) — щоб не покладатися на ШІ."""
    if speed is None:
        return ""
    if speed < 5:
        return "calma"
    if speed < 10:
        return "brisa suave"
    if speed < 20:
        return "brisa perceptible"
    if speed < 30:
        return "viento notable"
    if speed < 40:
        return "viento fuerte"
    return "viento muy fuerte"


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
        if "fuertes" in waves_desc:
            score -= 25
            reasons.append("high_waves")
        elif "moderadas" in waves_desc:
            score -= 10

    if precip_prob is not None and precip_prob >= 70:
        score -= 15
        reasons.append("rain")

    score = max(0, min(100, score))

    if score >= 80:
        emoji = "🟢"
        label = "¡Ideal para la playa!"
    elif score >= 60:
        emoji = "🟡"
        label = "Bien, pero con precaución"
    elif score >= 40:
        emoji = "🟠"
        label = "No es ideal, mejor limitar el tiempo"
    else:
        emoji = "🔴"
        label = "Mejor no ir a la playa"

    return score, emoji, label, reasons


def alerts(uv, wind_speed, waves_desc, precip_prob, weather_code, alerts_list):
    if uv is not None and uv >= 8:
        alerts_list.append(f"⚠️ UV ALTO ({uv}) — ¡aplica protector solar SPF50+!")

    if wind_speed is not None and wind_speed >= 40:
        alerts_list.append(f"⚠️ VIENTO FUERTE ({wind_speed} km/h) — ¡peligroso para el baño!")

    if waves_desc and ("fuertes" in waves_desc):
        alerts_list.append("⚠️ OLAS ALTAS — ¡el baño es peligroso!")

    if weather_code is not None and weather_code >= 95:
        alerts_list.append("⛈ TORMENTA — ¡sal de la playa inmediatamente!")

    if precip_prob is not None and precip_prob >= 80:
        alerts_list.append(f"🌧 ALTA PROBABILIDAD DE LLUVIA ({precip_prob}%)")

    if weather_code is not None and weather_code in (45, 48):
        alerts_list.append("🌫 NIEBLA — ten cuidado en el agua")


# ==================== КОМЕНТАР ДО ПОГОДИ ====================


def _weather_comment_prompt(d):
    """Спільний промпт для Gemini та Groq (той самий механізм, що й у sunset-бота)."""
    c = d["current"]
    hourly = d.get("hourly", [])
    daily = d.get("daily", [])
    wave_now = d.get("wave_now")

    max_temp_h = max((h.get("temp", 0) for h in hourly), default=c.get("temp", 20))
    max_uv_h = max((h.get("uv", 0) for h in hourly), default=d.get("uv_now", 0) or 0)
    max_wind_h = max((h.get("wind", 0) for h in hourly), default=c.get("wind", 0))
    wind_now_desc = wind_description(c.get("wind"))
    sky_now = sky_label(c.get("code", 0))

    rain_hours = []
    for h in hourly[:12]:
        pp = h.get("precip_prob")
        if pp is not None and pp > 20:
            rain_hours.append(f"{h['hour']:02d}:00")

    tomorrow = daily[1] if len(daily) > 1 else {}

    prompt = (
        "Eres un amigo que vive en Punta Umbría (España), adora el mar y de verdad "
        "entiende del tiempo. Escribe un mensaje vivo y humano (2-4 frases) EN ESPAÑOL "
        "sobre lo que pasará hoy en la playa Playa de Punta Umbría: cómo estará el tiempo, "
        "cómo cambiará a lo largo del día y qué esperar mañana. Escribe con calidez y "
        "naturalidad, como a un amigo por chat, sin lenguaje burocrático ni listas secas, "
        "integrando los datos en la narración. Sobre el viento habla SOLO con la descripción "
        f"humana que te doy: «{wind_now_desc}» ({c.get('wind', '?')} km/h). "
        f"Datos: ahora {sky_now} {c['temp']}°C, agua {d.get('water_temp', '?')}°C, "
        f"olas {wave_now or '?'}m, hoy hasta {max_temp_h}°C, UV hasta {max_uv_h}, "
        f"viento hasta {max_wind_h} km/h"
        + (f", lluvia {', '.join(rain_hours[:2])}" if rain_hours else "")
        + (f", mañana {tomorrow.get('min', '?')}…{tomorrow.get('max', '?')}°C" if tomorrow else "")
    )
    return prompt


def _gemini_comment(prompt):
    """Google Gemini 2.5-flash (та сама модель і механізм, що й у sunset-бота)."""
    if not GEMINI_API_KEY:
        return ""
    try:
        r = requests.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-2.5-flash:generateContent"
            f"?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json; charset=utf-8"},
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.7, "maxOutputTokens": 4096, "stopSequences": []},
            },
            timeout=25,
        )
        r.raise_for_status()
        parts = r.json()["candidates"][0]["content"]["parts"]
        return parts[0]["text"].strip()
    except Exception as e:
        print(f"Gemini commentary error: {e}")
        return ""


def _groq_comment(prompt):
    """Groq як запасний варіант, якщо Gemini недоступний."""
    if not GROQ_API_KEY:
        return ""
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.7,
            },
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"Groq commentary error: {e}")
        return ""


def generate_commentary(d):
    prompt = _weather_comment_prompt(d)

    text = _gemini_comment(prompt)
    if text:
        return text

    text = _groq_comment(prompt)
    if text:
        return text

    return _fallback_commentary(d)


def _fallback_commentary(d):
    c = d["current"]
    temp = c.get("temp", 20)
    wind = c.get("wind", 0)
    wave_now = d.get("wave_now")
    code = c.get("code", 0)
    hourly = d.get("hourly", [])
    wave_hourly = d.get("wave_hourly", [])

    sky_desc = sky_label(code)
    max_temp_h = max((h.get("temp", 0) for h in hourly), default=temp)
    wave_desc = wave_description(wave_now) if wave_now else "desconocido"

    parts = [f"Ahora {sky_desc.lower()}, {temp}°C, viento {wind} km/h"]
    if wave_now is not None:
        parts.append(f"Olas {wave_desc} ({wave_now} m)")
    if max_temp_h > temp + 2:
        parts.append(f"Sube hasta {max_temp_h}°C")
    return ". ".join(parts) + "."


# ==================== КІНЕЦЬ ====================


def get_marine_data():
    try:
        r = requests.get(MARINE_URL, timeout=15)
        r.raise_for_status()
        j = r.json()
        hourly = j.get("hourly", {})
        times = hourly.get("time", [])
        heights = hourly.get("wave_height", [])
        periods = hourly.get("wave_period", [])

        now = spain_now
        # MARINE_URL використовує timezone=auto, а в основній погоді — теж local,
        # тож шукаємо за місцевим (іспанським) часом, а не за UTC.
        target_time = now.strftime("%Y-%m-%dT%H:00")

        # Поточна висота хвилі
        wave_now = None
        period_now = None
        for i, t in enumerate(times):
            if t == target_time:
                if i < len(heights) and heights[i] is not None:
                    wave_now = heights[i]
                if i < len(periods) and periods[i] is not None:
                    period_now = periods[i]
                break

        # Погодинні хвилі (24 години)
        start_index = None
        for i, t in enumerate(times):
            if t >= target_time:
                start_index = i
                break
        if start_index is None:
            start_index = 0

        wave_hourly = []
        for i in range(start_index, min(start_index + 24, len(times))):
            h = int(times[i].split("T")[1].split(":")[0])
            wh = heights[i] if i < len(heights) and heights[i] is not None else None
            wp = periods[i] if i < len(periods) and periods[i] is not None else None
            wave_hourly.append({"hour": h, "height": wh, "period": wp})

        return {
            "wave_now": wave_now,
            "period_now": period_now,
            "wave_hourly": wave_hourly
        }
    except Exception as e:
        print(f"Marine API error: {e}")
        return None


def wave_description(height):
    if height is None:
        return None
    if height < 0.5:
        return "suaves"
    elif height < 1.0:
        return "moderadas"
    elif height < 2.0:
        return "fuertes"
    else:
        return "muy fuertes"


def get_all_data():
    for attempt in range(2):
        try:
            r = requests.get(OPEN_METEO_URL, timeout=15)
            r.raise_for_status()
            j = r.json()

            # Окремий запит для температури води (координати біля берега)
            water_times = []
            water_sea_temps = []
            try:
                wr = requests.get(WATER_URL, timeout=15)
                wr.raise_for_status()
                wj = wr.json()
                water_times = wj.get("hourly", {}).get("time", [])
                water_sea_temps = wj.get("hourly", {}).get("sea_surface_temperature", [])
            except Exception as we:
                print(f"Water API error: {we}")

            cur = j["current"]
            hourly = j.get("hourly", {})
            daily = j.get("daily", {})

            humidity_now = cur.get("relative_humidity_2m")

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

            # Поточна температура води (з окремого запиту WATER_URL)
            water_now = None
            for i, t in enumerate(water_times):
                if t == target_time:
                    if i < len(water_sea_temps) and water_sea_temps[i] is not None:
                        water_now = water_sea_temps[i]
                    break
            if water_now is None and water_sea_temps:
                for i, t in enumerate(water_times):
                    if t.startswith(today_str) and i < len(water_sea_temps) and water_sea_temps[i] is not None:
                        water_now = water_sea_temps[i]
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
                dow = DAYS_ES[dt.weekday()]

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

                # Температура води за день (середня з погодинних, окремий запит)
                day_water_temps = []
                for j, t in enumerate(water_times):
                    if t.startswith(date) and j < len(water_sea_temps) and water_sea_temps[j] is not None:
                        day_water_temps.append(water_sea_temps[j])
                water_avg = round(sum(day_water_temps) / len(day_water_temps)) if day_water_temps else None

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
                    "sunset": sunset_str,
                    "water_temp": water_avg
                })

            waves = get_marine_data()

            return {
                "current": {
                    "temp": rnd(cur["temperature_2m"]),
                    "apparent": rnd(cur.get("apparent_temperature")),
                    "wind": rnd(cur["wind_speed_10m"]),
                    "wind_dir": wind_direction(cur.get("wind_direction_10m")),
                    "code": cur["weathercode"],
                    "humidity": rnd(humidity_now)
                },
                "water_temp": rnd(water_now),
                "uv_now": rnd(uv_now),
                "precip_now": precip_now,
                "wave_now": waves["wave_now"] if waves else None,
                "wave_period": waves["period_now"] if waves else None,
                "wave_hourly": waves["wave_hourly"] if waves else [],
                "hourly": hourly_list,
                "daily": daily_list,
                "time_of_day": time_of_day
            }
        except Exception as e:
            print(f"Fetch error {attempt+1}: {e}")
            if attempt < 1:
                time.sleep(10)
    return None


def sky_label(code):
    label = WEATHER_CODES.get(code, "Desconocido")
    return label.rsplit(" ", 1)[0]


def uv_label(val):
    if val is None:
        return ""
    if val <= 2:
        return f"{val} (bajo)"
    elif val <= 5:
        return f"{val} (moderado)"
    elif val <= 7:
        return f"{val} (alto)"
    elif val <= 10:
        return f"{val} (muy alto)"
    else:
        return f"{val} (extremo)"


def build_message(d):
    c = d["current"]
    tod = d["time_of_day"]
    wave_now = d.get("wave_now")
    wave_hourly = d.get("wave_hourly", [])
    uv_val = d.get("uv_now")
    precip_val = d.get("precip_now")
    water_val = d.get("water_temp")
    hourly = d.get("hourly", [])

    # === ЗАГОЛОВОК ===
    date_str = spain_now.strftime("%d.%m.%Y")
    msg = f"🌊 {BEACH_NAME} — {date_str}\n\n"

    # === ПОГОДА ЗАРАЗ ===
    msg += "🔵 El tiempo ahora:\n"
    msg += f"🌡 Temperatura: {c['temp']}°C (sensación de {c.get('apparent', c['temp'])}°C)\n"
    msg += f"☁️ Cielo: {sky_label(c['code'])}\n"
    msg += f"💨 Viento: {c['wind']} km/h — {wind_description(c['wind'])} ({c['wind_dir']})\n"
    if c.get('humidity') is not None:
        msg += f"💧 Humedad: {c['humidity']}%\n"
    if wave_now is not None:
        msg += f"🌊 Olas: {wave_now} m\n"
    if water_val is not None:
        msg += f"💧 Agua: {water_val}°C\n"
    if uv_val is not None:
        msg += f"☀️ Índice UV: {uv_label(uv_val)}\n"
    if precip_val is not None:
        rain_status = "sin lluvia" if precip_val < 20 else "posible lluvia" if precip_val < 50 else "lluvia probable"
        msg += f"🌧 Precipitación: {precip_val}% ({rain_status})\n"

    # === РЕЙТИНГ БЕЗПЕКИ ===
    wave_desc = wave_description(wave_now)
    safety_score, safety_emoji, safety_label, _ = beach_safety_score(
        uv_val, c['wind'], wave_desc, precip_val
    )
    msg += f"🟢 Valoración de la playa: {safety_score}/100 ({safety_label})\n\n"

    # === КОРОТКО ПРО ПОГОДУ ===
    commentary = generate_commentary(d)
    msg += f"💡 En resumen:\n{commentary}\n\n"

    # === ПОГОДИННИЙ ПРОГНОЗ ===
    msg += "📋 Pronóstico por horas:\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"

    # З'єднуємо погодинні дані з хвилями
    wave_by_hour = {w["hour"]: w for w in wave_hourly}

    for h in hourly:
        hc = WEATHER_CODES_SHORT.get(h["code"], "?")
        precip_h = h.get("precip_prob")
        if precip_h is not None and precip_h > 0:
            hc = "🌧" if precip_h < 70 else "⛈"
        wind_str = f"{h.get('wind', 0):>2}" if h.get('wind') is not None else " ?"

        wh = wave_by_hour.get(h["hour"], {}).get("height")
        wave_str = f"🌊{wh:.1f}" if wh is not None else "🌊 —"

        msg += f"{h['hour']:02d}:00 │ {h['temp']}° {hc} │ 💨{wind_str} │ {wave_str} │ UV {h.get('uv', '?')}\n"

    # === 7-ДЕННИЙ ПРОГНОЗ ===
    msg += "\n📅 Pronóstico de los próximos 7 días (desde hoy):\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    for day in d["daily"]:
        dc = WEATHER_CODES_SHORT.get(day["code"], "?")
        wind_str = f"{day['wind_max']:>2}" if day.get('wind_max') is not None else " ?"
        water_str = f"💧{day['water_temp']}°" if day.get('water_temp') is not None else ""
        msg += f"{day['day']} │ {day['min']}°/{day['max']}° │ {dc} │ 💨{wind_str} │ UV {day.get('uv_max', '?')} {water_str}\n"

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
