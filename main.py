import sys
from code.notifier import save_html_preview, send_email
from code.scorer import process_and_rank_houses, save_seen_houses
from code.scraper import scrape_and_store

if __name__ == "__main__":
    ignore_seen = "--ignore-seen" in sys.argv
    preview_mode = "--preview" in sys.argv

    # Step 1: Scrape & save locally into generated/
    scrape_and_store()

    # Step 2: Read local data & score into generated/
    fresh_houses, seen_set = process_and_rank_houses(ignore_seen=ignore_seen)

    # Step 3: Output action (Save preview vs Send email)
    if fresh_houses:
        if preview_mode:
            print(f"Preview mode enabled: Saving HTML file for {len(fresh_houses)} houses...")
            save_html_preview(fresh_houses)
        else:
            print(f"Found {len(fresh_houses)} listings to notify. Sending email...")
            send_email(fresh_houses)

            if not ignore_seen:
                for house in fresh_houses:
                    seen_set.add(house["url"])
                save_seen_houses(seen_set)
    else:
        print("No new listings found.")