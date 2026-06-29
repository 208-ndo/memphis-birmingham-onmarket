import logging
import time
import sys
import json
import os
from datetime import datetime
from config import MARKETS
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
DAILY_LIMIT   = 5


def load_overflow() -> list:
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
    os.makedirs("data", exist_ok=True)
    with open(OVERFLOW_FILE, "w") as f:
        json.dump(leads, f, indent=2)
    log.info(f"Saved {len(leads)} leads to overflow for next run")


def save_dashboard_data(market_key: str, leads: list, sent_results: list):
    os.makedirs("data", exist_ok=True)
    dashboard_file = f"data/{market_key}_leads.json"
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
        offer   = lead.get("offer", {})
        new_entries.append({
            "address":             address,
            "city":                lead.get("city"),
            "state":               lead.get("state"),
            "list_price":          lead.get("price", 0),
            "days_on_market":      lead.get("days_on_market", 0),
            "agent_name":          lead.get("agent_name"),
            "agent_email":         lead.get("agent_email"),
            "agent_phone":         lead.get("agent_phone"),
            "offer_type":          offer.get("offer_type", ""),
            "owner_finance_offer": offer.get("owner_finance_offer", 0),
            "cash_offer":          offer.get("cash_offer", 0),
            "monthly_payment":     offer.get("monthly_payment", 0),
            "your_fee_estimate":   offer.get("your_fee_estimate", 0),
            "pitch_holds":         offer.get("pitch_holds", False),
            "down_payment":        offer.get("down_payment", 0),
            "zillow_url":          lead.get("url"),
            "email_sent":          address in sent_addresses,
            "pipeline_date":       datetime.now().strftime("%Y-%m-%d"),
        })

    all_entries = new_entries + [
        e for e in existing
        if e["address"] not in {n["address"] for n in new_entries}
    ]
    all_entries = all_entries[:200]
    with open(dashboard_file, "w") as f:
        json.dump(all_entries, f, indent=2)
    log.info(f"Dashboard data saved: {dashboard_file}")


def save_pipeline_log(all_results: dict):
    os.makedirs("data", exist_ok=True)
    log_file = "data/pipeline_log.json"
    existing_runs  = []
    existing_queue = []
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                old = json.load(f)
            existing_runs  = old.get("runs", [])
            existing_queue = old.get("queue", [])
        except Exception:
            pass

    run_date     = datetime.now().strftime("%Y-%m-%d %H:%M")
    total_leads  = sum(r["leads"] for r in all_results.values())
    total_emails = sum(r["emails_sent"] for r in all_results.values())
    total_ghl    = sum(r["ghl_pushed"] for r in all_results.values())
    total_of     = sum(r["of_deals"] for r in all_results.values())
    total_cl     = sum(r["cl_deals"] for r in all_results.values())

    new_runs = []
    for market_key, r in all_results.items():
        new_runs.append({
            "date":   run_date,
            "market": r["market_label"],
            "leads":  r["leads"],
            "emails": r["emails_sent"],
            "of":     r["of_deals"],
            "cl":     r["cl_deals"],
            "ghl":    r["ghl_pushed"],
            "status": "OK" if r["emails_sent"] > 0 else "NO SENDS",
        })

    new_queue = []
    for market_key, r in all_results.items():
        for item in r.get("sent_items", []):
            listing = item["listing"]
            offer   = item["offer"]
            sent_email = item.get("email", {})
            new_queue.append({
                "address":      listing.get("address"),
                "market":       r["market_label"],
                "price":        listing.get("price", 0),
                "dom":          listing.get("days_on_market", 0),
                "type":         "OF" if offer.get("offer_type") == "owner_finance" else "CL",
                "offer":        offer.get("owner_finance_offer") or offer.get("cash_offer", 0),
                "agent":        listing.get("agent_name"),
                "agent_email":  listing.get("agent_email"),
                "agent_phone":  listing.get("agent_phone"),
                "sent":         run_date,
                "zillow_url":   listing.get("url"),
                "email_subject": sent_email.get("subject"),
                "email_body":   sent_email.get("body"),
                "down_payment":       offer.get("down_payment", 0),
                "monthly_payment":    offer.get("monthly_payment", 0),
                "num_payments":       offer.get("num_payments", 100),
                "financed_balance":   offer.get("financed_balance", 0),
                "cash_offer":         offer.get("cash_offer", 0),
                "total_to_agent":     offer.get("total_to_agent", 0),
                "at_list_commission": offer.get("at_list_commission", 0),
                "your_fee":           offer.get("your_fee_estimate", 0),
                "your_monthly_cashflow": offer.get("your_monthly_cashflow", 0),
                "assign_price":       offer.get("assign_price", 0),
                "pitch_holds":        offer.get("pitch_holds", False),
            })

    combined_runs  = (new_runs + existing_runs)[:30]
    combined_queue = (new_queue + existing_queue)[:200]

    log_data = {
        "summary": {
            "run_date":    run_date,
            "total_leads": total_leads,
            "emails_sent": total_emails,
            "ghl_pushed":  total_ghl,
            "of_deals":    total_of,
            "cl_deals":    total_cl,
        },
        "runs":  combined_runs,
        "queue": combined_queue,
    }
    with open(log_file, "w") as f:
        json.dump(log_data, f, indent=2)
    log.info(f"pipeline_log.json written — {total_emails} emails, {total_leads} leads")


def run_market(market_key: str, dry_run: bool = False) -> dict:
    market       = MARKETS[market_key]
    market_label = f"{market['city']} {market['state']}"

    log.info(f"{'='*60}")
    log.info(f"PIPELINE: {market_key.upper()} | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"DRY RUN: {dry_run} | LIMIT: {DAILY_LIMIT} emails this run")
    log.info(f"{'='*60}")

    result = {
        "market_label": market_label,
        "leads":        0,
        "emails_sent":  0,
        "ghl_pushed":   0,
        "of_deals":     0,
        "cl_deals":     0,
        "sent_items":   [],
    }

    overflow_leads      = load_overflow()
    overflow_for_market = [l for l in overflow_leads if l.get("market") == market_key]
    other_overflow      = [l for l in overflow_leads if l.get("market") != market_key]

    log.info(f"[1/5] Scraping Zillow for {market_key}...")
    fresh_leads = scrape_market(market)
    log.info(f"[1/5] {len(fresh_leads)} fresh leads from Zillow")

    all_leads       = overflow_for_market + fresh_leads
    result["leads"] = len(fresh_leads)

    fresh_deduped = [l for l in all_leads if should_send(l)]
    log.info(f"[2/5] {len(fresh_deduped)} after dedup")

    if not fresh_deduped:
        log.info("No fresh leads — exiting market")
        save_overflow(other_overflow)
        return result

    todays_leads       = fresh_deduped[:DAILY_LIMIT]
    overflow_remaining = fresh_deduped[DAILY_LIMIT:]
    if overflow_remaining:
        save_overflow(other_overflow + overflow_remaining)
        log.info(f"Saved {len(overflow_remaining)} leads to overflow for next run")
    else:
        save_overflow(other_overflow)

    log.info(f"[3/5] Calculating offers and generating emails...")
    send_queue       = []
    skipped_pitch    = 0
    skipped_no_email = 0

    for listing in todays_leads:
        try:
            if not listing.get("agent_email"):
                skipped_no_email += 1
                continue

            listing["list_price"] = listing.get("price", 0)
            offer = calculate_offer(listing)
            if not offer:
                continue

            if not offer.get("pitch_holds", True):
                skipped_pitch += 1
                otype  = offer.get("offer_type", "unknown")
                reason = offer.get("skip_reason") or offer.get("reason") or "pitch_holds=False"
                lp     = offer.get("list_price", listing.get("price", 0))
                co     = offer.get("cash_offer", 0)
                of_    = offer.get("owner_finance_offer", 0)
                if otype in ("no_arv", "manual_cash_review", "manual_review"):
                    log.info(
                        f"SKIP (needs ARV/manual review): {listing.get('address')} | "
                        f"type={otype} | list_price=${lp:,.0f} | reason={reason}"
                    )
                else:
                    log.info(
                        f"SKIP (pitch fails): {listing.get('address')} | "
                        f"type={otype} | list_price=${lp:,.0f} | "
                        f"cash_offer=${co:,.0f} | of_offer=${of_:,.0f} | reason={reason}"
                    )
                continue

            listing["offer"] = offer
            emails = generate_emails(listing, offer)
            if not emails:
                log.warning(f"No emails generated for {listing.get('address')}")
                continue

            chosen_email = pick_email(emails)
            send_queue.append({"listing": listing, "offer": offer, "email": chosen_email})

            if offer.get("offer_type") == "owner_finance":
                result["of_deals"] += 1
            else:
                result["cl_deals"] += 1

        except Exception as e:
            log.error(f"Error processing {listing.get('address')}: {e}")

    log.info(f"[3/5] {len(send_queue)} ready | Skipped: {skipped_pitch} pitch + {skipped_no_email} no email")

    log.info(f"[4/5] Sending emails...")
    sent_results = send_batch(send_queue, market_key, dry_run=dry_run)
    successful   = [r for r in sent_results if r["success"]]
    result["emails_sent"] = len(successful)
    log.info(f"[4/5] {len(successful)} emails sent")

    log.info(f"[5/5] {'DRY RUN — skipping GHL push' if dry_run else 'Pushing to GHL...'}")
    ghl_count = 0
    for res in successful:
        listing = res["listing"]
        offer   = listing.get("offer", {})
        try:
            if not dry_run:
                mark_sent(listing, res["email"])
                push_to_ghl(listing, offer, res["email"], market_key)
                ghl_count += 1
            else:
                log.info(f"[DRY RUN] dedup write skipped: {listing.get('address')}")
                log.info(f"[DRY RUN] GHL skipped: {listing.get('address')}")
            result["sent_items"].append(res)
        except Exception as e:
            log.error(f"GHL error for {listing.get('address')}: {e}")

    result["ghl_pushed"] = ghl_count
    save_dashboard_data(market_key, todays_leads, sent_results)

    stats = get_stats()
    log.info(f"{'='*60}")
    log.info(
        f"COMPLETE: {market_key.upper()} | "
        f"Scraped: {len(fresh_leads)} | Sent: {len(successful)} | "
        f"Pitch skipped: {skipped_pitch} | No email: {skipped_no_email}"
    )
    log.info(f"All-time: {stats['total_properties_emailed']} properties | {stats['total_agents_contacted']} agents")
    log.info(f"{'='*60}")
    return result


def main():
    today        = datetime.now().weekday()  # 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun
    dry_run      = "--dry-run" in sys.argv
    force_run    = "--force" in sys.argv or os.environ.get("FORCE_RUN", "").lower() == "true"

    # Skip day gate if manually forced
    if not force_run and today not in [1, 2, 3, 4]:
        day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        log.info(f"Today is {day_names[today]} — pipeline only runs Tue/Wed/Thu/Fri. Exiting.")
        log.info("Tip: use --force flag or set FORCE_RUN=true to run on any day.")
        sys.exit(0)

    os.makedirs("data", exist_ok=True)
    os.makedirs("data/offers", exist_ok=True)

    log.info(
        f"Pipeline starting | Markets: Memphis + Birmingham | "
        f"Dry run: {dry_run} | Force: {force_run} | Limit: {DAILY_LIMIT}/run | "
        f"Time: {datetime.now().strftime('%H:%M UTC')}"
    )

    all_results = {}

    try:
        all_results["memphis"] = run_market("memphis", dry_run=dry_run)
    except Exception as e:
        log.error(f"Memphis pipeline error: {e}")
        all_results["memphis"] = {
            "market_label": "Memphis TN", "leads": 0, "emails_sent": 0,
            "ghl_pushed": 0, "of_deals": 0, "cl_deals": 0, "sent_items": []
        }

    log.info("Waiting 3 minutes between markets...")
    time.sleep(180)

    try:
        all_results["birmingham"] = run_market("birmingham", dry_run=dry_run)
    except Exception as e:
        log.error(f"Birmingham pipeline error: {e}")
        all_results["birmingham"] = {
            "market_label": "Birmingham AL", "leads": 0, "emails_sent": 0,
            "ghl_pushed": 0, "of_deals": 0, "cl_deals": 0, "sent_items": []
        }

    save_pipeline_log(all_results)
    log.info("Both markets complete. Dashboard updated. Check GHL for contacts.")


if __name__ == "__main__":
    main()
