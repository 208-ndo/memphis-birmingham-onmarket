import smtplib
import time
import random
import logging
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime, timezone
from config import MARKETS, EMAIL, DEDUP, GLOBAL_DAILY_CAP, PER_INBOX_CAP
from generate_offer_pdf import generate_offer_pdf
from dedup import mark_bounced

from contact_validation import email_is_sendable as cv_email_is_sendable

log = logging.getLogger(__name__)


# ── Calendar-day send counters ─────────────────────────────────────────────────
# Cap is per sender inbox email, not per market.
# A single inbox shared by 2 markets still caps at PER_INBOX_CAP/day combined.

def _load_dedup_log() -> dict:
    try:
        with open(DEDUP["log_file"]) as f:
            return json.load(f)
    except Exception:
        return {"properties": {}, "agents": {}, "opted_out": [], "bad_emails": []}


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def count_sent_today_by_inbox(sender_email: str) -> int:
    """
    Count confirmed sends today from a specific Gmail sender address.
    Counts across ALL markets that share this inbox.
    Returns 0 if dedup log is missing or unreadable (safe — batch cap still applies).
    """
    if not sender_email:
        return 0
    today = _today_utc()
    data  = _load_dedup_log()
    count = 0
    sender_lower = sender_email.lower().strip()
    for prop in data.get("properties", {}).values():
        sent_at = str(prop.get("sent_at", ""))
        if (sent_at.startswith(today)
                and prop.get("status") == "sent"
                and prop.get("sender_email", "").lower().strip() == sender_lower):
            count += 1
    return count


def count_sent_today_global() -> int:
    """
    Count all confirmed sends today across every inbox.
    Enforces GLOBAL_DAILY_CAP = 30 regardless of how many markets or inboxes are active.
    """
    today = _today_utc()
    data  = _load_dedup_log()
    return sum(
        1 for prop in data.get("properties", {}).values()
        if str(prop.get("sent_at", "")).startswith(today)
        and prop.get("status") == "sent"
    )


# ── Core email sender ──────────────────────────────────────────────────────────

def send_email(
    market_key: str,
    to_email: str,
    subject: str,
    body: str,
    pdf_path: str = None,
    dry_run: bool = False,
    email_confidence: str = ""
) -> bool:
    # Dry run checked FIRST — no credential lookup happens above this line's
    # outcome for a dry run (2026-07-02 fix, defense in depth: send_batch no
    # longer even calls this function during a dry run, but any other/future
    # caller passing dry_run=True must also never hit the credential check).
    if dry_run:
        log.info(f"[DRY RUN] Would send to {to_email} | Subject: {subject} | PDF: {bool(pdf_path)}")
        return True

    market         = MARKETS[market_key]
    gmail_user     = market["gmail_user"]
    gmail_password = market["gmail_app_password"]

    if not gmail_user or not gmail_password:
        log.error(f"Missing Gmail credentials for market: {market_key}")
        return False

    if not to_email:
        log.warning("No agent email — skipping send")
        return False

    # ── In-process live-send hard guard (2026-07-02) ─────────────────────────
    # The workflow already forces --dry-run unless the LIVE_SEND_ENABLED
    # secret is "true", but this guard makes the process itself refuse real
    # SMTP sends even if dry_run parsing was weird upstream. Belt and
    # suspenders: no LIVE_SEND_ENABLED=true env, no live email. Ever.
    live_send_env = os.environ.get("LIVE_SEND_ENABLED", "").lower().strip()
    if live_send_env != "true":
        log.warning(
            f"[LIVE-SEND BLOCKED] LIVE_SEND_ENABLED env is '{live_send_env or 'unset'}' "
            f"(not 'true') — refusing real send to {to_email} despite dry_run={dry_run}. "
            f"Treating as dry run."
        )
        return True

    # ── Sendable-confidence guard (2026-07-02) ───────────────────────────────
    # Live sends only to source_verified / snippet_verified / office_fallback
    # emails. pattern_guess is never sendable unless ALLOW_PATTERN_GUESS_SENDS
    # is explicitly enabled (see contact_validation.py).
    confidence = (email_confidence or "").strip()
    if confidence and not cv_email_is_sendable(confidence):
        log.warning(
            f"[LIVE-SEND BLOCKED] email confidence '{confidence}' is not sendable "
            f"— skipping {to_email}"
        )
        return False

    try:
        msg             = MIMEMultipart("mixed")
        msg["Subject"]  = subject
        msg["From"]     = gmail_user
        msg["To"]       = to_email
        msg["Reply-To"] = gmail_user
        msg.attach(MIMEText(body, "plain"))

        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                pdf_data = f.read()
            pdf_part = MIMEApplication(pdf_data, _subtype="pdf")
            pdf_part.add_header("Content-Disposition", "attachment", filename=os.path.basename(pdf_path))
            msg.attach(pdf_part)
            log.info(f"PDF attached: {os.path.basename(pdf_path)}")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, to_email, msg.as_string())

        log.info(f"SENT ✅ → {to_email} | Subject: {subject} | PDF: {'yes' if pdf_path else 'no'}")
        return True

    except smtplib.SMTPAuthenticationError:
        log.error(f"Gmail auth failed for {gmail_user} — check App Password")
        return False

    except smtplib.SMTPRecipientsRefused:
        log.error(f"Hard bounce — bad email address: {to_email}")
        mark_bounced(to_email)
        return False

    except smtplib.SMTPException as e:
        error_str = str(e).lower()
        if any(w in error_str for w in ["user unknown", "no such user", "invalid address",
                                         "address rejected", "does not exist"]):
            log.error(f"Bounce detected for {to_email}: {e}")
            mark_bounced(to_email)
        else:
            log.error(f"SMTP error sending to {to_email}: {e}")
        return False

    except Exception as e:
        log.error(f"Unexpected error sending to {to_email}: {e}")
        return False


# ── Batch sender ───────────────────────────────────────────────────────────────

def send_batch(leads_with_emails: list, market_key: str, dry_run: bool = False) -> list:
    delay       = EMAIL.get("stagger_max_secs", 180)
    sent_results = []
    sent_count   = 0

    market       = MARKETS[market_key]
    sender_email = market.get("gmail_user", "")

    if dry_run:
        # Dry run: don't read or write send history — caps are informational only
        inbox_sent_today  = 0
        global_sent_today = 0
    else:
        inbox_sent_today  = count_sent_today_by_inbox(sender_email)
        global_sent_today = count_sent_today_global()

    remaining_inbox  = max(0, PER_INBOX_CAP - inbox_sent_today)
    remaining_global = max(0, GLOBAL_DAILY_CAP - global_sent_today)
    effective_limit  = min(remaining_inbox, remaining_global)

    log.info(
        f"Starting batch | Market: {market_key} | Sender: {sender_email} | "
        f"Leads: {len(leads_with_emails)} | "
        f"Inbox {sender_email}: {inbox_sent_today}/{PER_INBOX_CAP} sent today, {remaining_inbox} remaining | "
        f"Global: {global_sent_today}/{GLOBAL_DAILY_CAP} sent today, {remaining_global} remaining | "
        f"Effective limit this batch: {effective_limit}"
    )

    if effective_limit <= 0 and not dry_run:
        if remaining_inbox <= 0:
            log.info(f"Per-inbox cap reached for {sender_email} ({inbox_sent_today}/{PER_INBOX_CAP}) — skipping batch")
        else:
            log.info(f"Global daily cap reached ({global_sent_today}/{GLOBAL_DAILY_CAP}) — skipping batch")
        return sent_results

    for item in leads_with_emails:
        if sent_count >= effective_limit:
            log.info(
                f"Cap reached — inbox: {inbox_sent_today + sent_count}/{PER_INBOX_CAP} | "
                f"global: {global_sent_today + sent_count}/{GLOBAL_DAILY_CAP}"
            )
            break

        listing     = item["listing"]
        offer       = item["offer"]
        email_draft = item["email"]
        to_email    = listing.get("agent_email")
        subject     = email_draft.get("subject", "Quick question")
        body        = email_draft.get("body", "")
        address     = listing.get("address", "unknown")

        if not to_email:
            log.warning(f"No email for {address} — skipping")
            continue

        pdf_path = None
        try:
            safe_addr    = address.replace("/", "-").replace(" ", "_")[:40]
            pdf_filename = f"{safe_addr}.pdf"
            pdf_out      = os.path.join("data/offers", pdf_filename)
            os.makedirs("data/offers", exist_ok=True)
            pdf_path = generate_offer_pdf(listing, offer, output_path=pdf_out)
            if pdf_path:
                log.info(f"PDF ready for {address}")
        except Exception as e:
            log.error(f"PDF error for {address}: {e} — sending without PDF")

        # ── Dry run: never touch Gmail credentials, SMTP, or send_email() ──────
        # (2026-07-02 fix) send_email() used to be called even in dry runs and
        # logged "Missing Gmail credentials" + returned False whenever the
        # workflow had no Gmail secrets configured (normal for a dry-run-only
        # test), which then counted a perfectly good ready lead as "Failed".
        # Dry run now short-circuits here — no credential lookup, no SMTP.
        if dry_run:
            success = True
            log.info(f"[DRY RUN] Would send to {to_email} | Subject: {subject} | PDF: {bool(pdf_path)}")
        else:
            success = send_email(
                market_key=market_key,
                to_email=to_email,
                subject=subject,
                body=body,
                pdf_path=pdf_path,
                dry_run=False,
                email_confidence=listing.get("email_confidence", ""),
            )

        if success:
            sent_count += 1
            sent_results.append({
                "listing":  listing,
                "email":    email_draft,
                "offer":    offer,
                "pdf_path": pdf_path,
                "sent_at":  datetime.now().isoformat(),
                "success":  True,
                "sender_email": sender_email,
            })
            if pdf_path and os.path.exists(pdf_path) and not dry_run:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

            # Dry runs never actually send, so never sleep the 60-204s
            # send stagger between "would send" lines (2026-07-02 fix) — that
            # delay is anti-spam pacing for REAL sends only.
            if not dry_run and sent_count < effective_limit:
                jitter     = random.uniform(-15, 30)
                sleep_time = max(60, delay + jitter)
                log.info(f"Waiting {round(sleep_time)}s before next send ({sent_count}/{effective_limit} this batch)...")
                time.sleep(sleep_time)
        else:
            sent_results.append({
                "listing":  listing,
                "email":    email_draft,
                "offer":    offer,
                "pdf_path": None,
                "sent_at":  datetime.now().isoformat(),
                "success":  False,
                "sender_email": sender_email,
            })

    successful = sum(1 for r in sent_results if r["success"])
    failed     = len(sent_results) - successful
    if dry_run:
        log.info(f"DRY RUN — would send {successful} verified emails; Gmail skipped.")
    else:
        log.info(f"Batch complete | Sent: {successful} | Failed: {failed} | Market: {market_key}")
    return sent_results
