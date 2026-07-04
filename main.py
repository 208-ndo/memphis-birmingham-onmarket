import logging
import time
import sys
import json
import os
from datetime import datetime
from config import (
    MARKETS, ACTIVE_MARKETS, GLOBAL_DAILY_CAP, PER_INBOX_CAP,
    OF_MIN_PRICE, OF_MAX_PRICE, OF_AUDIT_MIN_PRICE, OF_AUDIT_MAX_PRICE,
)
from scraper import ApifyQuotaError, scrape_market
from offer import calculate_offer
from email_gen import generate_emails, pick_email
from dedup import should_send, mark_sent, get_stats, is_bad_email
from gmail_send import send_batch
from ghl_push import push_to_ghl
from contact_validation import display_agent_name

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
# Per-run limit: split global daily cap evenly across 3 runs/day and active markets
# e.g. 30 cap / 3 runs = 10/run total, but enforced as a global running total
DAILY_LIMIT = PER_INBOX_CAP  # per-inbox per-day cap (passed to send_batch)

# Sent History cap — generous on purpose. At GLOBAL_DAILY_CAP=30/day this is
# ~330 days of full-volume sending before any trimming. Historical/sent
# records are audit trail, dedup reference, and follow-up tracking data —
# they are NEVER deleted by normal pipeline operation; this cap only exists
# as a sanity ceiling against unbounded file growth over years.
HISTORY_MAX_RECORDS = 10000


def get_target_markets(target_markets_raw: str | None = None) -> list[str]:
    """
    Resolve the market list for this run.

    Empty TARGET_MARKETS preserves normal ACTIVE_MARKETS behavior. Non-empty
    TARGET_MARKETS can explicitly run inactive test markets, but unknown keys
    fail fast instead of being silently skipped.
    """
    raw = os.environ.get("TARGET_MARKETS", "") if target_markets_raw is None else target_markets_raw
    if not raw or not raw.strip():
        return list(ACTIVE_MARKETS)

    selected = [part.strip() for part in raw.split(",") if part.strip()]
    unknown = [key for key in selected if key not in MARKETS]
    if unknown:
        valid = ", ".join(sorted(MARKETS))
        raise ValueError(f"Unknown TARGET_MARKETS key(s): {', '.join(unknown)}. Valid markets: {valid}")

    return selected


def classify_offer_lane(list_price: float, offer: dict) -> str:
    """
    Pure dashboard/audit classification label. Does NOT influence offer
    math, pitch_holds, dedup, or send eligibility in any way — those
    decisions are made entirely by offer.py and the existing pitch_holds
    gate in run_market(). This only labels what already happened, for
    clarity in the dashboard and logs.

      $30k-$80k                          -> OWNER_FINANCE_PRODUCTION
      $80k-$100k                         -> OWNER_FINANCE_AUDIT (never auto-sent;
                                             offer.py routes this to the cash lane,
                                             which requires ARV — absent ARV it
                                             already returns no_arv/pitch_holds=False)
      $100k+ with confirmed ARV (cash_lowball) -> CASH_LOWBALL_ARV_CONFIRMED
      $100k+ without ARV/comps           -> CASH_REVIEW_ARV_REQUIRED
      $500k+ (manual underwriting)       -> NO_AUTO_OFFER_HIGH_PRICE
    """
    if list_price <= 0:
        return "UNCLASSIFIED"

    offer_type = (offer or {}).get("offer_type", "")
    if offer_type == "seller_finance_counter":
        if (offer or {}).get("stale_seller_finance") or (offer or {}).get("requires_review"):
            return "STALE_SELLER_FINANCE_REVIEW"
        return "SELLER_FINANCE_LISTING_COUNTER"
    if offer_type == "owner_finance_rent_check":
        return "OWNER_FINANCE_RENT_CHECK_80_100"
    if offer_type == "owner_finance_manual_review":
        return "OWNER_FINANCE_MANUAL_REVIEW_100_125"

    if OF_MIN_PRICE <= list_price <= OF_MAX_PRICE:
        return "OWNER_FINANCE_PRODUCTION"

    if OF_AUDIT_MIN_PRICE < list_price <= OF_AUDIT_MAX_PRICE:
        return "OWNER_FINANCE_AUDIT"

    if offer_type == "manual_review":
        return "NO_AUTO_OFFER_HIGH_PRICE"
    if offer_type == "cash_lowball":
        return "CASH_LOWBALL_ARV_CONFIRMED"

    # no_arv, skip, or anything else above the audit band — review only
    return "CASH_REVIEW_ARV_REQUIRED"


def load_overflow() -> list:
    # ── CLEAR_OVERFLOW_BEFORE_RUN guard ───────────────────────────────────────
    # Default false — production behavior unchanged. Set true only for clean
    # dry-run testing so stale overflow from prior test runs doesn't contaminate
    # fresh-lead measurements. Does not delete or modify the committed file —
    # it only skips reading it for this run; save_overflow() still writes
    # normally afterward unless you also want to suppress that separately.
    clear_overflow_raw = os.environ.get("CLEAR_OVERFLOW_BEFORE_RUN", "false").lower().strip()
    if clear_overflow_raw == "true":
        log.info(
            "CLEAR_OVERFLOW_BEFORE_RUN=true — ignoring data/overflow.json for this run "
            "(treating overflow as empty, file on disk left untouched)"
        )
        return []

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


# ── Contact research export (2026-07-02) ────────────────────────────────────────
# Top-scored leads that finished enrichment with NO verified/sendable email
# (agent_email_finder exhausted every published-contact rung) are exported
# here instead of being silently dropped, so they can be manually researched
# rather than lost. This is a CSV export only — it never sends anything and
# never affects offer math, outreach copy, or the normal ready-to-send queue.
#
# IMPORTANT: this is a SEPARATE file from data/contact_research_queue.csv.
# That existing file holds real completed research (found_phone, contact
# source notes, approved_to_send flags for 25+ already-researched leads) in
# its own 22-column schema — this code must NEVER read, write, or otherwise
# touch it. This is a brand-new, append-only file for fresh no-email leads
# from the current run only.
NO_EMAIL_CONTACT_RESEARCH_FILE = "data/no_email_contact_research_candidates.csv"
NO_EMAIL_CONTACT_RESEARCH_COLUMNS = [
    "run_date", "market", "score", "address", "price", "dom", "brokerage",
    "listing_url", "zpid", "reason", "contact_status",
    "suggested_search_1", "suggested_search_2", "suggested_search_3",
]


def build_contact_research_row(listing: dict, market_key: str, reason: str) -> dict:
    address     = listing.get("address", "")
    brokerage   = listing.get("brokerage_name") or listing.get("brokerName") or ""
    listing_url = listing.get("listing_url") or listing.get("url") or ""
    city        = listing.get("city") or MARKETS.get(market_key, {}).get("city", "")
    dom         = listing.get("days_on_market", -1)
    parts_1 = [p for p in ([f'"{address}"'] if address else []) +
                          ([f'"{brokerage}"'] if brokerage else []) + ["email"] if p]
    return {
        "run_date":            datetime.now().date().isoformat(),
        "market":              market_key,
        "score":               listing.get("score", ""),
        "address":             address,
        "price":               listing.get("price", ""),
        "dom":                 dom if dom is not None and dom >= 0 else "",
        "brokerage":           brokerage,
        "listing_url":         listing_url,
        "zpid":                listing.get("zpid", ""),
        "reason":              reason,
        "contact_status":      "needs_contact_research",
        "suggested_search_1":  " ".join(parts_1) if (address or brokerage) else "",
        "suggested_search_2":  f'"{brokerage}" {city} office email'.strip() if brokerage else "",
        "suggested_search_3":  listing_url,
    }


def save_contact_research_queue(rows: list):
    """
    Appends (does not overwrite) rows for this run to
    data/no_email_contact_research_candidates.csv — a file dedicated to
    fresh no-email leads ONLY. Never touches data/contact_research_queue.csv,
    which holds separate, already-completed manual research in its own
    schema. Dedupes by (market, address, run_date) against anything already
    in this file so re-running the pipeline the same day doesn't create
    duplicate rows for the same lead. Writes the header only if the file
    doesn't exist yet.
    """
    import csv
    os.makedirs("data", exist_ok=True)

    existing_keys = set()
    file_exists = os.path.exists(NO_EMAIL_CONTACT_RESEARCH_FILE)
    if file_exists:
        try:
            with open(NO_EMAIL_CONTACT_RESEARCH_FILE, "r", newline="") as f:
                for r in csv.DictReader(f):
                    existing_keys.add((r.get("run_date", ""), r.get("market", ""), r.get("address", "")))
        except Exception as e:
            log.warning(f"Could not read existing {NO_EMAIL_CONTACT_RESEARCH_FILE} for dedup: {e}")

    new_rows = [r for r in rows
                if (r["run_date"], r["market"], r["address"]) not in existing_keys]

    if not new_rows:
        log.info("No-email contact research candidates: no new leads to add (all already queued today)")
        return

    write_header = not file_exists
    with open(NO_EMAIL_CONTACT_RESEARCH_FILE, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=NO_EMAIL_CONTACT_RESEARCH_COLUMNS)
        if write_header:
            writer.writeheader()
        for row in new_rows:
            writer.writerow(row)

    log.info(f"No-email contact research candidates: added {len(new_rows)} leads needing manual research "
             f"-> {NO_EMAIL_CONTACT_RESEARCH_FILE}")


def save_dashboard_data(market_key: str, leads: list, sent_results: list):
    """
    Persists the FULL current scored lead list for this market — dashboard
    "Current Scored Leads" persistence only, does not affect send eligibility,
    email enrichment caps, or which leads actually get emailed (those remain
    governed entirely by todays_leads/DAILY_LIMIT in run_market(), unchanged).

    This file is REPLACED each run (not merged/accumulated) since it
    represents what was scraped/scored THIS run. Historical sent records
    live separately and permanently in pipeline_log.json's "history" field —
    completely untouched by this function.
    """
    os.makedirs("data", exist_ok=True)
    dashboard_file = f"data/{market_key}_leads.json"

    sent_addresses = {r["listing"].get("address") for r in sent_results if r["success"]}
    bounced_addresses = {
        r["listing"].get("address")
        for r in sent_results
        if not r.get("success") and is_bad_email(r["listing"].get("agent_email"))
    }
    new_entries = []
    for lead in leads:
        address    = lead.get("address", "")
        offer      = lead.get("offer", {}) or {}
        list_price = lead.get("price", lead.get("list_price", 0))
        new_entries.append({
            "address":             address,
            "city":                lead.get("city"),
            "state":               lead.get("state"),
            "list_price":          list_price,
            "days_on_market":      lead.get("days_on_market", 0),
            "score":               lead.get("score", 0),
            "agent_name":          display_agent_name(lead.get("agent_name")),
            "agent_email":         lead.get("agent_email"),
            "agent_phone":         lead.get("agent_phone"),
            "offer_type":          offer.get("offer_type", ""),
            "offer_lane":          classify_offer_lane(list_price, offer),
            "owner_finance_offer": offer.get("owner_finance_offer", 0),
            "cash_offer":          offer.get("cash_offer", 0),
            "monthly_payment":     offer.get("monthly_payment", 0),
            "your_fee_estimate":   offer.get("your_fee_estimate", 0),
            "pitch_holds":         offer.get("pitch_holds", False),
            "down_payment":        offer.get("down_payment", 0),
            "zillow_url":          lead.get("url"),
            "email_sent":          address in sent_addresses,
            "email_bounced":       address in bounced_addresses,
            "contact_status":      "bounced" if address in bounced_addresses else ("sent" if address in sent_addresses else ""),
            "pipeline_date":       datetime.now().strftime("%Y-%m-%d"),
        })

    with open(dashboard_file, "w") as f:
        json.dump(new_entries, f, indent=2)
    log.info(f"Dashboard data saved: {dashboard_file} ({len(new_entries)} current scored leads)")


def save_pipeline_log(all_results: dict):
    os.makedirs("data", exist_ok=True)
    log_file = "data/pipeline_log.json"
    existing_runs    = []
    existing_history = []
    legacy_queue     = []  # old field name, pre-dating the queue/history split
    if os.path.exists(log_file):
        try:
            with open(log_file, "r") as f:
                old = json.load(f)
            existing_runs    = old.get("runs", [])
            existing_history = old.get("history", [])
            legacy_queue     = old.get("queue", [])
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

    # Markets actually included in THIS run — used to scope "Current Run / Active Queue"
    active_market_labels = {r["market_label"] for r in all_results.values()}

    new_queue = []
    for market_key, r in all_results.items():
        for item in r.get("sent_items", []):
            listing = item["listing"]
            offer   = item["offer"]
            sent_email = item.get("email", {})
            list_price = listing.get("price", 0)
            new_queue.append({
                "address":      listing.get("address"),
                "market":       r["market_label"],
                "price":        list_price,
                "dom":          listing.get("days_on_market", 0),
                "type":         "OF" if offer.get("offer_type") in (
                    "owner_finance",
                    "seller_finance_counter",
                    "owner_finance_rent_check",
                    "owner_finance_manual_review",
                ) else "CL",
                "offer_lane":   classify_offer_lane(list_price, offer),
                "offer":        offer.get("owner_finance_offer") or offer.get("cash_offer", 0),
                "agent":        display_agent_name(listing.get("agent_name")),
                "agent_email":  listing.get("agent_email"),
                "agent_phone":  listing.get("agent_phone"),
                "sent":         run_date,
                "status":       "SENT",
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

    combined_runs = (new_runs + existing_runs)[:30]

    # ── "queue" = CURRENT RUN / ACTIVE QUEUE ONLY ─────────────────────────────
    # Only this run's sent items, scoped to this run's active markets. Never
    # blended with older runs — that blending was the root cause of stale
    # Memphis/Birmingham rows appearing under a fresh Little Rock/OKC run.
    combined_queue = new_queue

    # ── "history" = SENT HISTORY / HISTORICAL OUTREACH — append-only ─────────
    # Every record ever written here is preserved (audit, follow-up tracking,
    # duplicate prevention). legacy_queue (the old blended field from before
    # this split existed) is migrated in once so no prior emailed records are
    # ever lost. Deduped on (address, agent_email, sent) so re-running the
    # same write doesn't create exact duplicate rows.
    merged_history = new_queue + existing_history + legacy_queue
    seen_keys = set()
    deduped_history = []
    for entry in merged_history:
        key = (entry.get("address"), entry.get("agent_email"), entry.get("sent"))
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped_history.append(entry)

    if len(deduped_history) > HISTORY_MAX_RECORDS:
        log.warning(
            f"Sent history at {len(deduped_history)} records, exceeds "
            f"HISTORY_MAX_RECORDS={HISTORY_MAX_RECORDS}. Trimming OLDEST records "
            f"only — no recent sent/emailed record is ever dropped by normal "
            f"day-to-day operation at current send volume."
        )
    combined_history = deduped_history[:HISTORY_MAX_RECORDS]

    log_data = {
        "summary": {
            "run_date":    run_date,
            "total_leads": total_leads,
            "emails_sent": total_emails,
            "ghl_pushed":  total_ghl,
            "of_deals":    total_of,
            "cl_deals":    total_cl,
            "active_markets_this_run": sorted(active_market_labels),
        },
        "runs":    combined_runs,
        "queue":   combined_queue,    # Current Run / Active Queue — this run only
        "history": combined_history,  # Sent History / Historical Outreach — all-time, never deleted
    }
    with open(log_file, "w") as f:
        json.dump(log_data, f, indent=2)
    log.info(
        f"pipeline_log.json written — {total_emails} emails this run, "
        f"{len(combined_queue)} in active queue, {len(combined_history)} in sent history"
    )


def run_market(market_key: str, dry_run: bool = False) -> dict:
    market       = MARKETS[market_key]
    market_label = f"{market['city']} {market['state']}"
    apify_disabled_no_scrape = os.environ.get("APIFY_ENABLED", "true").lower().strip() == "false"

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
        if apify_disabled_no_scrape:
            log.info(f"APIFY_DISABLED_NO_SCRAPE — preserving existing dashboard data for {market_key}")
            return result
        # Dashboard-only: reflect that THIS run found 0 current scored leads,
        # rather than leaving a stale snapshot from a prior run in place.
        save_dashboard_data(market_key, [], [])
        return result

    todays_leads       = fresh_deduped[:DAILY_LIMIT]
    overflow_remaining = fresh_deduped[DAILY_LIMIT:]
    if overflow_remaining:
        save_overflow(other_overflow + overflow_remaining)
        log.info(f"Saved {len(overflow_remaining)} leads to overflow for next run")
    else:
        save_overflow(other_overflow)

    log.info(f"[3/5] Calculating offers and generating emails...")
    send_queue         = []
    skipped_pitch       = 0
    skipped_no_email    = 0
    needs_contact_research = []  # (2026-07-02) leads with no verified email

    for listing in todays_leads:
        try:
            if not listing.get("agent_email"):
                skipped_no_email += 1
                needs_contact_research.append(
                    build_contact_research_row(listing, market_key,
                                               reason="no_verified_email_after_enrichment"))
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

            if offer.get("offer_type") in (
                "owner_finance",
                "seller_finance_counter",
                "owner_finance_rent_check",
                "owner_finance_manual_review",
            ):
                result["of_deals"] += 1
            else:
                result["cl_deals"] += 1

        except Exception as e:
            log.error(f"Error processing {listing.get('address')}: {e}")

    log.info(f"[3/5] {len(send_queue)} ready | Skipped: {skipped_pitch} pitch + {skipped_no_email} no email")

    if needs_contact_research:
        save_contact_research_queue(needs_contact_research)

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
                sender_email = MARKETS.get(market_key, {}).get("gmail_user", "")
                email_record = {**res["email"], "sender_email": sender_email}
                mark_sent(listing, email_record)
                push_to_ghl(listing, offer, res["email"], market_key)
                ghl_count += 1
            else:
                log.info(f"[DRY RUN] dedup write skipped: {listing.get('address')}")
                log.info(f"[DRY RUN] GHL skipped: {listing.get('address')}")
            result["sent_items"].append(res)
        except Exception as e:
            log.error(f"GHL error for {listing.get('address')}: {e}")

    result["ghl_pushed"] = ghl_count

    # ── Dashboard-only: compute offer/lane for the FULL current scored lead
    # list, not just the capped todays_leads send shortlist. Purely read-only
    # math via the same calculate_offer() already used above — no sending,
    # no enrichment, no change to send_queue/todays_leads/DAILY_LIMIT. Leads
    # already processed in the loop above keep their existing listing["offer"]
    # (identical recomputation would be redundant); this only fills in offer
    # data for the remaining leads beyond the per-run send cap so the
    # dashboard can show lane/type/score for the complete scored list.
    for listing in fresh_deduped:
        if "offer" not in listing:
            try:
                listing["offer"] = calculate_offer(listing) or {}
            except Exception as e:
                log.debug(f"Dashboard offer calc skipped for {listing.get('address')}: {e}")
                listing["offer"] = {}

    save_dashboard_data(market_key, fresh_deduped, sent_results)

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
    try:
        target_markets = get_target_markets()
    except ValueError as e:
        log.error(str(e))
        sys.exit(1)

    # Skip day gate if manually forced
    if not force_run and today not in [1, 2, 3, 4]:
        day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        log.info(f"Today is {day_names[today]} — pipeline only runs Tue/Wed/Thu/Fri. Exiting.")
        log.info("Tip: use --force flag or set FORCE_RUN=true to run on any day.")
        sys.exit(0)

    os.makedirs("data", exist_ok=True)
    os.makedirs("data/offers", exist_ok=True)

    log.info(
        f"Pipeline starting | Markets: {', '.join(target_markets)} | "
        f"Dry run: {dry_run} | Force: {force_run} | "
        f"Global cap: {GLOBAL_DAILY_CAP}/day | Per-inbox: {PER_INBOX_CAP}/day | "
        f"Time: {datetime.now().strftime('%H:%M UTC')}"
    )

    all_results = {}

    # Read actual sends already made today before this run starts
    # Prevents over-sending across multiple scheduled runs on the same day
    from gmail_send import count_sent_today_global
    global_sent_today = 0 if dry_run else count_sent_today_global()
    global_sent_this_run = 0

    if not dry_run:
        log.info(f"Global sends already today (before this run): {global_sent_today}/{GLOBAL_DAILY_CAP}")
        if global_sent_today >= GLOBAL_DAILY_CAP:
            log.info(f"Global daily cap of {GLOBAL_DAILY_CAP} already reached for today — exiting")
            save_pipeline_log({})
            if dry_run:
                log.info("DRY RUN complete — no Gmail emails sent and no GHL contacts/texts triggered.")
            else:
                log.info("All markets complete. Dashboard updated. Check GHL for contacts.")
            return

    for i, market_key in enumerate(target_markets):
        remaining_cap = GLOBAL_DAILY_CAP - (global_sent_today + global_sent_this_run)
        if remaining_cap <= 0:
            log.info(f"Global daily cap of {GLOBAL_DAILY_CAP} reached — skipping remaining markets")
            break

        log.info(
            f"Global: {global_sent_today + global_sent_this_run}/{GLOBAL_DAILY_CAP} sent today "
            f"({global_sent_today} prior runs + {global_sent_this_run} this run) | "
            f"Remaining: {remaining_cap}"
        )

        if i > 0:
            log.info("Waiting 3 minutes between markets...")
            time.sleep(180)

        try:
            result = run_market(market_key, dry_run=dry_run)
            all_results[market_key] = result
            global_sent_this_run += result.get("emails_sent", 0)
        except ApifyQuotaError:
            log.error("APIFY QUOTA BLOCKED — preserving previous dashboard data and stopping workflow.")
            return
        except Exception as e:
            log.error(f"{market_key} pipeline error: {e}")
            all_results[market_key] = {
                "market_label": f"{MARKETS[market_key]['city']} {MARKETS[market_key]['state']}",
                "leads": 0, "emails_sent": 0,
                "ghl_pushed": 0, "of_deals": 0, "cl_deals": 0, "sent_items": []
            }

    log.info(f"All markets complete | Sent this run: {global_sent_this_run} | Total today: {global_sent_today + global_sent_this_run}/{GLOBAL_DAILY_CAP}")

    save_pipeline_log(all_results)
    if dry_run:
        log.info("DRY RUN complete — no Gmail emails sent and no GHL contacts/texts triggered.")
    else:
        log.info("All markets complete. Dashboard updated. Check GHL for contacts.")


if __name__ == "__main__":
    main()
