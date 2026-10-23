"""Query understanding. Rules first (fast, deterministic); the SLM is used to fill gaps
(activity / location / radius) that the rules could not resolve."""
import json
import re

from .scoring import ACTIVITIES, HEALTH

ACTIVITY_PATTERNS = [
    ("hiking", r"\b(hike|hiking|trek|trekking|trail|nature walk)\b"),
    ("cycling", r"\b(cycle|cycling|bicycle|biking|bike)\b"),
    ("running", r"\b(run|running|jog|jogging|marathon)\b"),
    ("golf", r"\bgolf\b"),
    ("cricket", r"\bcricket\b"),
    ("football", r"\b(football|five-a-side|5-a-side|soccer|futsal)\b"),
    ("tennis", r"\btennis\b"),
    ("photography", r"\b(photo|photos|photography|photoshoot|photo shoot)\b"),
    ("picnic", r"\b(picnic|park outing)\b"),
    ("event", r"\b(wedding|fair|event|gathering|birthday|party|function|reception)\b"),
    ("walking", r"\b(walk|walking|stroll)\b"),
]
PROFILE_PATTERNS = [
    ("asthma", r"\b(asthma|asthmatic|copd|wheez\w*|breathing (problem|issue)s?|respiratory)\b"),
    ("senior", r"\b(senior|seniors|elderly|old age|parents|grandparents?|grandfather|grandmother|grandma|grandpa)\b"),
    ("child", r"\b(kid|kids|child|children|toddler|baby|infant)\b"),
    ("pregnancy", r"\b(pregnan\w*|expecting)\b"),
    ("heart", r"\b(heart (condition|patient|disease|problem)|cardiac|hypertension)\b"),
]
INTENT_WORDS = r"\b(outdoor|outside|go|going|play|best time|where|when|weather|safe|okay|ok|good place|spot|plan|planning)\b"

_STOP_FIRST = (r"(?:the|a|an|my|your|our|this|that|next|every|any|some|work|home|office|today|tomorrow|tonight|"
               r"morning|evening|afternoon|night|weekend|weekday|day|days|week|time|it|saturday|sunday|monday|"
               r"tuesday|wednesday|thursday|friday|\d+)")
_STOP_CONT = (r"(?:tomorrow|today|tonight|this|on|at|for|next|within|after|before|during|please|early|late|morning|"
              r"evening|afternoon|night|weekend|saturday|sunday|monday|tuesday|wednesday|thursday|friday|with|and|"
              r"or|when|where|what|is|are|in|i|we|my|any|good|best|safe|ok|okay|suitable|that|which|so|to|if)")
_NAME = rf"(?!{_STOP_FIRST}\b)([a-z][a-z0-9'\-\.]*(?:\s+(?!{_STOP_CONT}\b)[a-z0-9'\-\.]+){{0,3}})"
_KM = r"(\d+(?:\.\d+)?)\s*(?:km|kms|kilomet\w+)"


def rule_parse(q: str) -> dict:
    ql = q.lower()
    activity = next((k for k, p in ACTIVITY_PATTERNS if re.search(p, ql)), None)
    profiles = [k for k, p in PROFILE_PATTERNS if re.search(p, ql)]
    m = re.search(r"\b(\d{1,2})[- ]?(?:year|yr)s?[- ]?old\b|\bage[d]?\s+(\d{1,2})\b", ql)
    if m:
        age = int(m.group(1) or m.group(2))
        if age >= 60 and "senior" not in profiles:
            profiles.append("senior")
        if age <= 12 and "child" not in profiles:
            profiles.append("child")

    radius, location = None, None
    m = re.search(rf"within\s+{_KM}\s+(?:of|from|around)\s+{_NAME}", ql, re.I)
    if m:
        radius, location = float(m.group(1)), m.group(2)
    else:
        m = re.search(_KM, ql)
        if m:
            radius = float(m.group(1))
    if not location:
        for pat in (rf"\b(?:near|around|close to|nearby)\s+{_NAME}", rf"\b(?:in|at|from|of)\s+{_NAME}"):
            m = re.search(pat, ql, re.I)
            if m:
                location = m.group(1)
                break
    if location:
        location = " ".join(w.capitalize() if w.islower() else w for w in location.strip(" .,'").split())
    return {"activity": activity, "location": location, "radius_km": radius, "profiles": profiles,
            "commute": bool(re.search(r"\b(to work|commute|office)\b", ql)), "parsed_by": "rules"}


def slm_parse(llm, q: str) -> dict | None:
    """Ask the SLM to extract fields as JSON; every field is validated against the question text."""
    msgs = [
        {"role": "system", "content": "You extract fields from a user's outdoor-activity question. Reply with ONE JSON object only."},
        {"role": "user", "content": (
            f'Question: "{q}"\nFields: "activity" (one of {list(ACTIVITIES)} or null), '
            '"location" (place name copied exactly from the question, or null), '
            '"radius_km" (number or null).\nJSON:')},
    ]
    try:
        raw = llm.generate(msgs, max_new_tokens=80)
        m = re.search(r"\{.*?\}", raw, re.S)
        js = json.loads(m.group(0)) if m else None
    except Exception:
        return None
    if not isinstance(js, dict):
        return None
    out = {}
    if js.get("activity") in ACTIVITIES:
        out["activity"] = js["activity"]
    loc = js.get("location")
    if isinstance(loc, str) and loc.strip() and loc.strip().lower() in q.lower():  # anti-hallucination
        out["location"] = loc.strip()
    try:
        if js.get("radius_km") is not None:
            out["radius_km"] = float(js["radius_km"])
    except (TypeError, ValueError):
        pass
    return out


def merge_parse(rule: dict, slm: dict | None) -> dict:
    out = dict(rule)
    if slm:
        for k in ("activity", "location", "radius_km"):
            if not out.get(k) and slm.get(k):
                out[k] = slm[k]
                out["parsed_by"] = "rules+slm"
    return out


def looks_outdoor_related(q: str) -> bool:
    return bool(re.search(INTENT_WORDS, q.lower()))


SUPPORTED_TEXT = ", ".join(a["label"] for a in ACTIVITIES.values())
