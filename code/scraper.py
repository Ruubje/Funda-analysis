import argparse
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

MANUAL_URLS = []

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

        # 2. Extract Living Area from feature tables
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

        # 3. Regex Fallbacks for Living Area
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


def create_house_entry(url):
    """Cleans a Funda detail URL and formats its display name."""
    clean_url = url.split("?")[0].rstrip("/") + "/"
    url_parts = [p for p in clean_url.split("/") if p and p != "https:" and p != "http:"]

    # Check if we have a standard URL (domain/detail/koop/city/address/id)
    if "koop" in url_parts and len(url_parts) >= 4:
        address_idx = url_parts.index("koop") + 2
        city_idx = url_parts.index("koop") + 1
        
        if address_idx < len(url_parts):
            address_slug = url_parts[address_idx]
            city_slug = url_parts[city_idx]
            formatted_title = f"{address_slug.replace('-', ' ').title()}, {city_slug.title()}"
            return clean_url, {"url": clean_url, "name": formatted_title}

    # Fallback for short URLs (e.g., funda.nl/detail/44481411/): Use listing ID as name
    listing_id = url_parts[-1]
    formatted_title = f"Funda Listing #{listing_id}"
    return clean_url, {"url": clean_url, "name": formatted_title}


def load_existing_houses():
    """Loads existing listings from scraped_houses.json to prevent overwriting."""
    if os.path.exists(RAW_DATA_FILE):
        try:
            with open(RAW_DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Key entries by URL for duplicate checking
                return {house["url"]: house for house in data if "url" in house}
        except Exception as e:
            print(f"Could not load existing dataset: {e}")
    return {}


def scrape_and_store(filters=None, extra_urls=None, skip_search=False):
    os.makedirs(GENERATED_DIR, exist_ok=True)
    active_filters = filters if filters is not None else FILTERS

    # 1. Load existing listings from json so we append instead of overwrite
    existing_houses = load_existing_houses()
    new_house_urls = set()
    found_houses = dict(existing_houses)

    # 2. Process explicit CLI / manual URLs
    manual_list = extra_urls if extra_urls is not None else MANUAL_URLS
    if manual_list:
        print(f"Processing {len(manual_list)} explicit URL(s)...")
        for raw_url in manual_list:
            clean_url, house_obj = create_house_entry(raw_url)
            if clean_url not in found_houses:
                found_houses[clean_url] = house_obj
                new_house_urls.add(clean_url)

    # 3. Scrape target cities (unless explicitly skipped via CLI argument)
    if not skip_search:
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
                        clean_url, house_obj = create_house_entry(full_url)

                        if clean_url not in found_houses:
                            found_houses[clean_url] = house_obj
                            new_house_urls.add(clean_url)
                            city_count += 1

                print(f"Found {city_count} new listings in {city}.")
                time.sleep(1.0)
            except Exception as e:
                print(f"Error scraping city {city}: {e}")

    # 4. Extract detailed specifications ONLY for newly added URLs
    if new_house_urls:
        print(f"\nExtracting house specs for {len(new_house_urls)} new listing(s)...")
        for clean_url in new_house_urls:
            specs = extract_house_details(clean_url)
            found_houses[clean_url].update(specs)
    else:
        print("\nNo new listings to extract specs for.")

    # 5. Save all houses back to JSON
    scraped_results = list(found_houses.values())
    with open(RAW_DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(scraped_results, f, indent=2, ensure_ascii=False)

    print(f"Successfully updated {RAW_DATA_FILE}. Total stored listings: {len(scraped_results)}.")
    return scraped_results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scrape Funda property listings.")
    parser.add_argument(
        "--url",
        nargs="+",
        help="One or more direct Funda detail URLs to scrape and append.",
    )
    args = parser.parse_args()

    if args.url:
        scrape_and_store(extra_urls=args.url, skip_search=True)
    else:
        scrape_and_store()