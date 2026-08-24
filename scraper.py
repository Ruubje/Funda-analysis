import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from curl_cffi import requests

# Config
SEARCH_URL = "https://www.funda.nl/zoeken/koop?selected_area=%5B%22amsterdam%22%5D&price=%22300000-500000%22"
HISTORY_FILE = "seen_houses.json"

def get_seen_houses():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_seen_houses(seen_set):
    with open(HISTORY_FILE, "w") as f:
        json.dump(list(seen_set), f)

def scrape_funda():
    # Impersonate Chrome to bypass Akamai TLS checks
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    response = requests.get(SEARCH_URL, headers=headers, impersonate="chrome120")
    if response.status_code != 200:
        print(f"Failed to fetch page: {response.status_code}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    new_listings = []
    
    # Extract embedded JSON-LD metadata for reliable parsing
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string)
            if isinstance(data, list):
                for item in data:
                    if item.get("@type") == "SingleFamilyResidence" or "url" in item:
                        new_listings.append({"url": item.get("url"), "name": item.get("name", "New Listing")})
        except (json.JSONDecodeError, TypeError):
            continue

    return new_listings

def send_email(new_houses):
    sender = os.environ["EMAIL_SENDER"]
    password = os.environ["EMAIL_PASSWORD"]
    recipient = os.environ["EMAIL_RECIPIENT"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🏠 {len(new_houses)} New Funda Listings Found!"
    msg["From"] = sender
    msg["To"] = recipient

    body = "<h2>New houses available on Funda:</h2><ul>"
    for h in new_houses:
        body += f"<li><a href='{h['url']}'>{h['name']}</a></li>"
    body += "</ul>"

    msg.attach(MIMEText(body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

if __name__ == "__main__":
    seen = get_seen_houses()
    listings = scrape_funda()
    
    # Filter for brand-new listings
    fresh_houses = [h for h in listings if h["url"] not in seen]

    if fresh_houses:
        print(f"Found {len(fresh_houses)} new houses. Sending email...")
        send_email(fresh_houses)
        
        # Update seen list
        for h in fresh_houses:
            seen.add(h["url"])
        save_seen_houses(seen)
    else:
        print("No new listings today.")