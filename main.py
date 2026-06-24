import logging
import time
import sys
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


def run_market(market_key: str, dry_run: bool = False):
    """Run the full pipeline for a single market."""
    log.info(f"{'='*60}")
    log.info(f"STARTING PIPELINE: {market_key.upper()} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"DRY RUN: {dry_run}")
    log.info(f"{'='*60}")

    # STEP 1 — Scrape Zillow
    log.info(f"[1/5] Scraping Zillow for {market_key}...")
    leads = scrape_market(market_key)
    log.info(f"[1/5] {len(leads)} leads passed screening")

    if not leads:
        log.info(f"No leads found for {market_key} — exiting")
        return

    # STEP 2 — Dedup filter
    log.info(f"[2/5] Running dedup check...")
    fresh_leads = [l for l in leads if should_send(l)]
    log.info(f"[2/5] {len(fresh_leads)} fresh leads after dedup (skipped {len(leads) - len(fresh_leads)})")

    if not fresh_leads:
        log.info(f"All leads already contacted — exiting")
        return

    # STEP 3 — Calculate offers + generate emails
    log.info(f"[3/5] Calculating offers and generating emails...")
    send_queue = []

    for listing in fresh_leads:
        try:
            # Calculate offer
            offer = calculate_offer(listing)
            listing["offer"] = offer

            # Generate 4 email variations via Claude API
            emails = generate_emails(listing, offer)
            if not emails:
                log.warning(f"No emails generated for {listing.get('address')} — skipping")
                continue

            # Pick one variation to send
            chosen_email = pick_email(emails)

            send_queue.append({
                "listing": listing,
                "offer": offer,
                "email": chosen_email,
            })
        except Exception as e:
            log.error(f"Error processing {listing.get('address')}: {e}")
            continue

    log.info(f"[3/5] {len(send_queue)} leads ready to send")

    # STEP 4 — Send emails via Gmail
    log.info(f"[4/5] Sending emails...")
    sent_results = send_batch(send_queue, market_key, dry_run=dry_run)
    successful_sends = [r for r in sent_results if r["success"]]
    log.info(f"[4/5] {len(successful_sends)} emails sent successfully")

    # STEP 5 — GHL push + SMS for each successful send
    log.info(f"[5/5] Pushing to GHL and firing texts...")
    for result in successful_sends:
        listing = result["listing"]
        offer = listing.get("offer", {})
        email_sent = result["email"]

        try:
            # Mark as sent in dedup log FIRST
            mark_sent(listing, email_sent)

            # Push to GHL + fire SMS (SMS fires after 30 min delay internally)
            if not dry_run:
                push_to_ghl(listing, offer, email_sent, market_key)
            else:
                log.info(f"[DRY RUN] Would push to GHL + SMS: {listing.get('address')}")

        except Exception as e:
            log.error(f"GHL push error for {listing.get('address')}: {e}")
            continue

    # Final summary
    stats = get_stats()
    log.info(f"{'='*60}")
    log.info(f"PIPELINE COMPLETE: {market_key.upper()}")
    log.info(f"Leads scraped: {len(leads)}")
    log.info(f"Emails sent: {len(successful_sends)}")
    log.info(f"Total properties ever emailed: {stats['total_properties_emailed']}")
    log.info(f"Total agents ever contacted: {stats['total_agents_contacted']}")
    log.info(f"{'='*60}")


def main():
    """
    Run pipeline for both markets.
    Weekdays only — Tue/Wed/Thu for best agent response rates.
    """
    today = datetime.now().weekday()  # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri

    # Check for dry run flag
    dry_run = "--dry-run" in sys.argv

    # Weekday gate — only run Tue/Wed/Thu
    if today not in [1, 2, 3]:
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        log.info(f"Today is {day_names[today]} — pipeline only runs Tue/Wed/Thu. Exiting.")
        sys.exit(0)

    log.info(f"Pipeline starting for both markets | Dry run: {dry_run}")

    # Run Memphis first
    try:
        run_market("memphis", dry_run=dry_run)
    except Exception as e:
        log.error(f"Memphis pipeline error: {e}")

    # Wait between markets to avoid rate limits
    log.info("Waiting 5 minutes between markets...")
    time.sleep(300)

    # Run Birmingham
    try:
        run_market("birmingham", dry_run=dry_run)
    except Exception as e:
        log.error(f"Birmingham pipeline error: {e}")

    log.info("Both markets complete.")


if __name__ == "__main__":
    main()
