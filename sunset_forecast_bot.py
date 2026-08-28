import os
import sys
import time
import math
import datetime
import zoneinfo

import requests

# ==================== НАЛАШТУВАННЯ ====================
# Точка А — відкіля знімаєш захід сонця (набережна/порт в центрі Малаги).
LATITUDE = 36.7209
LONGITUDE = -4.4205

# Скільки км відкладати до Точки Б ("горизонт"/"прожектор")
POINT_B_DISTANCE_KM = float(os.environ.get("POINT_B_DISTANCE_KM", "80"))

# Скільки годин усереднювати навколо заходу для стабільності індексу
AVG_HOURS = int(os.environ.get("AVG_HOURS", "3"))

# Пороги "екрану" (Точка А): середня + висока хмарність
SCREEN_IDEAL_MIN = 30
SCREEN_IDEAL_MAX = 70

# Поріг "прожектора" (Точка Б): низька хмарність
SPOTLIGHT_IDEAL_MAX = 15
SPOTLIGHT_FAIL_AT = 60

# Нижче цього індексу — взагалі не постимо
MIN_INDEX_TO_NOTIFY = 30
# =====================================================

TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("SUNSET_CHANNEL_ID", "-1004312201455")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

MADRID_TZ = zoneinfo.ZoneInfo("Europe/Madrid")


# ==================== АЗИМУТ І ТОЧКА Б ====================

def sunset_azimuth(day_of_year: int) -> float:
    """Азимут заходу сонця для Малаги (°), синусоїда за днем року.
    271° на рівнодення, ~300° влітку, ~242° взимку."""
    return 271 + 29 * math.sin(2 * math.pi * (day_of_year - 81) / 365)


def destination_point(lat, lon, distance_km, bearing_deg):
    R = 6371.0
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    brng = math.radians(bearing_deg)
    d_r = distance_km / R
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d_r) + math.cos(lat1) * math.sin(d_r) * math.cos(brng)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brng) * math.sin(d_r) * math.cos(lat1),
        math.cos(d_r) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def azimuth_to_compass(deg: float) -> str:
    dirs = ["Пн", "ПнСх", "Сх", "ПдСх", "Пд", "ПдЗх", "Зх", "ПнЗх"]
    idx = round(deg / 45) % 8
    return dirs[idx]


# ==================== ЗАПИТИ ДО OPEN-METEO ====================
# timezone=UTC: Точка Б буває над морем, де auto може збити сітку годин.

def fetch_point_a(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=cloud_cover_low,cloud_cover_mid,cloud_cover_high"
        "&daily=sunset&timezone=UTC&forecast_days=2"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_point_b(lat, lon):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=cloud_cover_low"
        "&timezone=UTC&forecast_days=2"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    return r.json()


def hour_indices_near(hourly_times, target, n_hours):
    """Список індексів годин, найближчих за часом до target (по n годин)."""
    diffs = []
    for i, t_str in enumerate(hourly_times):
        t = datetime.datetime.fromisoformat(t_str)
        diff = abs((t - target).total_seconds())
        diffs.append((diff, i))
    diffs.sort()
    return [i for _, i in diffs[:n_hours]]


# ==================== ОЦІНКА (ІНДЕКС ЗАХОДУ СОНЦЯ) ====================

def screen_score(cloud_pct):
    if cloud_pct is None:
        return 0.0
    if cloud_pct < SCREEN_IDEAL_MIN:
        return max(0.0, (cloud_pct / SCREEN_IDEAL_MIN) * 100)
    if cloud_pct <= SCREEN_IDEAL_MAX:
        return 100.0
    span = 100 - SCREEN_IDEAL_MAX
    return max(0.0, 100 - (cloud_pct - SCREEN_IDEAL_MAX) * (100 / span))


def spotlight_score(cloud_low_pct):
    if cloud_low_pct is None:
        return 0.0
    if cloud_low_pct <= SPOTLIGHT_IDEAL_MAX:
        return 100.0
    if cloud_low_pct >= SPOTLIGHT_FAIL_AT:
        return 0.0
    span = SPOTLIGHT_FAIL_AT - SPOTLIGHT_IDEAL_MAX
    return max(0.0, 100 - (cloud_low_pct - SPOTLIGHT_IDEAL_MAX) * (100 / span))


def tier_for_index(index):
    if index >= 75:
        return "🔴", "Епічне небо на підході! Обов'язково піднімай дрон."
    if index >= 50:
        return "🟠", "Хороші умови для заходу сонця! Готуй камеру."
    if index >= MIN_INDEX_TO_NOTIFY:
        return "🟡", "Є непоганий шанс на цікаве небо. Варто перевірити ближче до вечора."
    return None, None


def groq_sunset_comment(f: dict) -> str:
    """Одне просте речення про погоду в Малазі під час заходу сонця."""
    if not GROQ_API_KEY:
        return ""
    prompt = (
        "Ти — короткий порадник фотографу заходу сонця в Малазі (Іспанія). "
        "Опиши ОДНИМ простим реченням (до 25 слів), яка буде погода під час "
        "заходу сонця і чого очікувати на небі. Дані: "
        f"хмарність середнього+високого рівня {round(f['screen_avg'])}%, "
        f"низька хмарність на горизонті {round(f['cloud_low'])}%, "
        f"індекс заходу {f['index']}% зі 100. Мова — українська, без канцеляриту."
    )
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "openai/gpt-oss-20b",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 1024,
                "temperature": 0.7,
            },
            timeout=20,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"GROQ error: {e}")
        return ""


# ==================== ОСНОВНА ЛОГІКА ====================

def get_forecast():
    day_of_year = datetime.datetime.now(MADRID_TZ).timetuple().tm_yday
    azimuth = sunset_azimuth(day_of_year)
    lat_b, lon_b = destination_point(LATITUDE, LONGITUDE, POINT_B_DISTANCE_KM, azimuth)

    data_a = fetch_point_a(LATITUDE, LONGITUDE)
    data_b = fetch_point_b(lat_b, lon_b)

    sunset_str = data_a["daily"]["sunset"][0]  # UTC
    sunset_utc = datetime.datetime.fromisoformat(sunset_str)

    hourly_a_times = data_a["hourly"]["time"]
    idxs_a = hour_indices_near(hourly_a_times, sunset_utc, AVG_HOURS)

    mids = [data_a["hourly"]["cloud_cover_mid"][i] for i in idxs_a]
    highs = [data_a["hourly"]["cloud_cover_high"][i] for i in idxs_a]
    cloud_mid = sum(mids) / len(mids)
    cloud_high = sum(highs) / len(highs)

    hourly_b_times = data_b["hourly"]["time"]
    idxs_b = hour_indices_near(hourly_b_times, sunset_utc, AVG_HOURS)
    lows = [data_b["hourly"]["cloud_cover_low"][i] for i in idxs_b]
    cloud_low = sum(lows) / len(lows)

    screen_avg = ((cloud_mid or 0) + (cloud_high or 0)) / 2
    s_screen = screen_score(screen_avg)
    s_spot = spotlight_score(cloud_low)
    index = round(s_screen * s_spot / 100)

    sunset_local = sunset_utc.replace(tzinfo=datetime.timezone.utc).astimezone(MADRID_TZ)

    return {
        "day_of_year": day_of_year,
        "azimuth": azimuth,
        "point_b": (lat_b, lon_b),
        "sunset_local": sunset_local,
        "cloud_mid": cloud_mid,
        "cloud_high": cloud_high,
        "cloud_low": cloud_low,
        "screen_avg": screen_avg,
        "score_screen": s_screen,
        "score_spotlight": s_spot,
        "index": index,
    }


def build_message(f: dict) -> str:
    emoji, text = tier_for_index(f["index"])
    compass = azimuth_to_compass(f["azimuth"])

    msg = f"{emoji} <b>Індекс заходу сонця: {f['index']}%</b>\n"
    msg += f"{text}\n\n"
    comment = groq_sunset_comment(f)
    if comment:
        msg += f"{comment}\n\n"
    msg += f"🕐 Захід сонця: {f['sunset_local'].strftime('%H:%M')} (за Мадридом)\n"
    msg += f"🧭 Напрямок: {compass} ({round(f['azimuth'])}°)\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += (
        f"🎨 Екран (сер./вис. хмарність): {round(f['screen_avg'])}% "
        f"→ {round(f['score_screen'])}/100\n"
    )
    msg += (
        f"🔦 Прожектор (низька хмарність): {round(f['cloud_low'])}% "
        f"→ {round(f['score_spotlight'])}/100\n"
    )
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🤖 @sunsetmalaga"
    return msg


def send_telegram(text: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for attempt in range(2):
        try:
            r = requests.post(
                url,
                json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            r.raise_for_status()
            print("Sent!")
            return True
        except Exception as e:
            print(f"Telegram error {attempt + 1}: {e}")
            if attempt < 1:
                time.sleep(5)
    return False


def main():
    now = datetime.datetime.now(MADRID_TZ)
    print(f"=== Sunset Forecast Bot === {now.strftime('%Y-%m-%d %H:%M')}")

    try:
        f = get_forecast()
    except Exception as e:
        print(f"FAIL: could not get forecast: {e}")
        sys.exit(1)

    print(
        f"Azimuth: {round(f['azimuth'], 1)}° | Point B: {f['point_b']} | "
        f"Sunset: {f['sunset_local'].strftime('%H:%M')}"
    )
    print(
        f"Screen avg (mid+high): {round(f['screen_avg'])}% "
        f"(mid={round(f['cloud_mid'])}%, high={round(f['cloud_high'])}%) | "
        f"Spotlight (low): {round(f['cloud_low'])}%"
    )
    print(f"Index: {f['index']}%")

    if f["index"] < MIN_INDEX_TO_NOTIFY:
        print(f"Index below {MIN_INDEX_TO_NOTIFY}% — не постимо (немає сенсу).")
        print("=== Done (no post) ===")
        return

    msg = build_message(f)
    if not send_telegram(msg):
        print("FAIL: send")
        sys.exit(1)

    print("=== Done ===")


if __name__ == "__main__":
    main()
