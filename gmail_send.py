import smtplib
import time
import random
import logging
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from datetime import datetime
from config import MARKETS, EMAIL
from generate_offer_pdf import generate_offer_pdf
from dedup import mark_bounced

log = logging.getLogger(__name__)


def send_email(
    market_key: str,
    to_email: str,
    subject: str,
    body: str,
    pdf_path: str = None,
    dry_run: bool = False
) -> bool:
    market          = MARKETS[market_key]
    gmail_user      = market["gmail_user"]
    gmail_password  = market["gmail_app_password"]

    if not gmail_user or not gmail_password:
        log.error(f"Missing Gmail credentials for market: {market_key}")
        return False

    if not to_email:
        log.warning("No agent email — skipping send")
        return False

    if dry_run:
        log.info(f"[DRY RUN] Would send to {to_email} | Subject: {subject} | PDF: {bool(pdf_path)}")
        return True

    try:
        msg = MIMEMultipart("mixed")
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
        if any(w in error_str for w in ["user unknown","no such user","invalid address","address rejected","does not exist"]):
            log.error(f"Bounce detected for {to_email}: {e}")
            mark_bounced(to_email)
        else:
            log.error(f"SMTP error sending to {to_email}: {e}")
        return False

    except Exception as e:
        log.error(f"Unexpected error sending to {to_email}: {e}")
        return False


def send_batch(leads_with_emails: list, market_key: str, dry_run: bool = False) -> list:
    # FIX: use correct key from config.py
    daily_limit = EMAIL["daily_limit"]
    delay       = EMAIL.get("stagger_max_secs", 180)
    sent_results = []
    sent_count   = 0

    log.info(f"Starting batch | Market: {market_key} | Leads: {len(leads_with_emails)} | Limit: {daily_limit}/day")

    for item in leads_with_emails:
        if sent_count >= daily_limit:
            log.info(f"Daily limit reached ({daily_limit}) — stopping batch")
            break

        listing      = item["listing"]
        offer        = item["offer"]
        email_draft  = item["email"]
        to_email     = listing.get("agent_email")
        subject      = email_draft.get("subject", "Quick question")
        body         = email_draft.get("body", "")
        address      = listing.get("address", "unknown")

        if not to_email:
            log.warning(f"No email for {address} — skipping")
            continue

        pdf_path = None
        try:
            safe_addr = address.replace("/", "-").replace(" ", "_")[:40]
            pdf_filename = f"{safe_addr}.pdf"
            pdf_out = os.path.join("data/offers", pdf_filename)
            os.makedirs("data/offers", exist_ok=True)
            pdf_path = generate_offer_pdf(listing, offer, output_path=pdf_out)
            if pdf_path:
                log.info(f"PDF ready for {address}")
        except Exception as e:
            log.error(f"PDF error for {address}: {e} — sending without PDF")

        success = send_email(
            market_key=market_key,
            to_email=to_email,
            subject=subject,
            body=body,
            pdf_path=pdf_path,
            dry_run=dry_run
        )

        if success:
            sent_count += 1
            sent_results.append({
                "listing": listing,
                "email":   email_draft,
                "offer":   offer,
                "pdf_path": pdf_path,
                "sent_at": datetime.now().isoformat(),
                "success": True,
            })
            if pdf_path and os.path.exists(pdf_path) and not dry_run:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

            if sent_count < daily_limit:
                jitter     = random.uniform(-15, 30)
                sleep_time = max(60, delay + jitter)
                log.info(f"Waiting {round(sleep_time)}s before next send ({sent_count}/{daily_limit} sent)...")
                time.sleep(sleep_time)
        else:
            sent_results.append({
                "listing": listing,
                "email":   email_draft,
                "offer":   offer,
                "pdf_path": None,
                "sent_at": datetime.now().isoformat(),
                "success": False,
            })

    successful = sum(1 for r in sent_results if r["success"])
    failed     = len(sent_results) - successful
    log.info(f"Batch complete | Sent: {successful} | Failed: {failed} | Market: {market_key}")
    return sent_results
