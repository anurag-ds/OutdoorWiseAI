"""End-to-end: question -> parse -> live data -> place x time scoring -> grounded answer."""
import asyncio
import json
import re
from datetime import datetime

from . import geo, weather as wx
from .advice import gear_and_watch
from .config import ATTRIBUTION, CANDIDATES, DATA_SOURCES, MAX_RADIUS_KM
from .parser import SUPPORTED_TEXT, looks_outdoor_related, merge_parse, rule_parse, slm_parse
from .timewindow import IST
from .scoring import ACTIVITIES, HEALTH, compass, limits, score_slot, traffic_factor
from .timewindow import parse_time


def _hk(dt):
    return dt.strftime("%Y-%m-%dT%H:00")


def _fmt(dt):
    return dt.strftime("%a %d %b %H:%M")


def _hhmm(iso):
    return iso[11:16] if iso else None


def _window(slots, best):
    """Contiguous hours around the best slot that stay within 8 points of it."""
    ok = lambda s: not s["avoid"] and s["score"] >= best["score"] - 8
    i = slots.index(best)
    a = b = i
    while a > 0 and ok(slots[a - 1]) and (best["dt"] - slots[a - 1]["dt"]).total_seconds() == 3600 * (i - a + 1):
        a -= 1
    while b < len(slots) - 1 and ok(slots[b + 1]) and (slots[b + 1]["dt"] - best["dt"]).total_seconds() == 3600 * (b + 1 - i):
        b += 1
    start, end = slots[a]["dt"], slots[b]["dt"].replace(minute=0)
    return {"date": start.strftime("%a %d %b"), "from": start.strftime("%H:%M"),
            "to": f"{(end.hour + 1) % 24:02d}:00"}


def _avoid_windows(slots):
    bad = [s for s in slots if (s["avoid"] and not s["dark_only"]) or s["score"] < 40]
    bad = [s for s in bad if not s["dark_only"]]
    groups, cur = [], []
    for s in bad:
        if cur and (s["dt"] - cur[-1]["dt"]).total_seconds() != 3600:
            groups.append(cur); cur = []
        cur.append(s)
    if cur:
        groups.append(cur)
    out = []
    for g in groups[:4]:
        reasons = []
        for s in g:
            for r in (s["avoid"] or s["notes"][:1]):
                if r not in reasons and r != "no daylight":
                    reasons.append(r)
        out.append({"date": g[0]["dt"].strftime("%a %d %b"), "from": g[0]["dt"].strftime("%H:%M"),
                    "to": f"{(g[-1]['dt'].hour + 1) % 24:02d}:00", "why": reasons[:2]})
    return out


def slot_facts(slot, sun):
    r = slot["row"]
    rnd = lambda k: None if r.get(k) is None else round(r[k])
    f = {"time": _fmt(slot["dt"]), "temp_c": rnd("temperature_2m"), "feels_like_c": rnd("apparent_temperature"),
         "rain_chance_pct": rnd("precipitation_probability"), "rain_mm": r.get("precipitation"),
         "wind_kmh": rnd("wind_speed_10m"), "wind_from": compass(r["wind_direction_10m"]) if r.get("wind_direction_10m") is not None else None,
         "uv_index": rnd("uv_index"), "cloud_cover_pct": rnd("cloud_cover"), "aqi": rnd("us_aqi"),
         "aqi_local_adjusted": None if slot["aqi_eff"] is None else round(slot["aqi_eff"]),
         "pm2_5": rnd("pm2_5")}
    if sun:
        f["sunrise"], f["sunset"] = _hhmm(sun["sunrise"]), _hhmm(sun["sunset"])
    return {k: v for k, v in f.items() if v is not None}


def _venue_context_text(ctx):
    out = []
    for s in ctx.get("sources", [])[:3]:
        out.append(f"{'major road' if s['kind'] == 'road' else 'industrial area'} '{s['name']}' about {s['dist_m']} m away")
    if ctx.get("water_m") is not None:
        out.append(f"water body about {ctx['water_m']} m away")
    if "green" not in ctx.get("unavailable", []):
        out.append(f"{ctx.get('green_count', 0)} mapped green areas within 600 m (including the venue itself)")
    return out


def template_answer(res):
    top, alts = res["recommendation"], res["alternatives"]
    L = [f"Best pick: {top['name']} ({top['distance_km']} km away, about {top['travel_min']} min by road). "
         f"Go on {top['window']['date']}, {top['window']['from']}-{top['window']['to']}.", "", "Why:"]
    f = top["conditions"]
    L.append(f"- Feels like {f.get('feels_like_c')}°C, rain chance {f.get('rain_chance_pct')}%, wind {f.get('wind_kmh')} km/h from {f.get('wind_from')}.")
    if f.get("aqi") is not None:
        L.append(f"- Air quality: AQI {f['aqi']} (local-adjusted {f.get('aqi_local_adjusted')}).")
    L += [f"- {c}" for c in top["surroundings"][:3]]
    if alts:
        L += ["", "Alternatives: " + "; ".join(f"{a['name']} ({a['window']['date']} {a['window']['from']}-{a['window']['to']}, score {a['score']})" for a in alts)]
    L += ["", "Carry: " + "; ".join(res["gear"])]
    if res["watch_out"]:
        L.append("Watch out: " + "; ".join(res["watch_out"]))
    if res["avoid_windows"]:
        L.append("Avoid: " + "; ".join(f"{w['date']} {w['from']}-{w['to']} ({'; '.join(w['why'])})" for w in res["avoid_windows"]))
    return "\n".join(L)


def grounded(text, facts_json, venue_name):
    if not text or len(text) < 60 or venue_name.lower() not in text.lower():
        return False
    allowed = set(re.findall(r"\d+(?:\.\d+)?", facts_json))
    for n in re.findall(r"\d+(?:\.\d+)?", text):
        if n in allowed or float(n) <= 12:
            continue
        return False
    return True


def write_answer(llm, question, res):
    facts = {"activity": res["understood"]["activity_label"], "health_profile": res["understood"]["profiles"],
             "when_asked": res["understood"]["time_window"], "assumptions": res["assumptions"][:3],
             "top_pick": {k: res["recommendation"][k] for k in ("name", "distance_km", "travel_min", "window", "score", "label", "conditions", "surroundings")},
             "alternatives": [{k: a[k] for k in ("name", "window", "score")} for a in res["alternatives"]],
             "avoid_windows": res["avoid_windows"], "carry": res["gear"], "watch_out": res["watch_out"]}
    if res.get("requested_hour"):
        facts["requested_hour"] = res["requested_hour"]
    facts_json = json.dumps(facts, ensure_ascii=False, default=str)
    if llm is None:
        return template_answer(res), "template (no SLM loaded)"
    msgs = [
        {"role": "system", "content": (
            "You are an outdoor-activity advisor. Write the final answer using ONLY the facts in the JSON. "
            "Never invent places, numbers, weather or times; if a detail is not in the facts, leave it out. "
            "Structure: Recommendation (place + time window), Why (2-4 short points with numbers from the facts), "
            "What to carry, Watch out for, When to avoid. Under 170 words. Plain text.")},
        {"role": "user", "content": f"Question: {question}\nFacts JSON:\n{facts_json}"},
    ]
    try:
        text = llm.generate(msgs, max_new_tokens=250)
    except Exception:
        text = ""
    if grounded(text, facts_json, res["recommendation"]["name"]):
        return text, f"SLM ({llm.model_id})"
    return template_answer(res), "template (SLM output failed the grounding check)"


async def _run(question: str, lat=None, lon=None, llm=None) -> dict:
    parsed = rule_parse(question)
    if llm and (not parsed["activity"] or (not parsed["location"] and lat is None)):
        slm = await asyncio.to_thread(slm_parse, llm, question)
        parsed = merge_parse(parsed, slm)

    act = parsed["activity"]
    if not act:
        if looks_outdoor_related(question):
            return {"status": "needs_clarification", "message": f"Which outdoor activity do you mean? I can help with: {SUPPORTED_TEXT}."}
        return {"status": "out_of_scope", "message": f"I only advise on where and when to do outdoor activities. I can help with: {SUPPORTED_TEXT}."}
    if lat is None and not parsed["location"]:
        return {"status": "needs_clarification",
                "message": f"Where are you (area or city)? I need a location to find {ACTIVITIES[act]['label'].lower()} spots."}

    assumptions = []
    if lat is not None and lon is not None:
        origin, origin_name = (lat, lon), "your location"
    else:
        try:
            g = await geo.geocode(parsed["location"])
        except Exception as e:
            return {"status": "error", "message": f"Location lookup services are unreachable right now ({e}). Please retry."}
        if not g:
            return {"status": "needs_clarification", "message": f"I couldn't find '{parsed['location']}' in India. Could you give a nearby area or city?"}
        origin, origin_name = (g["lat"], g["lon"]), g["display_name"]

    radius = parsed["radius_km"] or ACTIVITIES[act]["default_radius"]
    if not parsed["radius_km"]:
        assumptions.append(f"No search radius given, so I used {radius:g} km.")
    if radius > MAX_RADIUS_KM:
        radius = MAX_RADIUS_KM
        assumptions.append(f"Radius capped at {MAX_RADIUS_KM} km.")
    profiles = parsed["profiles"]
    if "senior" in profiles and re.search(r"\bparents\b", question.lower()):
        assumptions.append("I treated 'parents' as seniors, which uses stricter limits.")

    plan = parse_time(question)
    assumptions += plan["notes"]
    if not plan["hours"]:
        return {"status": "needs_clarification", "message": "I couldn't work out when you want to go. Try 'tomorrow evening' or 'Saturday morning'."}

    try:
        venues = await geo.find_venues(origin[0], origin[1], radius, ACTIVITIES[act]["tags"])
    except Exception as e:
        return {"status": "error", "message": f"Could not fetch map data right now ({e}). Please retry."}
    if not venues:
        return {"status": "no_results", "message": f"No mapped {ACTIVITIES[act]['label'].lower()} places within {radius:g} km of {origin_name}. Try a bigger radius."}
    cands = venues[:CANDIDATES]

    days = (max(plan["dates"]) - datetime.now(IST).date()).days + 1
    try:
        ctx_pack, (tmins, tmethod), wdata = await asyncio.gather(
            geo.fetch_context(cands), geo.travel_minutes(origin, cands), wx.fetch_weather(round(origin[0], 3), round(origin[1], 3), days))
    except Exception as e:
        return {"status": "error", "message": f"Could not fetch weather data right now ({e}). Please retry."}
    ctx_all = ctx_pack["by_venue"]
    if ctx_pack["failed"]:
        nm = {"road": "major roads", "industry": "industrial areas", "water": "water bodies", "green": "green cover"}
        assumptions.append("OpenStreetMap context could not be fetched right now for: "
                           + ", ".join(nm[k] for k in ctx_pack["failed"]) + ". Those factors were not scored.")
    if not wdata["aqi_available"]:
        assumptions.append("Air-quality forecast was unavailable, so AQI was not scored.")

    lim = limits(act, profiles)
    ptxt = " & ".join(HEALTH[p]["label"] for p in profiles)
    ranked = []
    for v, tmin in zip(cands, tmins):
        ctx, slots = ctx_all.get(v["osm"], {}), []
        for dt in plan["hours"]:
            row = wdata["hours"].get(_hk(dt))
            if row:
                slots.append(score_slot(act, lim, row, dt, wdata["daily"].get(dt.strftime("%Y-%m-%d")),
                                        ctx, tmin * traffic_factor(dt.hour), profiles, ptxt))
        if slots:
            best = max(slots, key=lambda s: (s["score"], -s["dt"].timestamp()))
            ranked.append({"v": v, "ctx": ctx, "slots": slots, "best": best, "tmin": tmin})
    if not ranked:
        return {"status": "error", "message": "No forecast data available for that time range."}
    ranked.sort(key=lambda r: (-r["best"]["score"], r["v"]["distance_km"]))

    def card(r):
        b, sun = r["best"], wdata["daily"].get(r["best"]["dt"].strftime("%Y-%m-%d"))
        return {"name": r["v"]["name"], "kind": r["v"]["kind"], "distance_km": r["v"]["distance_km"],
                "travel_min": round(r["tmin"]), "osm": f"https://www.openstreetmap.org/{r['v']['osm']}",
                "lat": r["v"]["lat"], "lon": r["v"]["lon"], "score": b["score"], "label": b["label"],
                "window": _window(r["slots"], b), "conditions": slot_facts(b, sun),
                "surroundings": _venue_context_text(r["ctx"]) + b["exposure_notes"][:2]}

    top = card(ranked[0])
    alts = [card(r) for r in ranked[1:3]]
    gear, watch = gear_and_watch(act, profiles, top["conditions"], lim["aqi_soft"], lim["wind_soft"])
    res = {
        "status": "ok",
        "understood": {"activity": act, "activity_label": ACTIVITIES[act]["label"], "location": origin_name,
                       "radius_km": radius, "profiles": profiles, "time_window": plan["label"],
                       "parsed_by": parsed["parsed_by"]},
        "assumptions": assumptions,
        "recommendation": top,
        "alternatives": [{k: a[k] for k in ("name", "distance_km", "travel_min", "score", "label", "window", "osm")} for a in alts],
        "avoid_windows": _avoid_windows(ranked[0]["slots"]),
        "gear": gear, "watch_out": watch,
        "evidence": {
            "weather_at_recommended_hour": top["conditions"],
            "venues_considered": [{"name": r["v"]["name"], "best_score": r["best"]["score"]} for r in ranked],
            "geospatial_context_failed": ctx_pack["failed"],
            "travel_time_method": tmethod + "; peak-hour factor is a heuristic",
            "limits_used": {"feels_like_comfort_c": lim["temp_ideal"], "aqi_comfort": lim["aqi_soft"], "aqi_hard": lim["aqi_hard"]},
            "fetched_at": datetime.now().isoformat(timespec="seconds"),
        },
        "data_sources": DATA_SOURCES, "attribution": ATTRIBUTION,
    }
    if plan["exact_hour"] is not None:
        slot = next((s for s in ranked[0]["slots"] if s["dt"].hour == plan["exact_hour"]), None)
        if slot:
            res["requested_hour"] = {"time": _fmt(slot["dt"]), "verdict": slot["label"], "score": slot["score"],
                                     "issues": slot["avoid"] or slot["notes"][:3]}
    text, source = await asyncio.to_thread(write_answer, llm, question, res)
    res["answer"], res["answer_source"] = text, source
    return res


async def run(question: str, lat=None, lon=None, llm=None) -> dict:
    """Never raise to the HTTP layer: always return a JSON-able dict."""
    try:
        return await _run(question, lat, lon, llm)
    except Exception as e:  # last-resort safety net
        return {"status": "error", "message": f"Unexpected error: {type(e).__name__}: {e}"}
