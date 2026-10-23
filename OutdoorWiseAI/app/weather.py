"""Live hourly weather + air quality from Open-Meteo (no API key)."""
from .cache import ttl_cache
from .config import OPEN_METEO_AQ_URL, OPEN_METEO_URL, TIMEZONE
from .http import client

HOURLY = ("temperature_2m,apparent_temperature,relative_humidity_2m,precipitation_probability,"
          "precipitation,cloud_cover,wind_speed_10m,wind_direction_10m,uv_index,is_day")


@ttl_cache(900)
async def fetch_weather(lat: float, lon: float, days: int):
    days = max(1, min(days, 7))
    r = await client().get(OPEN_METEO_URL, params={
        "latitude": lat, "longitude": lon, "hourly": HOURLY, "daily": "sunrise,sunset",
        "timezone": TIMEZONE, "forecast_days": days})
    r.raise_for_status()
    w = r.json()
    H, D = w["hourly"], w["daily"]
    hours = {t: {k: H[k][i] for k in H if k != "time"} for i, t in enumerate(H["time"])}
    daily = {d: {"sunrise": D["sunrise"][i], "sunset": D["sunset"][i]} for i, d in enumerate(D["time"])}

    aqi_ok = False
    try:
        a = await client().get(OPEN_METEO_AQ_URL, params={
            "latitude": lat, "longitude": lon, "hourly": "us_aqi,pm2_5,pm10",
            "timezone": TIMEZONE, "forecast_days": min(days, 5)})
        a.raise_for_status()
        A = a.json()["hourly"]
        for i, t in enumerate(A["time"]):
            if t in hours:
                hours[t].update(us_aqi=A["us_aqi"][i], pm2_5=A["pm2_5"][i], pm10=A["pm10"][i])
                aqi_ok = aqi_ok or A["us_aqi"][i] is not None
    except Exception:
        pass
    return {"hours": hours, "daily": daily, "aqi_available": aqi_ok}
