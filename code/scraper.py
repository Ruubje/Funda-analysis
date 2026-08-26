import json
import os
import re
import time
from urllib.parse import urlencode
from bs4 import BeautifulSoup
from curl_cffi import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATED_DIR = os.path.join(BASE_DIR, "generated")
RAW_DATA_FILE = os.path.join(GENERATED_DIR, "scraped_houses.json")

TARGET_CITIES = [
    "voorburg",
    "leidschendam",
    "zoetermeer",
    "gouda",
    "prins-alexander",
    "rijswijk-zuid-holland",
    "nootdorp",
    "pijnacker",
    "wassenaar",
    "wateringen",
    "leidschenveen",
    "ypenburg",
]

FILTERS = {
    "price_max": 550000,
    "price_min": None,
    "floor_area_min": None,
    "bedrooms_min": None,
    "energy_labels": [],
    "object_type": ["house"],
}


def build_city_search_url(city, filters):
    """Builds search URL targeting a single municipality slug using selected_area."""
    base = "https://www.funda.nl/zoeken/koop"
    
    # Selected area must be a JSON-encoded array containing the city slug
    params = {"selected_area": json.dumps([city])}

    if filters.get("object_type"):
        params["object_type"] = json.dumps(filters["object_type"])

    p_min = str(filters["price_min"]) if filters.get("price_min") else ""
    p_max = str(filters["price_max"]) if filters.get("price_max") else ""
    if p_min or p_max:
        params["price"] = f'"{p_min}-{p_max}"'

    if filters.get("floor_area_min"):
        params["floor_area"] = f'"{filters["floor_area_min"]}-"'

    return f"{base}?{urlencode(params)}"


def get_headers():
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    }


def parse_nuxt_state(soup):
    """Parses __NUXT_DATA__ array to locate living area, price, and energy label."""
    extracted = {}
    nuxt_script = soup.find("script", id="__NUXT_DATA__")
    if not nuxt_script or not nuxt_script.string:
        return extracted

    try:
        data_array = json.loads(nuxt_script.string)
        if not isinstance(data_array, list):
            return extracted

        for idx, item in enumerate(data_array):
            if isinstance(item, str):
                if item == "livingArea" and idx + 1 < len(data_array):
                    val = data_array[idx + 1]
                    if isinstance(val, (int, float)) and val > 0:
                        extracted["living_area"] = int(val)
                elif item == "energyLabel" and idx + 1 < len(data_array):
                    val = data_array[idx + 1]
                    if isinstance(val, str) and len(val) <= 4:
                        extracted["energy_label"] = val.upper()
    except Exception:
        pass

    return extracted


def extract_house_details(url):
    """Extracts specs directly from detail pages using Nuxt state, HTML tags, and Regex."""
    details = {"living_area": 0, "energy_label": "Onbekend", "price": 0, "type": "Huis"}
    try:
        res = requests.get(url, headers=get_headers(), impersonate="chrome120")
        if res.status_code != 200:
            return details

        html_text = res.text
        soup = BeautifulSoup(html_text, "html.parser")

        # 1. Nuxt State Data Extraction
        nuxt_data = parse_nuxt_state(soup)
        if nuxt_data.get("living_area"):
            details["living_area"] = nuxt_data["living_area"]
        if nuxt_data.get("energy_label"):
            details["energy_label"] = nuxt_data["energy_label"]

        # 2. Extract Living Area from dl / dt / dd feature tables
        if details["living_area"] == 0:
            for dt in soup.find_all(["dt", "span", "div"]):
                text = dt.get_text(strip=True).lower()
                if "wonen" in text or "gebruiksoppervlakte" in text:
                    sibling = dt.find_next_sibling() or dt.parent.find_next_sibling()
                    target_text = sibling.get_text() if sibling else dt.parent.get_text()
                    match = re.search(r"(\d+)\s*m²", target_text)
                    if match:
                        details["living_area"] = int(match.group(1))
                        break

        # 3. Comprehensive Regex Fallbacks for Living Area
        if details["living_area"] == 0:
            patterns = [
                r"(\d+)\s*m²\s*(?:wonen|gebruiksoppervlakte)",
                r"Wonen\s*</[^>]+>\s*<[^>]+>\s*(\d+)\s*m²",
                r"\"livingArea\":\s*(\d+)",
                r"\"oppervlakte\":\s*(\d+)",
                r"(\d+)\s*m²",
            ]
            for pat in patterns:
                m2_match = re.search(pat, html_text, re.IGNORECASE)
                if m2_match:
                    val = int(m2_match.group(1))
                    if 20 <= val <= 600:
                        details["living_area"] = val
                        break

        # 4. JSON-LD scripts fallback
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict):
                        if details["living_area"] == 0 and "floorSize" in item:
                            fs = item["floorSize"]
                            if isinstance(fs, dict) and "value" in fs:
                                details["living_area"] = int(fs["value"])
                        if details["price"] == 0 and "offers" in item:
                            offers = item["offers"]
                            if isinstance(offers, list) and offers:
                                offers = offers[0]
                            if isinstance(offers, dict) and "price" in offers:
                                details["price"] = float(offers["price"])
            except Exception:
                continue

        # 5. Price Regex fallback
        if details["price"] == 0:
            price_match = re.search(r"€\s*([\d\.]+)", html_text)
            if price_match:
                raw_price = price_match.group(1).replace(".", "")
                if raw_price.isdigit() and len(raw_price) >= 5:
                    details["price"] = float(raw_price)

        # 6. Energy Label Regex fallback
        if details["energy_label"] == "Onbekend":
            label_match = re.search(
                r'energielabel[":\s]+([A-G](?:\+{1,4})?)', html_text, re.IGNORECASE
            )
            if label_match:
                details["energy_label"] = label_match.group(1).upper()

    except Exception as e:
        print(f"Failed to fetch details for {url}: {e}")

    return details


def scrape_and_store(filters=None):
    os.makedirs(GENERATED_DIR, exist_ok=True)
    active_filters = filters if filters is not None else FILTERS
    found_houses = {}

    # Scrape listings per target municipality
    for city in TARGET_CITIES:
        search_url = build_city_search_url(city, active_filters)
        print(f"Scraping city [{city}]: {search_url}")

        try:
            response = requests.get(
                search_url, headers=get_headers(), impersonate="chrome120"
            )
            if response.status_code != 200:
                print(f"Skipping {city}: HTTP {response.status_code}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            city_count = 0

            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/detail/koop/" in href:
                    full_url = href if href.startswith("http") else f"https://www.funda.nl{href}"
                    clean_url = full_url.split("?")[0]

                    if clean_url not in found_houses:
                        url_parts = clean_url.rstrip("/").split("/")
                        address_slug = url_parts[-1] if len(url_parts) > 0 else ""
                        city_slug = url_parts[-2] if len(url_parts) > 1 else city

                        formatted_title = f"{address_slug.replace('-', ' ').title()}, {city_slug.title()}"
                        found_houses[clean_url] = {"url": clean_url, "name": formatted_title}
                        city_count += 1

            print(f"Found {city_count} new listings in {city}.")
            time.sleep(1.0)  # Gentle rate limit safety delay
        except Exception as e:
            print(f"Error scraping city {city}: {e}")

    scraped_results = []
    print(f"\nTotal unique listings collected: {len(found_houses)}. Extracting house specs...")

    for clean_url, house in found_houses.items():
        specs = extract_house_details(clean_url)
        house.update(specs)
        scraped_results.append(house)

    with open(RAW_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(scraped_results, f, indent=2, ensure_ascii=False)

    print(f"Successfully stored {len(scraped_results)} listings in {RAW_DATA_FILE}.")
    return scraped_results


if __name__ == "__main__":
    scrape_and_store()