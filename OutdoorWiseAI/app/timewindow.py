"""Turn vague time phrases ("tomorrow evening", "this weekend", "8 AM") into concrete local hours."""
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
PARTS = {
    "early morning": (5, 8), "morning": (5, 11), "afternoon": (12, 17), "evening": (16, 20),
    "after work": (17, 21), "sunset": (16, 19), "sunrise": (5, 8), "tonight": (19, 23),
    "night": (19, 23), "noon": (11, 14), "lunch": (12, 14),
}


def _exact_hour(ql):
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)", ql)
    if m:
        h = int(m.group(1)) % 12
        if m.group(3).startswith("p"):
            h += 12
        return h
    m = re.search(r"\bat\s+(\d{1,2}):(\d{2})\b", ql)
    return int(m.group(1)) if m else None


def parse_time(q: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(IST)
    now = now.replace(tzinfo=None) if now.tzinfo else now
    ql, today, notes = q.lower(), now.date(), []

    dates = []
    if "day after tomorrow" in ql:
        dates = [today + timedelta(days=2)]
    elif "tomorrow" in ql:
        dates = [today + timedelta(days=1)]
    elif re.search(r"\b(today|tonight|now|this (morning|afternoon|evening))\b", ql):
        dates = [today]
    elif "weekend" in ql:
        wd = today.weekday()
        if wd == 5:
            dates = [today, today + timedelta(days=1)]
        elif wd == 6:
            dates = [today]
        else:
            sat = today + timedelta(days=(5 - wd))
            dates = [sat, sat + timedelta(days=1)]
    else:
        found = [(today + timedelta(days=(i - today.weekday()) % 7)) for i, d in enumerate(WEEKDAYS)
                 if re.search(rf"\b{d}\b", ql)]
        if found:
            dates = sorted(found)
        else:
            m = re.search(r"next\s+(\d+|one|two|three|four|five|six|seven)\s+days", ql)
            if m:
                n = NUM_WORDS.get(m.group(1)) or int(m.group(1))
                dates = [today + timedelta(days=i) for i in range(min(n, 7))]
            else:
                dates = [today, today + timedelta(days=1)]
                notes.append("No date given, so I looked at today and tomorrow.")

    horizon = today + timedelta(days=6)
    if any(d > horizon for d in dates):
        dates = [d for d in dates if d <= horizon]
        notes.append("Forecast data only covers about 7 days, so later dates were dropped.")

    exact = _exact_hour(ql)
    part = None
    if exact is not None:
        start, end = max(0, exact - 1), min(23, exact + 1)
    else:
        part = next((p for p in sorted(PARTS, key=len, reverse=True) if p in ql), None)
        if part:
            start, end = PARTS[part]
        else:
            start, end = 5, 21
            notes.append("No time of day given, so I compared daytime hours (5 AM-9 PM).")

    cutoff = now.replace(minute=0, second=0, microsecond=0)

    def build(ds):
        return [datetime(d.year, d.month, d.day, h) for d in ds for h in range(start, end + 1)
                if datetime(d.year, d.month, d.day, h) >= cutoff]

    hours = build(dates)
    if not hours and dates:
        dates = [d + timedelta(days=1) for d in dates]
        hours = build(dates)
        notes.append("That time has already passed today, so I moved to the next day.")

    label = ", ".join(d.strftime("%a %d %b") for d in dates) + f" {start:02d}:00-{end + 1:02d}:00" if dates else "n/a"
    return {"dates": dates, "start_hour": start, "end_hour": end, "exact_hour": exact,
            "part": part, "hours": hours, "notes": notes, "label": label}
