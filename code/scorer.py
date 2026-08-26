import json
import math
import os
import re
import time
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATED_DIR = os.path.join(BASE_DIR, "generated")

RAW_DATA_FILE = os.path.join(GENERATED_DIR, "scraped_houses.json")
SCORED_DATA_FILE = os.path.join(GENERATED_DIR, "scored_houses.json")
HISTORY_FILE = os.path.join(GENERATED_DIR, "seen_houses.json")
GEO_CACHE_FILE = os.path.join(GENERATED_DIR, "geo_cache.json")

VOORBURG_CENTER = (52.0722, 4.3592)
geolocator = Nominatim(user_agent="dutch_house_scorer_voorburg")


def ensure_generated_dir():
    os.makedirs(GENERATED_DIR, exist_ok=True)


def get_seen_houses():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_seen_houses(seen_set):
    """Saves the set of seen house URLs to history file."""
    ensure_generated_dir()
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_set), f, indent=2)


def load_geo_cache():
    if os.path.exists(GEO_CACHE_FILE):
        try:
            with open(GEO_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_geo_cache(cache):
    ensure_generated_dir()
    with open(GEO_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2, ensure_ascii=False)


def haversine_distance(coord1, coord2):
    lat1, lon1 = coord1
    lat2, lon2 = coord2
    R = 6371.0

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return R * c


def extract_searchable_address(house_data):
    address = house_data.get("address") or house_data.get("title") or ""
    city = house_data.get("city") or ""

    if address and city:
        return f"{address}, {city}, Netherlands"
    elif address:
        return f"{address}, Netherlands"

    url = house_data.get("url", "")
    match = re.search(r"koop/([^/]+)/huizen|koop/([^/]+)/", url)
    if match:
        raw_slug = match.group(1) or match.group(2)
        parts = [p for p in raw_slug.split("-") if not p.isdigit() and p not in ("huis", "appartement")]
        if len(parts) >= 2:
            return f"{' '.join(parts[1:])}, {parts[0]}, Netherlands"
        elif len(parts) == 1:
            return f"{parts[0]}, Netherlands"

    return "Netherlands"


def geocode_address(address_str, cache):
    if not address_str or address_str == "Netherlands":
        return None

    address_clean = address_str.lower().strip()

    if address_clean in cache:
        cached_val = cache[address_clean]
        return tuple(cached_val) if cached_val else None

    try:
        location = geolocator.geocode(address_clean, timeout=5)
        time.sleep(1.0)

        if location:
            coords = (location.latitude, location.longitude)
            cache[address_clean] = list(coords)
            return coords
        else:
            cache[address_clean] = None
            return None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        print(f"Geocoding error for '{address_str}': {e}")
        return None


def score_price(price):
    if price <= 0:
        return 0.0, "Prijs onbekend (+0)"

    target_budget = 550000
    sweet_spot = 450000
    hard_max = 600000

    if price <= sweet_spot:
        score = 30.0
    elif price <= target_budget:
        score = 30.0 - 20.0 * ((price - sweet_spot) / (target_budget - sweet_spot))
    elif price <= hard_max:
        score = 10.0 - 10.0 * ((price - target_budget) / (hard_max - target_budget))
    else:
        score = 0.0

    return round(score, 1), f"€{price:,.0f} (+{score:.1f})"


def score_living_area(m2):
    if m2 <= 0:
        return 0.0, "Oppervlakte onbekend (+0)"

    min_m2, max_m2 = 60, 120

    if m2 >= max_m2:
        score = 30.0
    elif m2 <= min_m2:
        score = max(0.0, (m2 / min_m2) * 5.0)
    else:
        score = 5.0 + 25.0 * ((m2 - min_m2) / (max_m2 - min_m2))

    return round(score, 1), f"{m2}m² (+{score:.1f})"


def score_energy_label(label):
    label_upper = label.upper().replace("ENERGIELABEL", "").strip()

    label_weights = {
        "A++++": 20.0, "A+++": 19.5, "A++": 18.5, "A+": 17.5,
        "A": 16.0, "B": 13.0, "C": 9.0, "D": 6.0, "E": 3.0,
        "F": 1.0, "G": 0.0,
    }

    score = 0.0
    for key, weight in label_weights.items():
        if key in label_upper:
            score = weight
            break

    if score == 0.0 and label_upper and label_upper != "ONBEKEND":
        score = 5.0

    return round(score, 1), f"Label {label_upper or 'Onbekend'} (+{score:.1f})"


def score_property_type(house_data):
    url_lower = house_data["url"].lower()
    type_str = house_data.get("type", "").lower()

    is_house = "huis" in url_lower or "woonhuis" in type_str
    type_score = 20.0 if is_house else 8.0
    return type_score, f"{'Woonhuis' if is_house else 'Appartement'} (+{type_score:.1f})"


def score_address_location(house_data, cache):
    address_str = extract_searchable_address(house_data)
    coords = geocode_address(address_str, cache)

    if not coords and house_data.get("latitude") and house_data.get("longitude"):
        coords = (float(house_data["latitude"]), float(house_data["longitude"]))

    if not coords:
        return 8.0, "Locatie onbekend / Geocode mislukt (+8.0)"

    dist_km = haversine_distance(VOORBURG_CENTER, coords)
    max_radius_km = 25.0

    if dist_km <= 0.5:
        score = 20.0
    elif dist_km >= max_radius_km:
        score = 1.0
    else:
        decay_ratio = dist_km / max_radius_km
        score = 20.0 * ((1.0 - decay_ratio) ** 1.5)

    score = round(max(1.0, score), 1)
    return score, f"{dist_km:.1f}km van Centrum Voorburg (+{score:.1f})"


def calculate_match_score(house_data, cache):
    reasons = []

    p_score, p_reason = score_price(house_data.get("price", 0))
    reasons.append(p_reason)

    m2_score, m2_reason = score_living_area(house_data.get("living_area", 0))
    reasons.append(m2_reason)

    e_score, e_reason = score_energy_label(house_data.get("energy_label", "Onbekend"))
    reasons.append(e_reason)

    t_score, t_reason = score_property_type(house_data)
    reasons.append(t_reason)

    l_score, l_reason = score_address_location(house_data, cache)
    reasons.append(l_reason)

    raw_total = p_score + m2_score + e_score + t_score + l_score
    final_score = round(min((raw_total / 120.0) * 100.0, 100.0), 1)

    return final_score, reasons


def process_and_rank_houses(ignore_seen=False):
    ensure_generated_dir()

    if not os.path.exists(RAW_DATA_FILE):
        print(f"File {RAW_DATA_FILE} not found. Run scraper first.")
        return [], set()

    with open(RAW_DATA_FILE, "r", encoding="utf-8") as f:
        houses = json.load(f)

    seen = get_seen_houses()
    geo_cache = load_geo_cache()
    all_scored_houses = []

    for house in houses:
        score, reasons = calculate_match_score(house, geo_cache)
        house_entry = house.copy()
        house_entry["score"] = score
        house_entry["reasons"] = reasons
        all_scored_houses.append(house_entry)

    save_geo_cache(geo_cache)
    all_scored_houses.sort(key=lambda x: x["score"], reverse=True)

    with open(SCORED_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_scored_houses, f, indent=2, ensure_ascii=False)

    target_houses = all_scored_houses if ignore_seen else [h for h in all_scored_houses if h["url"] not in seen]
    return target_houses, seen


if __name__ == "__main__":
    ranked, _ = process_and_rank_houses(ignore_seen=True)
    print(f"Scored {len(ranked)} total listings.")