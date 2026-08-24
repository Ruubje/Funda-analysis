import os
import sys
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from curl_cffi import requests

# Search locations based on chat preferences: Voorburg, Leidschendam, Zoetermeer, Gouda, Rotterdam Prins Alexander
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

def scrape_funda():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    found_houses = {}

    for url in SEARCH_URLS:
        response = requests.get(url, headers=headers, impersonate="chrome120")
        if response.status_code != 200:
            print(f"Failed to fetch page: {response.status_code}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        # Extract links directly from HTML anchor tags
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "/detail/koop/" in href:
                full_url = href if href.startswith("http") else f"https://www.funda.nl{href}"
                clean_url = full_url.split("?")[0]
                
                title = a.get_text(strip=True)
                if not title or len(title) < 5 or "€" in title:
                    # Clean address title from URL path slug
                    title = clean_url.split("/")[-2].replace("-", " ").title()

                found_houses[clean_url] = {"url": clean_url, "name": title}

    return list(found_houses.values())

def send_email(new_houses):
    sender = os.environ["EMAIL_SENDER"].strip()
    password = os.environ["EMAIL_PASSWORD"].replace(" ", "").strip()
    recipient = os.environ["EMAIL_RECIPIENT"].strip()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🏠 Funda Update: {len(new_houses)} New House(s) Found!"
    msg["From"] = f"Funda House Hunter <{sender}>"
    msg["To"] = recipient

    # HTML Email Template
    cards_html = ""
    for h in new_houses:
        cards_html += f"""
        <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
            <h3 style="margin: 0 0 8px 0; color: #1e293b; font-size: 18px;">{h['name']}</h3>
            <p style="margin: 0 0 12px 0; color: #64748b; font-size: 14px;">Matching search areas: Voorburg, Leidschendam, Zoetermeer, Gouda & Prins Alexander</p>
            <a href="{h['url']}" style="display: inline-block; background-color: #f97316; color: #ffffff; text-decoration: none; font-weight: bold; font-size: 14px; padding: 10px 18px; border-radius: 6px;">Bekijk op Funda →</a>
        </div>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 24px;">
        <div style="max-width: 600px; margin: 0 auto;">
            <div style="background-color: #f97316; padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
                <h1 style="color: #ffffff; margin: 0; font-size: 22px;">🏡 New Property Alerts</h1>
            </div>
            <div style="background-color: #f1f5f9; padding: 20px; border-radius: 0 0 8px 8px;">
                <p style="color: #334155; font-size: 15px; margin-top: 0;">Hi Marc & Suus,</p>
                <p style="color: #334155; font-size: 15px;">Here are the latest matching house listings found on Funda today:</p>
                {cards_html}
                <hr style="border: none; border-top: 1px solid #cbd5e1; margin: 24px 0 16px 0;" />
                <p style="color: #94a3b8; font-size: 12px; text-align: center; margin: 0;">Automated daily search digest generated via GitHub Actions.</p>
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