---
title: OutdoorWise AI
emoji: 🌿
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# OutdoorWise AI

GeoAI Hackathon 2026 (CSRE, IIT Bombay) submission. Ask a free-form question and get **where** and **when** to do an
outdoor activity, backed by live weather, air quality and OpenStreetMap context.

**Live API:** `TODO: https://<your-space>.hf.space`  (try `GET /ask?q=Where can I run tomorrow evening near Koregaon Park?`)
**Model on Hugging Face:** `TODO: https://huggingface.co/<your-username>/outdoorwise-qwen2.5-1.5b`
**Code:** `TODO: https://github.com/<your-username>/OutdoorWiseAI`

## What it does
- Understands the activity, area, radius, time window and personal details (asthma, senior, child, pregnancy, heart condition).
- Compares several nearby venues across the upcoming hours (place x time), not a single spot.
- Uses geospatial context: wind direction vs nearby roads/industry (downwind exposure), water bodies, green cover, drive time.
- Returns a recommendation, alternatives, what to carry, what to watch for and when to avoid, with the live numbers it used.
- Asks for clarification on missing location/activity and declines off-topic questions.

Supported activities (11): running, cycling, golf, cricket, football/five-a-side, tennis, hiking, walking,
picnic/park outing, outdoor event/gathering, outdoor photography.

## Architecture
1. **Parse** the question (rules first, SLM fills gaps; SLM fields are validated against the question text).
2. **Fetch live** (per query, cached): Nominatim, Overpass, Open-Meteo forecast + air quality, OSRM.
3. **Score** each venue x hour with per-activity limits, tightened by health profile. Heuristics are documented in `app/scoring.py`.
4. **Write** the answer with the SLM from the fetched facts only. A grounding check rejects output that has unknown
   numbers or omits the venue name, and falls back to a template answer.

## Model
Base model: **Qwen/Qwen2.5-1.5B-Instruct** (1.5B parameters, Apache-2.0), used without fine-tuning.
Hosted copy and model card: see the Hugging Face link above. No hosted large model (GPT/Claude/Gemini) is used in the running assistant.

## Data sources (all free and open)
- OpenStreetMap via Overpass API: venues, roads, industry, water, green cover. **© OpenStreetMap contributors**
- Nominatim: geocoding
- Open-Meteo Forecast API and Air Quality API: hourly weather, UV, sunrise/sunset, US AQI, PM2.5, PM10
- OSRM public demo server: driving time

## Run locally
```bash
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                       # set CONTACT_EMAIL (Nominatim policy)
export CONTACT_EMAIL=you@example.com                       # Windows: set CONTACT_EMAIL=you@example.com
uvicorn app.main:app --port 7860
```
```bash
curl -X POST localhost:7860/ask -H "content-type: application/json" \
  -d '{"question":"I have mild asthma, where is good for a morning walk near Powai in the next two days?"}'
```
Environment: `LLM_BACKEND=transformers|llama_cpp|none` (none = template answers, no SLM), `MODEL_ID` (HF repo id).
Offline tests (mocked network): `python tests/test_offline.py`

## API
- `POST /ask` `{"question": "...", "lat": optional, "lon": optional}` or `GET /ask?q=...`
- `GET /health`, `GET /` (activities, sources)
- `GET /debug/weather`, `GET /debug/places` (raw live data)

## AI tools disclosure
Claude (Anthropic) was used as a coding assistant while building this project. No hosted LLM runs inside the assistant.

## Limitations (honest notes)
- Weather is gridded (~km scale), so it does not differ between nearby venues.
- OSRM demo has no live traffic; a documented peak-hour factor is applied to drive time.
- Downwind exposure is a geometric heuristic using OSM roads/industry, not a dispersion model.
- OSM venue coverage varies by area; unnamed venues are mostly skipped.
- Health limits are conservative heuristics, not medical advice.
