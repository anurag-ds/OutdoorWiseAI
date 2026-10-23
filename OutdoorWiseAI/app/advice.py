"""What to carry / what to watch for, derived from the conditions at the recommended hour."""
STATIC_GEAR = {
    "running": ["Breathable clothes and well-fitting running shoes"],
    "cycling": ["Helmet", "Water bottle"],
    "golf": ["Cap, towel and water", "Spare balls and a glove"],
    "cricket": ["Water and a hat", "Spare shoes in case the pitch is damp"],
    "football": ["Shin guards and water", "Shoes with good grip"],
    "tennis": ["Spare balls and a grip towel", "Sun hat and water"],
    "hiking": ["Trail shoes, snacks and water", "Offline map and a torch"],
    "walking": ["Comfortable shoes and water"],
    "picnic": ["Mat, snacks and water", "Bags to carry your trash out"],
    "event": ["Shade or a tent and drinking water", "A backup plan for the weather"],
    "photography": ["Extra battery and a lens cloth", "Tripod for low light"],
}


def gear_and_watch(act, profiles, f, aqi_soft, wind_soft):
    """f = facts of the recommended hour (rounded numbers)."""
    gear, watch = list(STATIC_GEAR[act]), []
    t, uv, rain = f.get("feels_like_c", 25), f.get("uv_index", 0), f.get("rain_chance_pct", 0)
    aqi_eff = f.get("aqi_local_adjusted") or f.get("aqi") or 0
    if t >= 28:
        gear.append("Extra water and a cap")
        watch.append("Heat exhaustion signs (dizziness, headache, nausea): stop, shade, hydrate")
    if t <= 12:
        gear.append("A warm layer")
    if uv >= 6:
        gear.append("Sunscreen and sunglasses")
    if rain >= 30:
        gear.append("Rain jacket or umbrella")
        watch.append("Wet, slippery surfaces")
    if aqi_eff > aqi_soft:
        gear.append("An N95 mask if you are sensitive to dust or smoke")
        watch.append("Hazy air: cut intensity if you cough or feel breathless")
    if f.get("wind_kmh", 0) >= wind_soft:
        watch.append("Gusty wind")
    if act == "cycling":
        gear.append("Front and rear lights for low light")
    if act in ("photography", "hiking") and f.get("sunset"):
        watch.append(f"Sunset is at {f['sunset']}, so plan to finish before dark")
    if "asthma" in profiles:
        gear.append("Your prescribed reliever inhaler")
        watch.append("Stop if you feel wheezy or breathless; warm up slowly")
    if "senior" in profiles:
        watch.append("Keep an easy pace and carry a phone")
    if "child" in profiles:
        gear.append("Water and a hat for the kids")
        watch.append("Take frequent water breaks")
    if "pregnancy" in profiles:
        watch.append("Avoid overheating; rest in shade and stop if dizzy")
    if "heart" in profiles:
        watch.append("Keep intensity low and stop if you feel chest discomfort")
    if profiles:
        watch.append("General guidance only, not medical advice; check with your doctor")
    return gear[:7], watch[:6]
