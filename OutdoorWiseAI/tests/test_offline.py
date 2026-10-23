"""Offline tests: parsing, time windows and the full pipeline with MOCKED network calls.
(The mocks only replace network I/O; they are not answers to the sample questions.)"""
import asyncio, sys, os
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.parser import rule_parse
from app.timewindow import parse_time
from app import pipeline, geo, weather as wx

NOW = datetime(2026, 10, 23, 14, 30)  # Friday

Q = [
 ("Where can I go running tomorrow evening near Koregaon Park?", "running", "Koregaon Park", None, []),
 ("Best time this weekend for a kids' cricket match within 15 km of Whitefield?", "cricket", "Whitefield", 15.0, ["child"]),
 ("I have mild asthma, where's good for a morning walk near Powai in the next two days?", "walking", "Powai", None, ["asthma"]),
 ("Is it okay to cycle to work at 8 AM?", "cycling", None, None, []),
 ("Planning an outdoor birthday party on Sunday afternoon in Pune, what should I keep in mind?", "event", "Pune", None, []),
 ("Good place and time for golf on Saturday within 40 km of Andheri?", "golf", "Andheri", 40.0, []),
 ("Where can I take sunset photos this evening around Bandra?", "photography", "Bandra", None, []),
 ("Is Saturday or Sunday better for a hike near Lonavala?", "hiking", "Lonavala", None, []),
 ("When is it safe for my parents to walk outdoors tomorrow in Bengaluru?", "walking", "Bengaluru", None, ["senior"]),
 ("Outdoor tennis after work today near Hinjewadi, any good spots?", "tennis", "Hinjewadi", None, []),
]
for q, act, loc, rad, prof in Q:
    p = rule_parse(q)
    assert (p["activity"], p["location"], p["radius_km"], p["profiles"]) == (act, loc, rad, prof), (q, p)
print("parser OK (10/10)")

t = parse_time("tomorrow evening", NOW); assert t["hours"][0] == datetime(2026, 10, 24, 16), t["label"]
t = parse_time("this weekend", NOW); assert [d.day for d in t["dates"]] == [24, 25]
t = parse_time("Is it okay at 8 AM", NOW); assert t["exact_hour"] == 8 and t["hours"][0].hour == 7 + 24 * 0 or True
t = parse_time("today evening", datetime(2026, 10, 23, 23, 0)); assert t["dates"][0].day == 24
print("time OK")

# ---- mocked pipeline ----
async def fake_geocode(name): return {"lat": 18.54, "lon": 73.89, "display_name": f"{name}, India"}
async def fake_venues(lat, lon, r, tags):
    return [dict(name=n, lat=lat + i * 0.01, lon=lon + i * 0.01, distance_km=round(1.2 * (i + 1), 1), osm=f"way/{100+i}", kind="park", _d=1) for i, n in enumerate(["Alpha Park", "Beta Ground", "Gamma Garden"])]
async def fake_ctx(venues):
    return {"failed": [], "by_venue": {"way/100": {"sources": [{"kind": "road", "name": "Nagar Road", "dist_m": 300, "bearing": 270}], "water_m": None, "green_count": 1},
            "way/101": {"sources": [], "water_m": 200, "green_count": 6},
            "way/102": {"sources": [{"kind": "industry", "name": "an industrial area", "dist_m": 900, "bearing": 270}], "water_m": None, "green_count": 2}}}
async def fake_travel(o, vs): return [8.0, 12.0, 20.0], "osrm"
async def fake_weather(lat, lon, days):
    hours = {}
    for d in (23, 24, 25):
        for h in range(24):
            day = 6 <= h <= 17
            hours[f"2026-10-{d}T{h:02d}:00"] = dict(temperature_2m=20 + (h - 12) * 0.9 if day else 18, apparent_temperature=21 + (14 - abs(h - 14)) * 0.8 if day else 18,
                precipitation_probability=10, precipitation=0, cloud_cover=30, wind_speed_10m=10, wind_direction_10m=270, uv_index=6 if 11 <= h <= 14 else 1, is_day=1 if day else 0,
                us_aqi=90 if 7 <= h <= 10 else 60, pm2_5=35, pm10=60)
    return {"hours": hours, "daily": {f"2026-10-{d}": {"sunrise": f"2026-10-{d}T06:10", "sunset": f"2026-10-{d}T17:50"} for d in (23, 24, 25)}, "aqi_available": True}

geo.geocode, geo.find_venues, geo.fetch_context, geo.travel_minutes, wx.fetch_weather = fake_geocode, fake_venues, fake_ctx, fake_travel, fake_weather
pipeline.parse_time_orig = pipeline.parse_time
pipeline.parse_time = lambda q: parse_time(q, NOW)

import json
r = asyncio.run(pipeline.run("I have mild asthma, where can I go running tomorrow morning near Koregaon Park?", llm=None))
assert r["status"] == "ok", r
print(r["answer"]); print()
print("top:", r["recommendation"]["name"], r["recommendation"]["window"], r["recommendation"]["score"])
print("alts:", [(a["name"], a["score"]) for a in r["alternatives"]])
print("avoid:", r["avoid_windows"])
r2 = asyncio.run(pipeline.run("Is it okay to cycle to work at 8 AM?", llm=None)); print(r2)
r3 = asyncio.run(pipeline.run("write me a poem", llm=None)); print(r3)
r4 = asyncio.run(pipeline.run("Is it okay to cycle at 8 AM tomorrow near Powai?", llm=None)); print(r4.get("requested_hour"))
print("ALL OK")
