import os
import sys
import json
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from curl_cffi import requests

SEARCH_URLS = [
    "https://www.funda.nl/zoeken/koop?selected_area=%5B%22voorburg%22%2C%22leidschendam%22%2C%22zoetermeer%22%2C%22gouda%22%2C%22prins-alexander%22%5D&object_type=%5B%22house%22%5D",
]

HISTORY_FILE = "seen_houses.json"

def get_seen_houses():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen_houses(seen_set):
    with open(HISTORY_FILE, "w") as f:
        json.dump(list(seen_set), f)

def get_headers():
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    }

def calculate_match_score(house_data):
    """Calculates a match score out of 100 based on Marc & Suus's preferences."""
    score = 0
    reasons = []

    # 1. Property Type Preference (Max 30 pts)
    # Whole houses are preferred over ground-floor/stacked apartments
    is_house = "huis" in house_data["url"].lower() or "woonhuis" in house_data.get("type", "").lower()
    if is_house:
        score += 30
        reasons.append("Woonhuis (+30)")
    else:
        score += 10
        reasons.append("Appartement (+10)")

    # 2. Living Area / Space (Max 30 pts)
    m2 = house_data.get("living_area", 0)
    if m2 >= 110:
        score += 30
        reasons.append(f"{m2}m² Ruim (+30)")
    elif m2 >= 85:
        score += 20
        reasons.append(f"{m2}m² Gemiddeld (+20)")
    elif m2 > 0:
        score += 10
        reasons.append(f"{m2}m² Compact (+10)")

    # 3. Energy Label / Sustainability (Max 20 pts)
    label = house_data.get("energy_label", "").upper()
    if any(x in label for x in ["A++++", "A+++", "A++", "A+", "A", "B"]):
        score += 20
        reasons.append(f"Energielabel {label} (+20)")
    elif label in ["C", "D"]:
        score += 10
        reasons.append(f"Energielabel {label} (+10)")
    elif label:
        score += 5
        reasons.append(f"Energielabel {label} (+5)")

    # 4. Location Priority (Max 20 pts)
    url_lower = house_data["url"].lower()
    if "voorburg" in url_lower:
        score += 20
        reasons.append("Voorburg (+20)")
    elif "leidschendam" in url_lower or "prins-alexander" in url_lower:
        score += 15
        reasons.append("Goede locatie (+15)")
    else:
        score += 10
        reasons.append("Regio (+10)")

    return min(score, 100), reasons

def extract_house_details(url):
    """Scrapes individual property pages to extract detailed specs for scoring."""
    details = {"living_area": 0, "energy_label": "Onbekend", "type": "Huis"}
    try:
        res = requests.get(url, headers=get_headers(), impersonate="chrome120")
        if res.status_code != 200:
            return details
        
        soup = BeautifulSoup(res.text, "html.parser")
        
        # Look for JSON-LD data on detail page
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "{}")
                if isinstance(data, dict):
                    if "floorSize" in data:
                        details["living_area"] = int(data["floorSize"].get("value", 0))
                    if "energyRating" in data:
                        details["energy_label"] = str(data["energyRating"]).strip()
            except Exception:
                continue

        # Fallback text parsing for living area
        if details["living_area"] == 0:
            m2_match = re.search(r"(\d+)\s*m²\s*wonen", res.text, re.IGNORECASE)
            if m2_match:
                details["living_area"] = int(m2_match.group(1))

    except Exception as e:
        print(f"Failed to fetch details for {url}: {e}")

    return details

def scrape_funda():
    found_houses = {}

    for url in SEARCH_URLS:
        response = requests.get(url, headers=get_headers(), impersonate="chrome120")
        if response.status_code != 200:
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/detail/koop/" in href:
                full_url = href if href.startswith("http") else f"https://www.funda.nl{href}"
                clean_url = full_url.split("?")[0]
                
                title = a.get_text(strip=True)
                if not title or len(title) < 5 or "€" in title:
                    title = clean_url.split("/")[-2].replace("-", " ").title()

                found_houses[clean_url] = {"url": clean_url, "name": title}

    # Fetch specs and compute scores for found houses
    results = []
    for clean_url, house in found_houses.items():
        specs = extract_house_details(clean_url)
        house.update(specs)
        score, reasons = calculate_match_score(house)
        house["score"] = score
        house["reasons"] = reasons
        results.append(house)

    # Sort listings by match score (highest match first)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

def send_email(new_houses):
    sender = os.environ["EMAIL_SENDER"].strip()
    password = os.environ["EMAIL_PASSWORD"].replace(" ", "").strip()
    recipient = os.environ["EMAIL_RECIPIENT"].strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🏠 Funda Update: {len(new_houses)} House(s) Ranked by Match Score!"
    msg["From"] = f"Funda House Hunter <{sender}>"
    msg["To"] = recipient

    cards_html = ""
    for h in new_houses:
        # Pick badge color based on score
        score_color = "#16a34a" if h['score'] >= 75 else ("#ca8a04" if h['score'] >= 50 else "#dc2626")
        reasons_str = " • ".join(h['reasons'])

        cards_html += f"""
        <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h3 style="margin: 0; color: #1e293b; font-size: 18px;">{h['name']}</h3>
                <span style="background-color: {score_color}; color: #ffffff; font-weight: bold; font-size: 13px; padding: 4px 10px; border-radius: 12px; white-space: nowrap;">
                    {h['score']}% Match
                </span>
            </div>
            <p style="margin: 0 0 10px 0; color: #475569; font-size: 13px; font-weight: 500;">
                {reasons_str}
            </p>
            <a href="{h['url']}" style="display: inline-block; background-color: #f97316; color: #ffffff; text-decoration: none; font-weight: bold; font-size: 14px; padding: 10px 18px; border-radius: 6px;">Bekijk op Funda →</a>
        </div>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px;">
        <div style="max-width: 600px; margin: 0 auto;">
            <div style="background-color: #f97316; padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
                <h1 style="color: #ffffff; margin: 0; font-size: 22px;">🏡 Funda Match Digest</h1>
            </div>
            <div style="background-color: #f1f5f9; padding: 20px; border-radius: 0 0 8px 8px;">
                <p style="color: #334155; font-size: 15px; margin-top: 0;">Hi Marc & Suus,</p>
                <p style="color: #334155; font-size: 15px;">Here are today's listings, ranked by match score according to your search preferences:</p>
                {cards_html}
                <hr style="border: none; border-top: 1px solid #cbd5e1; margin: 24px 0 16px 0;" />
                <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">Automated search digest generated via GitHub Actions.</p>
            </div>
        </div>
    </body>
    </html>
    """

    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

if __name__ == "__main__":
    ignore_seen = "--ignore-seen" in sys.argv

    seen = get_seen_houses()
    listings = scrape_funda()

    if ignore_seen:
        print("Manual run triggered: ignoring history file and sending all current listings.")
        fresh_houses = listings
    else:
        fresh_houses = [h for h in listings if h["url"] not in seen]

    if fresh_houses:
        print(f"Found {len(fresh_houses)} houses to send. Sending email...")
        send_email(fresh_houses)

        if not ignore_seen:
            for h in fresh_houses:
                seen.add(h["url"])
            save_seen_houses(seen)
    else:
        print("No new listings found.")