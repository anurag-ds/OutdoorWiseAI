"""Live geospatial data: Nominatim (geocode), Overpass (venues + context), OSRM (travel time)."""
import asyncio
import math

from .cache import ttl_cache
from .config import NOMINATIM_URL, OPEN_METEO_GEOCODE_URL, OSRM_URL, OVERPASS_URLS
from .http import client


# ---------- geometry helpers ----------
def haversine_m(a_lat, a_lon, b_lat, b_lon):
    R = 6371000.0
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dphi, dl = p2 - p1, math.radians(b_lon - a_lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def bearing_deg(a_lat, a_lon, b_lat, b_lon):
    """Compass bearing from point A to point B (0 = north, clockwise)."""
    p1, p2 = math.radians(a_lat), math.radians(b_lat)
    dl = math.radians(b_lon - a_lon)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def ang_diff(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


# ---------- Nominatim ----------
@ttl_cache(86400)
async def geocode(name: str):
    """Nominatim first; Open-Meteo geocoding as fallback. Returns None only if both answered 'not found';
    raises RuntimeError if both services were unreachable."""
    errors = []
    try:
        r = await client().get(NOMINATIM_URL, params={"q": name, "format": "jsonv2", "limit": 1, "countrycodes": "in"})
        r.raise_for_status()
        js = r.json()
        if js:
            return {"lat": float(js[0]["lat"]), "lon": float(js[0]["lon"]), "display_name": js[0]["display_name"],
                    "source": "Nominatim"}
    except Exception as e:
        errors.append(f"Nominatim: {e!r}")
    try:
        r = await client().get(OPEN_METEO_GEOCODE_URL, params={"name": name, "count": 1, "countryCode": "IN",
                                                                "language": "en", "format": "json"})
        r.raise_for_status()
        res = r.json().get("results")
        if res:
            x = res[0]
            disp = ", ".join(p for p in [x.get("name"), x.get("admin2"), x.get("admin1"), x.get("country")] if p)
            return {"lat": x["latitude"], "lon": x["longitude"], "display_name": disp, "source": "Open-Meteo Geocoding"}
    except Exception as e:
        errors.append(f"Open-Meteo geocoding: {e!r}")
    if len(errors) == 2:
        raise RuntimeError("; ".join(errors))
    return None


# ---------- Overpass ----------
@ttl_cache(6 * 3600)
async def _overpass(query: str):
    last = None
    for attempt in range(2):
        for url in OVERPASS_URLS:
            try:
                r = await client().post(url, data={"data": query})
                if r.status_code == 200:
                    return r.json()
                last = f"{url}: HTTP {r.status_code}"
            except Exception as e:  # network / timeout -> try next mirror
                last = f"{url}: {e!r}"
        await asyncio.sleep(2)
    raise RuntimeError(f"Overpass unavailable ({last})")


def _center(el):
    if el.get("type") == "node":
        return el.get("lat"), el.get("lon")
    c = el.get("center")
    return (c["lat"], c["lon"]) if c else (None, None)


async def find_venues(lat, lon, radius_km, tags):
    """Candidate venues for an activity, nearest first. tags = [(key, value), ...]."""
    r_m = int(radius_km * 1000)
    parts = "".join(f'nwr(around:{r_m},{lat},{lon})["{k}"="{v}"];' for k, v in tags)
    data = await _overpass(f"[out:json][timeout:30];({parts});out center tags 250;")
    named, unnamed = {}, []
    for el in data.get("elements", []):
        t = el.get("tags", {})
        vlat, vlon = _center(el)
        if vlat is None:
            continue
        d = haversine_m(lat, lon, vlat, vlon)
        kind = t.get("sport") or t.get("leisure") or t.get("tourism") or t.get("natural") or "place"
        v = {"name": t.get("name") or t.get("name:en"), "lat": vlat, "lon": vlon,
             "distance_km": round(d / 1000, 1), "osm": f'{el["type"]}/{el["id"]}', "kind": kind, "_d": d}
        if v["name"]:
            key = v["name"].strip().lower()
            if key not in named or d < named[key]["_d"]:
                named[key] = v
        else:
            v["name"] = f"Unnamed {kind} (OSM {v['osm']})"
            unnamed.append(v)
    out = sorted(named.values(), key=lambda v: v["_d"])
    if len(out) < 3:
        out += sorted(unnamed, key=lambda v: v["_d"])[: 3 - len(out)]
    return out


def _bbox(venues, pad_m=2500):
    lats, lons = [v["lat"] for v in venues], [v["lon"] for v in venues]
    mid = sum(lats) / len(lats)
    dlat = pad_m / 111000.0
    dlon = dlat / max(0.2, math.cos(math.radians(mid)))
    return min(lats) - dlat, min(lons) - dlon, max(lats) + dlat, max(lons) + dlon


CONTEXT_QUERIES = {
    "road": (['way["highway"~"^(motorway|trunk|primary)$"]'], "out geom 400;"),
    "industry": (['nwr["landuse"="industrial"]', 'nwr["power"="plant"]'], "out center 200;"),
    "water": (['nwr["natural"="water"]', 'way["waterway"~"^(river|canal)$"]'], "out center 300;"),
    "green": (['nwr["leisure"~"^(park|garden|nature_reserve)$"]',
               'nwr["landuse"~"^(forest|grass|meadow|village_green)$"]', 'nwr["natural"="wood"]'], "out center 500;"),
}


async def fetch_context(venues):
    """Roads, industry, water, green cover around the candidates: 4 small bbox queries, each failing independently.
    Returns {"by_venue": {osm: ctx}, "failed": [kinds that could not be fetched]}."""
    if not venues:
        return {"by_venue": {}, "failed": []}
    s, w, n, e = _bbox(venues)
    box = f"({s:.5f},{w:.5f},{n:.5f},{e:.5f})"
    elements, failed = [], []
    for kind, (filters, out) in CONTEXT_QUERIES.items():
        q = "[out:json][timeout:40];(" + "".join(f + box + ";" for f in filters) + ");" + out
        try:
            data = await _overpass(q)
            for el in data.get("elements", []):
                el["_kind"] = kind
                elements.append(el)
        except Exception:
            failed.append(kind)
    return {"by_venue": {v["osm"]: venue_context(v, elements, failed) for v in venues}, "failed": failed}


def venue_context(v, elements, failed=()):
    la, lo = v["lat"], v["lon"]
    sources, water_d, green = [], None, 0
    for el in elements:
        kind, t = el["_kind"], el.get("tags", {})
        if kind == "road":
            best = None
            for p in el.get("geometry", []):
                d = haversine_m(la, lo, p["lat"], p["lon"])
                if best is None or d < best[0]:
                    best = (d, p)
            if best and best[0] <= 1200:
                sources.append({"kind": "road", "name": t.get("name") or t.get("ref") or f"a {t.get('highway')} road",
                                "dist_m": int(best[0]), "bearing": bearing_deg(la, lo, best[1]["lat"], best[1]["lon"])})
            continue
        clat, clon = _center(el)
        if clat is None:
            continue
        d = haversine_m(la, lo, clat, clon)
        if kind == "industry" and d <= 2500:
            sources.append({"kind": "industry", "name": t.get("name") or "an industrial area",
                            "dist_m": int(d), "bearing": bearing_deg(la, lo, clat, clon)})
        elif kind == "water" and d <= 800:
            water_d = d if water_d is None else min(water_d, d)
        elif kind == "green" and d <= 600:
            green += 1
    sources.sort(key=lambda s: s["dist_m"])
    seen, uniq = set(), []
    for s in sources:
        k = (s["kind"], s["name"])
        if k not in seen:
            seen.add(k)
            uniq.append(s)
    return {"sources": uniq[:5], "water_m": int(water_d) if water_d is not None else None, "green_count": green,
            "unavailable": list(failed)}


# ---------- OSRM ----------
async def travel_minutes(origin, venues):
    """Free-flow driving minutes from origin (lat, lon) to each venue. Returns (list, method)."""
    def est(v):
        return haversine_m(origin[0], origin[1], v["lat"], v["lon"]) * 1.4 / 1000 / 25 * 60

    if not venues:
        return [], "none"
    cs = ";".join([f"{origin[1]:.5f},{origin[0]:.5f}"] + [f"{v['lon']:.5f},{v['lat']:.5f}" for v in venues])
    try:
        r = await client().get(f"{OSRM_URL}/table/v1/driving/{cs}", params={"sources": "0", "annotations": "duration"})
        r.raise_for_status()
        dur = r.json()["durations"][0][1:]
        return [d / 60 if d is not None else est(v) for d, v in zip(dur, venues)], "osrm"
    except Exception:
        return [est(v) for v in venues], "estimated (OSRM unreachable)"
