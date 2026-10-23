import os

CONTACT = os.getenv("CONTACT_EMAIL", "").strip()  # Nominatim policy: identify yourself (set CONTACT_EMAIL)
USER_AGENT = "OutdoorWiseAI/0.1 (GeoAI Hackathon 2026 project" + (f"; {CONTACT}" if CONTACT else "") + ")"
OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OSRM_URL = "https://router.project-osrm.org"
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_AQ_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
TIMEZONE = "Asia/Kolkata"

# SLM settings (<= 3B params, open weights)
LLM_BACKEND = os.getenv("LLM_BACKEND", "transformers")  # transformers | llama_cpp | none
MODEL_ID = os.getenv("MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
GGUF_REPO = os.getenv("GGUF_REPO", "Qwen/Qwen2.5-1.5B-Instruct-GGUF")
GGUF_FILE = os.getenv("GGUF_FILE", "*q4_k_m.gguf")

MAX_RADIUS_KM = 50
CANDIDATES = 8  # venues analysed in depth per query

DATA_SOURCES = [
    {"name": "OpenStreetMap via Overpass API", "url": "https://overpass-api.de", "used_for": "venues, roads, industry, water, green cover"},
    {"name": "Nominatim", "url": "https://nominatim.openstreetmap.org", "used_for": "geocoding place names"},
    {"name": "Open-Meteo Geocoding API", "url": "https://open-meteo.com/en/docs/geocoding-api", "used_for": "fallback geocoding if Nominatim blocks or fails"},
    {"name": "Open-Meteo Forecast API", "url": "https://open-meteo.com", "used_for": "hourly weather, UV, sunrise/sunset"},
    {"name": "Open-Meteo Air Quality API", "url": "https://open-meteo.com/en/docs/air-quality-api", "used_for": "hourly US AQI, PM2.5, PM10"},
    {"name": "OSRM public demo server", "url": "https://router.project-osrm.org", "used_for": "driving time to each venue"},
]
ATTRIBUTION = "© OpenStreetMap contributors"
