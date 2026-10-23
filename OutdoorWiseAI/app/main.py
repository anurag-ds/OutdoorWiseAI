import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from . import pipeline
from .config import ATTRIBUTION, DATA_SOURCES, LLM_BACKEND, MODEL_ID
from .scoring import ACTIVITIES

log = logging.getLogger("geoai")
STATE = {"llm": None, "llm_error": None}


@asynccontextmanager
async def lifespan(app):
    if LLM_BACKEND != "none":
        try:
            from .llm import LLM
            STATE["llm"] = await asyncio.to_thread(LLM)
            log.info("SLM loaded: %s", MODEL_ID)
        except Exception as e:  # keep serving with the template writer
            STATE["llm_error"] = str(e)
            log.exception("SLM failed to load")
    yield


app = FastAPI(title="OutdoorWise AI", version="0.1", lifespan=lifespan)


class Ask(BaseModel):
    question: str
    lat: float | None = None
    lon: float | None = None


@app.get("/")
def root():
    return {"name": "OutdoorWise AI", "usage": "POST /ask {\"question\": \"...\"} or GET /ask?q=...",
            "model": MODEL_ID, "activities": [a["label"] for a in ACTIVITIES.values()],
            "data_sources": DATA_SOURCES, "attribution": ATTRIBUTION}


@app.get("/health")
def health():
    return {"ok": True, "slm_loaded": STATE["llm"] is not None, "slm_error": STATE["llm_error"]}


@app.post("/ask")
async def ask(body: Ask):
    return await pipeline.run(body.question, body.lat, body.lon, STATE["llm"])


@app.get("/ask")
async def ask_get(q: str, lat: float | None = None, lon: float | None = None):
    return await pipeline.run(q, lat, lon, STATE["llm"])


# ---------- debug routes (raw live data, no scoring) ----------
from fastapi import HTTPException, Query  # noqa: E402

from . import geo, weather as _wx  # noqa: E402


@app.get("/debug/weather")
async def debug_weather(latitude: float = Query(..., ge=-90, le=90), longitude: float = Query(..., ge=-180, le=180)):
    try:
        return await _wx.fetch_weather(round(latitude, 3), round(longitude, 3), 2)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Weather provider failed: {e}")


@app.get("/debug/places")
async def debug_places(latitude: float = Query(..., ge=-90, le=90), longitude: float = Query(..., ge=-180, le=180),
                       activity: str = "running", radius_km: float = Query(5, ge=0.5, le=50)):
    if activity not in ACTIVITIES:
        raise HTTPException(status_code=400, detail=f"Unsupported activity. Use one of {list(ACTIVITIES)}")
    try:
        venues = await geo.find_venues(latitude, longitude, radius_km, ACTIVITIES[activity]["tags"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Places provider failed: {e}")
    return [{k: v for k, v in x.items() if k != "_d"} for x in venues[:25]]
