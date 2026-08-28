import os
import sys
import time
import json
import math
import datetime
import zoneinfo

import requests

# ==================== НАЛАШТУВАННЯ ====================
# Точка А — звідки знімаєш захід сонця (набережна/порт у центрі Малаги).
LATITUDE = 36.7209
LONGITUDE = -4.4205

# Відстані (км) вздовж променя в напрямку заходу для оцінки низької хмарності
# на горизонті: ближня точка (база низьких хмар неподалік) і дальня точка
# (власне західний горизонт, де сідає сонце).
HORIZON_NEAR_KM = 40.0
HORIZON_FAR_KM = 110.0

# Пороги "екрану" (Точка А): середня + висока хмарність як підсвічувана поверхня.
SCREEN_IDEAL_MIN = 30
SCREEN_IDEAL_MAX = 70

# Поріг "прожектора"/горизонту: низька хмарність у напрямку заходу.
SPOTLIGHT_IDEAL_MAX = 15
SPOTLIGHT_FAIL_AT = 60

# Нижче цього score — взагалі не постимо.
MIN_INDEX_TO_NOTIFY = 30

# Файл стану між щогодинними запусками (зберігається в гіті, щоб переживати
# перезапуски GitHub Actions): чи вже постили сьогодні і який був останній score.
STATE_FILE = ".sunset_state.json"
# Скільки годин до заходу — останній момент для оновлення/відміни.
LAST_UPDATE_HOURS_BEFORE = 1
# =====================================================

TELEGRAM_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("SUNSET_CHANNEL_ID", "-1004312201455")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

MADRID_TZ = zoneinfo.ZoneInfo("Europe/Madrid")

# ==================== АЗИМУТ І ТОЧКИ ГОРИЗОНТУ ====================

def sunset_azimuth(day_of_year: int) -> float:
    """Азимут заходу сонця для Малаги (°), синусоїда за днем року.
    271° на рівнодення, ~300° влітку, ~242° взимку."""
    return 271 + 29 * math.sin(2 * math.pi * (day_of_year - 81) / 365)


def destination_point(lat, lon, distance_km, bearing_deg):
    """Точка на відстані distance_km уздовж азимута bearing_deg."""
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

def build_forecast_url(lat, lon, hourly, extra=""):
    return (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        f"&hourly={hourly}{extra}"
        "&timezone=UTC&forecast_days=2"
    )


def safe_get(url, timeout=15):
    """HTTP GET з таймаутом; повертає dict або None на помилку."""
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"API error ({url[:80]}...): {e}")
        return None


def fetch_point_a(lat, lon):
    hourly = (
        "cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,"
        "visibility,relative_humidity_2m,precipitation,precipitation_probability,"
        "surface_pressure,wind_speed_10m,wind_direction_10m,temperature_2m"
    )
    return safe_get(build_forecast_url(lat, lon, hourly, "&daily=sunrise,sunset"))


def fetch_horizon_point(lat, lon):
    """Точка горизонту: потрібна лише низька хмарність."""
    hourly = "cloud_cover_low"
    return safe_get(build_forecast_url(lat, lon, hourly))


def fetch_aod(lat, lon):
    """CAMS air quality: aerosol optical depth + dust (необов'язково)."""
    url = (
        "https://air-quality-api.open-meteo.com/v1/air-quality"
        f"?latitude={lat}&longitude={lon}"
        "&hourly=aerosol_optical_depth,dust"
        "&timezone=UTC&forecast_days=2"
    )
    return safe_get(url)


def hour_indices(hourly_times, target):
    """Індекси годин у проміжку [target-4h, target+3h] навколо target."""
    out = []
    for i, t_str in enumerate(hourly_times):
        t = datetime.datetime.fromisoformat(t_str)
        d = (t - target).total_seconds() / 3600.0
        if -4.0 <= d <= 3.0:
            out.append(i)
    return out


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ==================== СКОР-ФУНКЦІЇ ====================

def screen_score(cloud_pct):
    """Наявність середньо/високої хмарності як 'екрана' для підсвітки.
    Ідеально 30-70%: мало — небо чисте й без кольору, багато — занадто сіро."""
    if cloud_pct is None:
        return 50.0
    if cloud_pct < SCREEN_IDEAL_MIN:
        # Без/мало хмар — чисте, але бліде небо без яскравих кольорів.
        return max(0.0, 35 + (cloud_pct / SCREEN_IDEAL_MIN) * 65)
    if cloud_pct <= SCREEN_IDEAL_MAX:
        return 100.0
    span = 100 - SCREEN_IDEAL_MAX
    return max(0.0, 100 - (cloud_pct - SCREEN_IDEAL_MAX) * (100 / span))


def horizon_score(cloud_low_pct):
    """Низька хмарність у напрямку заходу: висока низька хмарність
    перекриває сонце і вбиває захід. Низька — сонце видно."""
    if cloud_low_pct is None:
        return 50.0
    if cloud_low_pct <= SPOTLIGHT_IDEAL_MAX:
        return 100.0
    if cloud_low_pct >= SPOTLIGHT_FAIL_AT:
        return 0.0
    span = SPOTLIGHT_FAIL_AT - SPOTLIGHT_IDEAL_MAX
    return max(0.0, 100 - (cloud_low_pct - SPOTLIGHT_IDEAL_MAX) * (100 / span))


def visibility_score(vis_km):
    """Висока видимість → менше атмосферної мутності → яскравіші кольори.
    Лише дуже низька видимість (<5 км) суттєво погіршує картину."""
    if vis_km is None:
        return 60.0
    if vis_km >= 20:
        return 100.0
    if vis_km <= 5:
        return max(0.0, vis_km / 5 * 40)
    # 5..20 км лінійно
    return 40 + (vis_km - 5) / 15 * 60


def aod_score(aod):
    """Aerosol Optical Depth — оптична прозорість атмосфери.
    Дуже мала кількість аерозолів (чисте небо) — добре; легка димка (0.1-0.3)
    часто ПІДСИЛЮЄ насиченість кольорів, тому дає максимум; сильно запилений
    (>0.5, пил з Африки) — мутне, приглушене небо = погано."""
    if aod is None:
        return 60.0
    if 0.08 <= aod <= 0.30:
        return 100.0
    if aod < 0.08:
        # чисте небо — гарне світло, але без димки насиченості
        return 75 + aod / 0.08 * 25
    if aod <= 0.60:
        return 100 - (aod - 0.30) / 0.30 * 60
    return max(0.0, 100 - (aod - 0.60) / 0.40 * 70)


def precip_score(prob, mm):
    """Відсутність опадів у вікні заходу → краще. Низькі значення конвективних
    опадів (тут проксі = загальні опади + висока проба дощу) були пов'язані
    з яскравими 'flaming clouds'."""
    if prob is None:
        prob = 0
    if mm is None:
        mm = 0.0
    if mm > 0.5:
        return 0.0
    if prob >= 70:
        return 10.0
    if prob >= 50:
        return 35.0
    if prob >= 30:
        return 60.0
    if prob >= 15:
        return 85.0
    return 100.0


def humidity_score(rh):
    """Нижча відносна вологість → чистіше, суше повітря → насиченіші кольори."""
    if rh is None:
        return 60.0
    if rh <= 55:
        return 100.0
    if rh >= 95:
        return 20.0
    return 100 - (rh - 55) / 40 * 80


# ==================== ОПИС ЗОЛОТОЇ ГОДИНИ ====================

def gold_hour_desc(f):
    """Опис стану неба під час заходу, повністю за фактичними даними."""
    lines = []
    total = f["cloud_total"] or 0
    if total < 20:
        lines.append("🌤️ Ясно — мало хмар на небі")
    elif total < 60:
        lines.append("☁️ Частково хмарно")
    elif total < 85:
        lines.append("☁️☁️ Переважно хмарно")
    else:
        lines.append("🌫️ Суцільна хмарність")

    if f["cloud_low"] is None or f["cloud_low"] <= 20:
        lines.append("☀️ Сонце: видно")
    elif f["cloud_low"] <= 55:
        lines.append("🌤️ Сонце: періодично видно")
    else:
        lines.append("🌥️ Сонце: перекрите хмарами")

    high = f["cloud_high"]
    if high is not None and high >= 25:
        lines.append("☁️ Високі хмари: сприятливі для кольору")
    elif high is not None and high > 0:
        lines.append("☁️ Високі хмари: небагато")
    else:
        lines.append("☀️ Високі хмари: немає (небо чисте)")

    if f["horizon_open"] is True:
        lines.append("🔦 Горизонт: відкритий")
    elif f["horizon_open"] is False:
        lines.append("🚫 Горизонт: перекритий низькою хмарністю")
    else:
        lines.append("⚠️ Горизонт: дані недоступні")

    prob = f["rain_prob"]
    if prob is None or prob < 15:
        lines.append("🌧️ Дощ: малоймовірний")
    elif prob < 50:
        lines.append("🌦️ Дощ: можливий")
    else:
        lines.append("🌧️ Дощ: ймовірний")

    return lines


def human_conclusion(f):
    """Короткий людський висновок на основі даних."""
    idx = f["index"]
    if idx >= 80:
        return "📸 Відмінні умови для фотографування заходу — обов'язково варто вийти!"
    if idx >= 60:
        return "📸 Хороші умови — варто підготувати камеру й вийти на захід."
    if idx >= 40:
        return "🌅 Є непоганий шанс на цікаве небо, але не гарантія — перевір ближче до вечора."
    if (f["cloud_total"] or 0) < 25:
        return "🌤️ Небо буде чистим і прозорим, але без хмар кольори заходу будуть стриманими."
    return "☁️ Висока хмарність, імовірно, закриє захід — барвистого заходу чекати не варто."


def tier_label(idx):
    if idx >= 80:
        return "🔴"
    if idx >= 60:
        return "🟠"
    if idx >= 40:
        return "🟡"
    if idx >= 20:
        return "🟢"
    return "⚪"


# ==================== GROQ КОМЕНТАР ====================

def groq_sunset_comment(f: dict) -> str:
    """Одне просте речення про умови під час заходу (необов'язково)."""
    if not GROQ_API_KEY:
        return ""
    prompt = (
        "Ти — порадник фотографу заходу сонця в Малазі (Іспанія). "
        "Напиши ОДНЕ просте речення (до 25 слів), яке підсумовує, чого "
        "очікувати ввечері і чи варто йти фотографувати. Врахуй фактично: "
        f"загальна хмарність {round(f['cloud_total'])}%), "
        f"серед./вис. хмарність {round(f['screen_avg'])}%, "
        f"низька хмарність на горизонті {round(f['cloud_low'])}%, "
        f"видимість {round(f['visibility_km'])} км, "
        f"ймовірність дощу {f['rain_prob']}%, "
        f"шанс на красивий захід {f['index']}/100. "
        "Мова — українська, без канцеляриту."
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
                "max_tokens": 300,
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
    lat_near, lon_near = destination_point(LATITUDE, LONGITUDE, HORIZON_NEAR_KM, azimuth)
    lat_far, lon_far = destination_point(LATITUDE, LONGITUDE, HORIZON_FAR_KM, azimuth)

    data_a = fetch_point_a(LATITUDE, LONGITUDE)
    if not data_a or "hourly" not in data_a:
        raise RuntimeError("Point A (main forecast) недоступний")

    sunset_str = data_a["daily"]["sunset"][0]  # UTC
    sunset_utc = datetime.datetime.fromisoformat(sunset_str)

    ha = data_a["hourly"]
    times = ha["time"]
    idxs = hour_indices(times, sunset_utc)

    g = lambda key: [ha.get(key, [None] * len(times))[i] for i in idxs]

    cloud_total = mean(g("cloud_cover"))
    cloud_low = mean(g("cloud_cover_low"))
    cloud_mid = mean(g("cloud_cover_mid"))
    cloud_high = mean(g("cloud_cover_high"))
    mids = g("cloud_cover_mid")
    highs = g("cloud_cover_high")
    screen_pairs = [(m if m is not None else 0, h if h is not None else 0)
                    for m, h in zip(mids, highs)]
    screen_avg = mean([(m + h) / 2 for m, h in screen_pairs])

    visibility_m = g("visibility")
    visibility_km = None
    if any(v is not None for v in visibility_m):
        visibility_km = mean(visibility_m) / 1000.0

    rh = mean(g("relative_humidity_2m"))
    precip_prob = max(g("precipitation_probability") or [0])
    precip_mm = mean(g("precipitation"))
    temp_avg = mean(g("temperature_2m"))
    wind_avg = mean(g("wind_speed_10m"))
    wind_dir = mean(g("wind_direction_10m"))
    pressure = mean(g("surface_pressure"))
    tmax = data_a["daily"].get("temperature_2m_max", [None])[0]

    # Низька хмарність на горизонті (напрямок заходу) — середня з двох точок.
    low_near = low_far = None
    data_near = fetch_horizon_point(lat_near, lon_near)
    if data_near and "hourly" in data_near:
        low_near = mean([data_near["hourly"]["cloud_cover_low"][i]
                         for i in hour_indices(data_near["hourly"]["time"], sunset_utc)])
    data_far = fetch_horizon_point(lat_far, lon_far)
    if data_far and "hourly" in data_far:
        low_far = mean([data_far["hourly"]["cloud_cover_low"][i]
                        for i in hour_indices(data_far["hourly"]["time"], sunset_utc)])

    vals = [v for v in (low_near, low_far) if v is not None]
    cloud_low_horizon = mean(vals) if vals else None

    # Якщо на горизонті немає даних — використаємо локальну низьку хмарність.
    horizon_low_used = cloud_low_horizon if cloud_low_horizon is not None else cloud_low

    # AOD / dust (необов'язково — падіння не допускаємо).
    aod = dust = None
    aq = fetch_aod(LATITUDE, LONGITUDE)
    if aq and "hourly" in aq:
        hq = aq["hourly"]
        aq_idx = hour_indices(hq["time"], sunset_utc)
        if hq.get("aerosol_optical_depth"):
            aod = mean([hq["aerosol_optical_depth"][i] for i in aq_idx])
        if hq.get("dust"):
            dust = mean([hq["dust"][i] for i in aq_idx])

    # Тенденція: зміна сумарної хмарності за останні 3 години ДО заходу.
    trend = 0.0
    trend_vals = sorted((t, ha["cloud_cover"][i]) for i, t in enumerate(times)
                        if -4.0 <= ((datetime.datetime.fromisoformat(t) - sunset_utc).total_seconds() / 3600.0) <= -0.9
                        and ha["cloud_cover"][i] is not None)
    if len(trend_vals) >= 2:
        trend = trend_vals[-1][1] - trend_vals[0][1]

    # ===== SCORE =====
    # Головний компонент — хмарна структура: гарний захід потребує хмар
    # (як підсвічуваного "екрана") І відкритого західного горизонту одночасно.
    # Це мультиплікативний фактор: без хмар захід не буде барвистим, якими б
    # хорошими не були вторинні умови (видимість, чистота повітря тощо).
    s_screen = screen_score(screen_avg)
    s_horizon = horizon_score(horizon_low_used)
    cloud_knowledge = (s_screen / 100.0) * (s_horizon / 100.0)

    s_vis = visibility_score(visibility_km)
    s_aod = aod_score(aod)
    s_precip = precip_score(precip_prob, precip_mm)
    s_hum = humidity_score(rh)
    secondary = s_vis * 0.40 + s_aod * 0.25 + s_precip * 0.20 + s_hum * 0.15

    index = round(cloud_knowledge * secondary)
    index = max(0, min(100, index))

    sunset_local = sunset_utc.replace(tzinfo=datetime.timezone.utc).astimezone(MADRID_TZ)

    return {
        "day_of_year": day_of_year,
        "azimuth": azimuth,
        "horizon_points": [(lat_near, lon_near), (lat_far, lon_far)],
        "sunset_local": sunset_local,
        "cloud_total": cloud_total,
        "cloud_low": cloud_low,
        "cloud_mid": cloud_mid,
        "cloud_high": cloud_high,
        "screen_avg": screen_avg,
        "cloud_low_horizon": cloud_low_horizon,
        "horizon_open": (cloud_low_horizon is not None and cloud_low_horizon <= 25),
        "visibility_km": visibility_km,
        "humidity": rh,
        "rain_prob": precip_prob,
        "precip_mm": precip_mm,
        "pressure": pressure,
        "temp_avg": temp_avg,
        "temp_max": tmax,
        "wind_avg": wind_avg,
        "wind_dir": wind_dir,
        "aod": aod,
        "dust": dust,
        "trend": trend,
        "s_screen": s_screen,
        "s_horizon": s_horizon,
        "s_vis": s_vis,
        "s_aod": s_aod,
        "s_precip": s_precip,
        "s_hum": s_hum,
        "index": index,
    }


def golden_hour_block(f: dict) -> str:
    compass = azimuth_to_compass(f["azimuth"])
    label = tier_label(f["index"])
    gold = gold_hour_desc(f)

    msg = f"🌅 <b>ЗАХІД СОНЦЯ — МАЛАГА</b>\n\n"
    msg += f"<b>Шанс на красивий захід: {f['index']}% {label}</b>\n"
    msg += f"🕐 Захід: {f['sunset_local'].strftime('%H:%M')}\n"
    msg += f"🧭 Напрямок: {compass} ({round(f['azimuth'])}°)\n\n"

    msg += f"🌇 <b>Золота година</b>\n"
    for line in gold:
        msg += line + "\n"
    msg += "\n"

    msg += f"🌤️ <b>Погода сьогодні</b>\n"
    if f["temp_max"] is not None:
        msg += f"🌡️ Макс: {round(f['temp_max'])}°C"
        if f["temp_avg"] is not None:
            msg += f" (ввечері {round(f['temp_avg'])}°C)"
        msg += "\n"
    elif f["temp_avg"] is not None:
        msg += f"🌡️ {round(f['temp_avg'])}°C\n"
    if f["wind_avg"] is not None:
        msg += f"💨 Вітер: {round(f['wind_avg'])} км/год\n"
    if f["visibility_km"] is not None:
        msg += f"👁️ Видимість: {round(f['visibility_km'])} км\n"
    if f["rain_prob"] is not None:
        msg += f"🌧️ Дощ: {f['rain_prob']}%\n"
    if f["pressure"] is not None:
        msg += f"🗜️ Тиск: {round(f['pressure'])} гПа\n"

    comment = groq_sunset_comment(f)
    if comment:
        msg += "\n" + comment + "\n"

    msg += f"\n<b>{human_conclusion(f)}</b>\n"
    msg += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    msg += "🤖 @sunsetmalaga"
    return msg


def build_message(f: dict, mode="first", prev_index=None) -> str:
    """Генерує текстове повідомлення.
    mode: 'first' — перший пост дня; 'update' — оновлення щогодини;
    'cancel' — відміна/хибна тривога (score впав нижче порогу)."""
    body = golden_hour_block(f)

    if mode == "first":
        return body

    # Оновлення / відміна: короткий заголовок зі зміною + повне тіло.
    if mode == "cancel":
        head = "🔄 <b>ОНОВЛЕННЯ ЗАХОДУ — МАЛАГА</b>\n\n"
        if prev_index is not None and prev_index >= MIN_INDEX_TO_NOTIFY:
            head += f"⬇️ Шанс знизився: {prev_index}% → <b>{f['index']}%</b>\n"
        else:
            head += f"<b>Шанс: {f['index']}%</b>\n"
        head += "⚠️ Схоже, барвистого заходу не буде — це могла бути хибна тривога.\n\n"
        return head + body

    # mode == 'update'
    head = "🔄 <b>ОНОВЛЕННЯ ЗАХОДУ — МАЛАГА</b>\n\n"
    if prev_index is not None:
        arrow = "📈" if f["index"] > prev_index else ("📉" if f["index"] < prev_index else "➖")
        head += f"{arrow} Шанс: {prev_index}% → <b>{f['index']}%</b>\n\n"
    else:
        head += f"<b>Шанс: {f['index']}%</b>\n\n"
    return head + body


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


def read_state():
    """Читає стан із диск-файлу. Якщо файлу немає/пошкоджено — порожній стан."""
    default = {"date": None, "posted": False, "last_index": None}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return {**default, **data}
    except Exception as e:
        print(f"State read: no/invalid state ({e})")
        return default


def write_state(state):
    """Записує стан у диск-файл."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        print("State saved.")
    except Exception as e:
        print(f"State write error: {e}")


def is_too_late(now_local, sunset_local):
    """Чи вже пізно оновлювати прогноз (за годину до заходу або після)."""
    diff_hours = (sunset_local - now_local).total_seconds() / 3600.0
    return diff_hours < LAST_UPDATE_HOURS_BEFORE


def main():
    now = datetime.datetime.now(MADRID_TZ)
    today = now.strftime("%Y-%m-%d")
    print(f"=== Sunset Forecast Bot === {now.strftime('%Y-%m-%d %H:%M')}")

    try:
        f = get_forecast()
    except Exception as e:
        print(f"FAIL: could not get forecast: {e}")
        sys.exit(1)

    print(
        f"Azimuth: {round(f['azimuth'], 1)}° | Points: {f['horizon_points']} | "
        f"Sunset: {f['sunset_local'].strftime('%H:%M')}"
    )
    print(
        f"Clouds: tot={round(f['cloud_total'])}% low={round(f['cloud_low'])}% "
        f"mid={round(f['cloud_mid'])}% high={round(f['cloud_high'])}% | "
        f"screen={round(f['screen_avg'])}% | horizon low={round(f['cloud_low_horizon'])}%"
    )
    print(
        f"vis={f['visibility_km']} km | AOD={f['aod']} | dust={f['dust']} | "
        f"rain={f['rain_prob']}% | hum={f['humidity']}% | trend={round(f['trend'])}%"
    )
    print(
        f"Scores: screen={round(f['s_screen'])} horizon={round(f['s_horizon'])} "
        f"vis={round(f['s_vis'])} aod={round(f['s_aod'])} "
        f"precip={round(f['s_precip'])} hum={round(f['s_hum'])}"
    )
    print(f"Index: {f['index']}%")

    # Надто пізно — прогноз на сьогодні вже завершено.
    if is_too_late(now, f["sunset_local"]):
        print("Too late (за <1 год до заходу або після) — не постимо.")
        print("=== Done (too late) ===")
        return

    # Стан між щогодинними запусками.
    state = read_state()
    if state.get("date") != today:
        state = {"date": today, "posted": False, "last_index": None}

    index = f["index"]

    if not state.get("posted"):
        # Перший пост дня: щогодини перевіряємо, поки score не перевищить поріг.
        if index < MIN_INDEX_TO_NOTIFY:
            print(f"First post: index {index} < {MIN_INDEX_TO_NOTIFY} — чекаємо далі.")
            print("=== Done (waiting) ===")
            return
        msg = build_message(f, mode="first")
        if not send_telegram(msg):
            print("FAIL: send first")
            sys.exit(1)
        state["posted"] = True
        state["last_index"] = index
        print("=== First post sent ===")
    else:
        # Вже постили сьогодні — щогодини приходить оновлення або відміна.
        prev = state.get("last_index")
        mode = "cancel" if index < MIN_INDEX_TO_NOTIFY else "update"
        msg = build_message(f, mode=mode, prev_index=prev)
        if not send_telegram(msg):
            print("FAIL: send update")
            sys.exit(1)
        state["last_index"] = index
        print("=== Update sent ===")

    write_state(state)
    print(msg)


if __name__ == "__main__":
    main()
