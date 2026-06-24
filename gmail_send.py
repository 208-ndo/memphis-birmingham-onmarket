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

log = logging.getLogger(__name__)


def send_email(
    market_key: str,
    to_email: str,
    subject: str,
    body: str,
    pdf_path: str = None,
    dry_run: bool = False
) -> bool:
    """
    Send a single email via Gmail SMTP using App Password.
    Attaches offer PDF if provided.
    Returns True on success, False on failure.
    """
    market = MARKETS[market_key]
    gmail_user = market["gmail_user"]
    gmail_password = market["gmail_app_password"]

    if not gmail_user or not gmail_password:
        log.error(f"Missing Gmail credentials for market: {market_key}")
        return False

    if not to_email:
        log.warning("No agent email — skipping send")
        return False

    if dry_run:
        log.info(f"[DRY RUN] Would send to {to_email} | Subject: {subject} | PDF: {pdf_path}")
        return True

    try:
        msg = MIMEMultipart("mixed")
        msg["Subject"] = subject
        msg["From"] = gmail_user
        msg["To"] = to_email
        msg["Reply-To"] = gmail_user

        # Attach plain text body
        msg.attach(MIMEText(body, "plain"))

        # Attach PDF offer if it exists
        if pdf_path and os.path.exists(pdf_path):
            with open(pdf_path, "rb") as f:
                pdf_data = f.read()
            pdf_part = MIMEApplication(pdf_data, _subtype="pdf")
            pdf_filename = os.path.basename(pdf_path)
            pdf_part.add_header(
                "Content-Disposition",
                "attachment",
                filename=pdf_filename
            )
            msg.attach(pdf_part)
            log.info(f"PDF attached: {pdf_filename}")

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(gmail_user, gmail_password)
            server.sendmail(gmail_user, to_email, msg.as_string())

        log.info(f"SENT: {to_email} | {subject} | PDF: {'yes' if pdf_path else 'no'}")
        return True

    except smtplib.SMTPAuthenticationError:
        log.error(f"Gmail auth failed for {gmail_user} — check App Password")
        return False
    except smtplib.SMTPException as e:
        log.error(f"SMTP error sending to {to_email}: {e}")
        return False
    except Exception as e:
        log.error(f"Unexpected error sending to {to_email}: {e}")
        return False


def send_batch(leads_with_emails: list, market_key: str, dry_run: bool = False) -> list:
    """
    Send a batch of emails with staggered delays.
    Generates PDF offer for each property and attaches it.
    Respects daily limit per account.
    Returns list of successfully sent leads.
    """
    daily_limit = EMAIL["daily_limit_per_account"]
    delay = EMAIL["delay_between_sends_sec"]
    sent_results = []
    sent_count = 0

    log.info(f"Starting batch: {len(leads_with_emails)} leads | Market: {market_key} | Limit: {daily_limit}")

    for item in leads_with_emails:
        if sent_count >= daily_limit:
            log.info(f"Daily limit reached ({daily_limit}) — stopping")
            break

        listing = item["listing"]
        offer = item["offer"]
        email_draft = item["email"]
        to_email = listing.get("agent_email")
        subject = email_draft.get("subject", "Quick question")
        body = email_draft.get("body", "")

        if not to_email:
            log.warning(f"No email for {listing.get('address')} — skipping")
            continue

        # Generate PDF offer for this property
        pdf_path = None
        try:
            pdf_path = generate_offer_pdf(listing, offer, output_dir="data/offers")
            if pdf_path:
                log.info(f"PDF ready: {pdf_path}")
            else:
                log.warning(f"PDF generation failed for {listing.get('address')} — sending without")
        except Exception as e:
            log.error(f"PDF error for {listing.get('address')}: {e}")

        # Send email with PDF attached
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
                "email": email_draft,
                "offer": offer,
                "pdf_path": pdf_path,
                "sent_at": datetime.now().isoformat(),
                "success": True
            })

            # Clean up PDF after sending
            if pdf_path and os.path.exists(pdf_path) and not dry_run:
                try:
                    os.remove(pdf_path)
                except Exception:
                    pass

            # Staggered delay — randomized to look human
            if sent_count < daily_limit:
                jitter = random.uniform(-15, 30)
                sleep_time = max(60, delay + jitter)
                log.info(f"Waiting {round(sleep_time)}s before next send...")
                time.sleep(sleep_time)
        else:
            sent_results.append({
                "listing": listing,
                "email": email_draft,
                "offer": offer,
                "pdf_path": None,
                "sent_at": datetime.now().isoformat(),
                "success": False
            })

    log.info(f"Batch complete: {sent_count} sent out of {len(leads_with_emails)} attempted")
    return sent_results
