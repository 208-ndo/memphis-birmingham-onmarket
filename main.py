import logging
import time
import sys
import json
import os
from datetime import datetime
from scraper import scrape_market
from offer import calculate_offer
from email_gen import generate_emails, pick_email
from dedup import should_send, mark_sent, get_stats
from gmail_send import send_batch
from ghl_push import push_to_ghl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/pipeline.log", mode="a"),
    ]
)
log = logging.getLogger(__name__)

OVERFLOW_FILE = "data/overflow.json"
DAILY_LIMIT = 15


def load_overflow() -> list:
    """Load saved overflow leads from previous run."""
    if not os.path.exists(OVERFLOW_FILE):
        return []
    try:
        with open(OVERFLOW_FILE, "r") as f:
            data = json.load(f)
            log.info(f"Loaded {len(data)} overflow leads from previous run")
            return data
    except Exception:
        return []


def save_overflow(leads: list):
    """Save excess leads for next run."""
    os.makedirs("data", exist_ok=True)
    with open(OVERFLOW_FILE, "w") as f:
        json.dump(leads, f, indent=2)
    log.info(f"Saved {len(leads)} leads to overflow for next run")


def clear_overflow():
    """Clear overflow file after consuming it."""
    if os.path.exists(OVERFLOW_FILE):
        os.remove(OVERFLOW_FILE)


def save_dashboard_data(market_key: str, leads: list, sent_results: list):
    """Save data for GitHub Pages dashboard."""
    os.makedirs("data", exist_ok=True)
    dashboard_file = f"data/{market_key}_leads.json"

    # Load existing data
    existing = []
    if os.path.exists(dashboard_file):
        try:
            with open(dashboard_file, "r") as f:
                existing = json.load(f)
        except Exception:
            existing = []

    sent_addresses = {r["listing"].get("address") for r in sent_results if r["success"]}

    new_entries = []
    for lead in leads:
        address = lead.get("address", "")
        offer = lead.get("offer", {})
        new_entries.append({
            "address": address,
            "city": lead.get("city"),
            "state": lead.get("state"),
            "list_price": lead.get("list_price", 0),
            "days_on_market": lead.get("days_on_market", 0),
            "views_per_day": lead.get("views_per_day", 0),
            "has_price_cut": lead.get("has_price_cut", False),
            "score": lead.get("score", 0),
            "agent_name": lead.get("listing_agent"),
            "agent_email": lead.get("agent_email"),
            "agent_phone": lead.get("agent_phone"),
            "owner_finance_offer": offer.get("owner_finance_offer", 0),
            "cash_offer": offer.get("cash_offer", 0),
            "zillow_url": lead.get("url"),
            "email_sent": address in sent_addresses,
            "scraped_at": lead.get("scraped_at"),
            "pipeline_date": datetime.now().strftime("%Y-%m-%d"),
        })

    # Merge — newest first, dedup by address
    all_entries = new_entries + [e for e in existing if e["address"] not in {n["address"] for n in new_entries}]
    all_entries = all_entries[:200]  # Keep last 200 entries

    with open(dashboard_file, "w") as f:
        json.dump(all_entries, f, indent=2)
    log.info(f"Dashboard data saved: {dashboard_file}")


def run_market(market_key: str, dry_run: bool = False):
    """Run the full pipeline for a single market with overflow logic."""
    log.info(f"{'='*60}")
    log.info(f"PIPELINE: {market_key.upper()} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"{'='*60}")

    # STEP 1 — Load overflow from previous run first
    overflow_leads = load_overflow()
    overflow_for_market = [l for l in overflow_leads if l.get("market") == market_key]
    other_overflow = [l for l in overflow_leads if l.get("market") != market_key]

    # STEP 2 — Scrape fresh leads
    log.info(f"[1/5] Scraping Zillow for {market_key}...")
    fresh_leads = scrape_market(market_key)
    log.info(f"[1/5] {len(fresh_leads)} fresh leads from Zillow")

    # STEP 3 — Combine overflow + fresh, overflow gets priority
    all_leads = overflow_for_market + fresh_leads
    log.info(f"[2/5] Total pool: {len(all_leads)} leads ({len(overflow_for_market)} overflow + {len(fresh_leads)} fresh)")

    # STEP 4 — Dedup filter
    fresh_deduped = [l for l in all_leads if should_send(l)]
    log.info(f"[2/5] {len(fresh_deduped)} after dedup")

    if not fresh_deduped:
        log.info("No fresh leads to send — exiting market")
        clear_overflow()
        return []

    # STEP 5 — Apply daily limit + save overflow
    todays_leads = fresh_deduped[:DAILY_LIMIT]
    overflow_remaining = fresh_deduped[DAILY_LIMIT:]

    if overflow_remaining:
        save_overflow(other_overflow + overflow_remaining)
        log.info(f"Overflow saved: {len(overflow_remaining)} leads for tomorrow")
    else:
        save_overflow(other_overflow)

    log.info(f"Sending today: {len(todays_leads)} | Overflow for tomorrow: {len(overflow_remaining)}")

    # STEP 6 — Calculate offers + generate emails
    log.info(f"[3/5] Generating offers and emails...")
    send_queue = []

    for listing in todays_leads:
        try:
            offer = calculate_offer(listing)
            listing["offer"] = offer
            emails = generate_emails(listing, offer)
            if not emails:
                continue
            chosen_email = pick_email(emails)
            send_queue.append({
                "listing": listing,
                "offer": offer,
                "email": chosen_email,
            })
        except Exception as e:
            log.error(f"Error processing {listing.get('address')}: {e}")

    log.info(f"[3/5] {len(send_queue)} ready to send")

    # STEP 7 — Send emails
    log.info(f"[4/5] Sending emails...")
    sent_results = send_batch(send_queue, market_key, dry_run=dry_run)
    successful = [r for r in sent_results if r["success"]]
    log.info(f"[4/5] {len(successful)} sent successfully")

    # STEP 8 — GHL push + SMS + mark sent
    log.info(f"[5/5] Pushing to GHL...")
    for result in successful:
        listing = result["listing"]
        offer = listing.get("offer", {})
        email_sent = result["email"]
        try:
            mark_sent(listing, email_sent)
            if not dry_run:
                push_to_ghl(listing, offer, email_sent, market_key)
            else:
                log.info(f"[DRY RUN] GHL skipped: {listing.get('address')}")
        except Exception as e:
            log.error(f"GHL error: {e}")

    # STEP 9 — Save dashboard data
    save_dashboard_data(market_key, todays_leads, sent_results)

    stats = get_stats()
    log.info(f"COMPLETE: {market_key.upper()} | Sent: {len(successful)} | Total ever: {stats['total_properties_emailed']}")
    return sent_results


def main():
    """Run both markets. Tue/Wed/Thu only."""
    today = datetime.now().weekday()
    dry_run = "--dry-run" in sys.argv

    if today not in [1, 2, 3]:
        day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        log.info(f"Today is {day_names[today]} — runs Tue/Wed/Thu only. Exiting.")
        sys.exit(0)

    log.info(f"Starting both markets | Dry run: {dry_run}")

    try:
        run_market("memphis", dry_run=dry_run)
    except Exception as e:
        log.error(f"Memphis error: {e}")

    log.info("Waiting 5 min between markets...")
    time.sleep(300)

    try:
        run_market("birmingham", dry_run=dry_run)
    except Exception as e:
        log.error(f"Birmingham error: {e}")

    log.info("Both markets complete.")


if __name__ == "__main__":
    main()
