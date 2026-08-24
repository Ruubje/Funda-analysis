import os
import json
import re
import smtplib
import sys
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    response = requests.get(SEARCH_URL, headers=headers, impersonate="chrome120")
    if response.status_code != 200:
        print(f"Failed to fetch page: {response.status_code}")
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    found_houses = {}

    # Method 1: Parse all listing links directly from HTML anchor tags
    for a in soup.find_all("a", href=True):
        href = a["href"]
        # Matches house detail URLs on Funda (e.g., /detail/koop/amsterdam/huis-...)
        if "/detail/koop/" in href or "/detail/huur/" in href:
            full_url = href if href.startswith("http") else f"https://www.funda.nl{href}"
            # Clean tracking parameters from URL
            clean_url = full_url.split("?")[0]
            
            # Extract title text or fallback to URL slug
            title = a.get_text(strip=True)
            if not title or len(title) < 5:
                # Extract address from URL slug
                title = clean_url.split("/")[-2].replace("-", " ").title()

            found_houses[clean_url] = {"url": clean_url, "name": title}

    # Method 2: Fallback to JSON-LD blocks if any exist
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "{}")
            if isinstance(data, dict) and "itemListElement" in data:
                for item in data["itemListElement"]:
                    url = item.get("url")
                    if url:
                        clean_url = url.split("?")[0]
                        found_houses[clean_url] = {
                            "url": clean_url, 
                            "name": item.get("name", clean_url.split("/")[-2].replace("-", " ").title())
                        }
        except (json.JSONDecodeError, TypeError):
            continue

    return list(found_houses.values())

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
    # Check if --ignore-seen flag was passed from command line
    ignore_seen = "--ignore-seen" in sys.argv

    seen = get_seen_houses()
    listings = scrape_funda()

    if ignore_seen:
        print("Manual run triggered: ignoring history file and sending all current listings.")
        fresh_houses = listings
    else:
        # Filter for brand-new listings only
        fresh_houses = [h for h in listings if h["url"] not in seen]

    if fresh_houses:
        print(f"Found {len(fresh_houses)} houses to send. Sending email...")
        send_email(fresh_houses)

        # Only update the history file during normal scheduled runs
        if not ignore_seen:
            for h in fresh_houses:
                seen.add(h["url"])
            save_seen_houses(seen)
    else:
        print("No listings found to send.")