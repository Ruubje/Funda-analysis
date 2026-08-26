import json
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENERATED_DIR = os.path.join(BASE_DIR, "generated")

SCORED_DATA_FILE = os.path.join(GENERATED_DIR, "scored_houses.json")
HTML_PREVIEW_FILE = os.path.join(GENERATED_DIR, "email_preview.html")


def ensure_generated_dir():
    os.makedirs(GENERATED_DIR, exist_ok=True)


def calculate_price_per_m2(house):
    """Calculates price per m2 living area."""
    price = house.get("price", 0)
    m2 = house.get("living_area", 0)

    if price > 0 and m2 > 0:
        price_m2 = round(price / m2)
        return f"€{price_m2:,.0f}/m²"
    return "Prijs/m² N/B"


def generate_html_body(houses):
    """Generates and returns the complete HTML email body for a list of scored houses."""
    cards_html = ""
    for h in houses:
        score_color = (
            "#16a34a"
            if h["score"] >= 75
            else ("#ca8a04" if h["score"] >= 50 else "#dc2626")
        )
        reasons_str = " • ".join(h["reasons"])
        price_m2_str = calculate_price_per_m2(h)

        cards_html += f"""
        <div style="background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 18px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.04);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px;">
                <h3 style="margin: 0; color: #1e293b; font-size: 18px;">{h['name']}</h3>
                <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
                    <span style="background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; font-weight: 600; font-size: 12px; padding: 4px 8px; border-radius: 12px; white-space: nowrap;">
                        {price_m2_str}
                    </span>
                    <span style="background-color: {score_color}; color: #ffffff; font-weight: bold; font-size: 13px; padding: 4px 10px; border-radius: 12px; white-space: nowrap;">
                        {h['score']}% Match
                    </span>
                </div>
            </div>
            <p style="margin: 0 0 10px 0; color: #475569; font-size: 13px; font-weight: 500;">
                {reasons_str}
            </p>
            <a href="{h['url']}" style="display: inline-block; background-color: #f97316; color: #ffffff; text-decoration: none; font-weight: bold; font-size: 14px; padding: 10px 18px; border-radius: 6px;">Bekijk op Funda →</a>
        </div>
        """

    return f"""
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


def save_html_preview(houses, filename=HTML_PREVIEW_FILE):
    """Saves the generated HTML to generated/email_preview.html for browser viewing."""
    ensure_generated_dir()
    if not houses:
        print("No houses provided to generate HTML preview.")
        return None

    html_content = generate_html_body(houses)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"HTML preview saved to {filename}. Open this file in your browser to view.")
    return filename


def send_email(houses_to_send):
    """Sends scored house listings via SMTP email."""
    if not houses_to_send:
        print("No houses provided to send.")
        return

    sender = os.environ["EMAIL_SENDER"].strip()
    password = os.environ["EMAIL_PASSWORD"].replace(" ", "").strip()
    recipient = os.environ["EMAIL_RECIPIENT"].strip()

    html_body = generate_html_body(houses_to_send)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (
        f"🏠 Funda Update: {len(houses_to_send)} House(s) Ranked by Match Score!"
    )
    msg["From"] = f"Funda House Hunter <{sender}>"
    msg["To"] = recipient

    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    print("Email sent successfully.")


if __name__ == "__main__":
    if os.path.exists(SCORED_DATA_FILE):
        with open(SCORED_DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        save_html_preview(data)
    else:
        print(f"File {SCORED_DATA_FILE} not found. Run scorer.py first.")