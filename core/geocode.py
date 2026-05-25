"""Address geocoding for order placement snapshots."""


def geocode_address_snapshot(addr_row):
    import json
    import time
    import urllib.parse
    import urllib.request

    line = str(addr_row.get("address_line") or "").strip()
    city = str(addr_row.get("city") or "").strip()
    state = str(addr_row.get("state") or "").strip()
    pincode = str(addr_row.get("pincode") or "").strip()

    queries = []
    full = ", ".join(p for p in [line, city, state, pincode, "India"] if p)
    if full:
        queries.append(full)
    if line and city:
        queries.append(", ".join(p for p in [line, city, pincode, "India"] if p))
    if city and pincode:
        queries.append(f"{city}, {pincode}, India")
    if pincode:
        queries.append(f"{pincode}, India")

    seen = set()
    headers = {"User-Agent": "PandeyjiEatery-FoodChatbot/1.0 (order-snapshot-geocode)"}
    for q in queries:
        if not q or q in seen:
            continue
        seen.add(q)
        try:
            url = (
                "https://nominatim.openstreetmap.org/search?"
                + urllib.parse.urlencode({"format": "json", "limit": "1", "q": q})
            )
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                rows = json.loads(resp.read().decode())
            time.sleep(1.1)
            if not rows:
                continue
            lat = float(rows[0]["lat"])
            lng = float(rows[0]["lon"])
            if -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0:
                return lat, lng
        except Exception:
            continue
    return None, None
