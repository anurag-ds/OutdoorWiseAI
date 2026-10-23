"""Rule-based place x time scoring. Thresholds are per activity and tightened per health profile.
All thresholds are documented heuristics (not medical advice)."""
from datetime import datetime, timedelta

from .geo import ang_diff

COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]


def compass(deg):
    return COMPASS[int((deg % 360) / 22.5 + 0.5) % 16]


def _a(label, tags, ideal, hard, wind, rain, aqi, uv, daylight, travel_ok, radius, likes=("green",)):
    return dict(label=label, tags=tags, temp_ideal=ideal, temp_hard=hard, wind_soft=wind[0], wind_hard=wind[1],
                rain_soft=rain[0], rain_hard=rain[1], aqi_soft=aqi[0], aqi_hard=aqi[1], uv_soft=uv,
                daylight=daylight, travel_ok=travel_ok, default_radius=radius, likes=likes)


PARK = [("leisure", "park")]
ACTIVITIES = {
    "running": _a("Running / jogging", PARK + [("leisure", "track"), ("leisure", "stadium")], (10, 24), (2, 34), (25, 45), (30, 70), (70, 150), 6, True, 15, 5, ("green", "water")),
    "cycling": _a("Cycling", PARK + [("leisure", "track")], (12, 26), (3, 36), (20, 40), (30, 60), (70, 150), 7, True, 20, 8),
    "golf": _a("Golf", [("leisure", "golf_course")], (14, 30), (4, 37), (25, 45), (25, 50), (100, 200), 7, True, 40, 40),
    "cricket": _a("Cricket", [("sport", "cricket")], (14, 30), (5, 37), (30, 50), (20, 40), (90, 170), 7, True, 25, 10),
    "football": _a("Football / five-a-side", [("sport", "soccer")], (10, 27), (3, 35), (30, 50), (30, 60), (80, 160), 7, True, 20, 10),
    "tennis": _a("Tennis", [("sport", "tennis")], (12, 29), (4, 36), (15, 30), (20, 40), (90, 170), 7, True, 20, 8),
    "hiking": _a("Hiking / nature trail", [("natural", "peak"), ("tourism", "viewpoint"), ("leisure", "nature_reserve")] + PARK, (10, 26), (0, 34), (30, 55), (25, 50), (100, 180), 7, True, 60, 40, ("green", "water")),
    "walking": _a("Walking", PARK + [("leisure", "nature_reserve"), ("leisure", "garden")], (8, 28), (0, 36), (30, 50), (35, 70), (80, 160), 7, True, 12, 5, ("green", "water")),
    "picnic": _a("Picnic / park outing", PARK + [("leisure", "garden"), ("tourism", "picnic_site")], (16, 28), (8, 35), (20, 35), (15, 40), (100, 180), 7, True, 30, 15, ("green", "water")),
    "event": _a("Outdoor event / gathering", PARK + [("leisure", "garden"), ("leisure", "stadium")], (16, 30), (8, 36), (25, 40), (10, 30), (100, 200), 8, False, 30, 15),
    "photography": _a("Outdoor photography", [("tourism", "viewpoint"), ("natural", "water"), ("tourism", "attraction")] + PARK, (8, 32), (0, 38), (30, 50), (30, 60), (100, 200), 9, True, 40, 20, ("water",)),
}

HEALTH = {
    "asthma": dict(label="asthma", ideal_lo=3, hard_hi=-3, aqi_mult=0.6),
    "senior": dict(label="seniors", ideal_lo=2, ideal_hi=-3, hard_lo=4, hard_hi=-4, aqi_mult=0.7, wind_mult=0.8),
    "child": dict(label="children", ideal_hi=-2, hard_hi=-3, aqi_mult=0.7, uv_mult=0.8),
    "pregnancy": dict(label="pregnancy", ideal_hi=-3, hard_hi=-4, aqi_mult=0.7),
    "heart": dict(label="a heart condition", ideal_hi=-3, hard_hi=-4, hard_lo=3, aqi_mult=0.7),
}


def limits(act_key, profiles):
    a = ACTIVITIES[act_key]
    lo, hi = a["temp_ideal"]
    hlo, hhi = a["temp_hard"]
    aqi_s, aqi_h, uv, ws, wh = a["aqi_soft"], a["aqi_hard"], a["uv_soft"], a["wind_soft"], a["wind_hard"]
    for p in profiles:
        m = HEALTH[p]
        lo += m.get("ideal_lo", 0); hi += m.get("ideal_hi", 0)
        hlo += m.get("hard_lo", 0); hhi += m.get("hard_hi", 0)
        aqi_s *= m.get("aqi_mult", 1); aqi_h *= m.get("aqi_mult", 1)
        uv *= m.get("uv_mult", 1); ws *= m.get("wind_mult", 1); wh *= m.get("wind_mult", 1)
    return dict(temp_ideal=(lo, hi), temp_hard=(hlo, hhi), aqi_soft=round(aqi_s), aqi_hard=round(aqi_h),
                uv_soft=uv, wind_soft=ws, wind_hard=wh, rain_soft=a["rain_soft"], rain_hard=a["rain_hard"],
                daylight=a["daylight"], travel_ok=a["travel_ok"], likes=a["likes"])


def traffic_factor(hour):
    """OSRM public server has no live traffic; apply a documented peak-hour heuristic."""
    return 1.6 if (7 <= hour <= 10 or 17 <= hour <= 20) else 1.0


def local_exposure(ctx, wind_from, wind_kmh):
    """AQI-equivalent points added when the venue is downwind of a road/industrial source."""
    total, notes = 0.0, []
    for s in ctx.get("sources", []):
        max_d = 1000 if s["kind"] == "road" else 2500
        d = s["dist_m"]
        if d >= max_d:
            continue
        close, base = 1 - d / max_d, (20 if s["kind"] == "road" else 26)
        if wind_kmh < 4:
            if d < max_d * 0.4:
                total += base * close * 0.5
                notes.append(f"calm air near {s['name']} ({d} m)")
            continue
        diff = ang_diff(wind_from, s["bearing"])
        if diff <= 50:
            total += base * close * (0.5 + 0.5 * (1 - diff / 50))
            notes.append(f"downwind of {s['name']} ({d} m, wind from {compass(wind_from)})")
    return min(total, 35.0), notes


def _num(row, key, default=None):
    v = row.get(key)
    return default if v is None else v


def label_for(score, avoid):
    if avoid or score < 40:
        return "Avoid"
    return "Great" if score >= 75 else "Good" if score >= 55 else "Fair"


def score_slot(act_key, lim, row, dt, sun, ctx, travel_min, profiles, profile_txt):
    pen, bonus, bad, notes = 0.0, 0.0, [], []
    who = f"for {profile_txt}" if profiles else "for this activity"

    t = _num(row, "apparent_temperature", _num(row, "temperature_2m", 25))
    lo, hi = lim["temp_ideal"]; hlo, hhi = lim["temp_hard"]
    if t > hi:
        pen += min(35, (t - hi) * 3); notes.append(f"feels like {t:.0f}°C, above the {hi:.0f}°C comfort limit")
        if t > hhi:
            bad.append(f"feels like {t:.0f}°C, above the {hhi:.0f}°C safe limit {who}")
    elif t < lo:
        pen += min(25, (lo - t) * 2.5); notes.append(f"feels like {t:.0f}°C, below the {lo:.0f}°C comfort limit")
        if t < hlo:
            bad.append(f"feels like {t:.0f}°C, below the {hlo:.0f}°C safe limit {who}")

    aq = row.get("us_aqi")
    exposure, exp_notes, aqi_eff = 0.0, [], None
    if aq is not None:
        exposure, exp_notes = local_exposure(ctx, _num(row, "wind_direction_10m", 0), _num(row, "wind_speed_10m", 0))
        aqi_eff = aq + exposure
        s, h = lim["aqi_soft"], lim["aqi_hard"]
        if aqi_eff > s:
            pen += min(45, 45 * (aqi_eff - s) / max(1, h - s))
            notes.append(f"AQI {aq:.0f} (+{exposure:.0f} local exposure) above the {s} comfort limit")
        if aqi_eff > h:
            bad.append(f"air quality (AQI {aq:.0f}, +{exposure:.0f} local) is above the {h} limit {who}")

    p, mm = _num(row, "precipitation_probability", 0), _num(row, "precipitation", 0)
    if p > lim["rain_soft"]:
        pen += min(30, 30 * (p - lim["rain_soft"]) / max(1, 100 - lim["rain_soft"]))
        notes.append(f"{p:.0f}% rain chance")
    if p >= lim["rain_hard"] or mm >= 2:
        bad.append(f"rain likely ({p:.0f}% chance, {mm:.1f} mm)")

    w = _num(row, "wind_speed_10m", 0)
    if w > lim["wind_soft"]:
        pen += min(20, 20 * (w - lim["wind_soft"]) / max(1, lim["wind_hard"] - lim["wind_soft"]))
        notes.append(f"wind {w:.0f} km/h")
    if w > lim["wind_hard"]:
        bad.append(f"wind {w:.0f} km/h is too strong")

    is_day = row.get("is_day", 1)
    uv = _num(row, "uv_index", 0)
    if is_day and uv > lim["uv_soft"]:
        pen += min(15, (uv - lim["uv_soft"]) * 3); notes.append(f"UV index {uv:.0f}")

    dark_only = False
    if lim["daylight"] and not is_day:
        bad.append("no daylight"); dark_only = len(bad) == 1

    if act_key == "photography":
        if sun:
            ss, sr = datetime.fromisoformat(sun["sunset"]), datetime.fromisoformat(sun["sunrise"])
            if ss - timedelta(minutes=90) <= dt <= ss or sr - timedelta(minutes=15) <= dt <= sr + timedelta(minutes=75):
                bonus += 12; notes.append("golden-hour light")
        if _num(row, "cloud_cover", 0) > 85:
            pen += 8; notes.append("heavy cloud cover")

    if travel_min > lim["travel_ok"]:
        pen += min(25, 0.5 * (travel_min - lim["travel_ok"]))
    if ctx.get("green_count", 0) >= 3 and "green" in lim["likes"]:
        bonus += 5
    if ctx.get("water_m") is not None and ctx["water_m"] <= 500 and "water" in lim["likes"]:
        bonus += 3

    score = max(0.0, min(100.0, 100 - pen + bonus))
    if bad:
        score = min(score, 30.0)
    return {"dt": dt, "score": round(score), "label": label_for(score, bad), "avoid": bad, "dark_only": dark_only,
            "notes": notes, "aqi": aq, "aqi_eff": aqi_eff, "exposure": round(exposure), "exposure_notes": exp_notes,
            "travel_min": round(travel_min), "row": row}
