import json
import os
import logging
from datetime import datetime, timedelta
from config import DEDUP

log = logging.getLogger(__name__)

# Max times we ever contact the same agent across all properties
MAX_AGENT_CONTACTS_EVER = 3

# Business hours gate — only send between these hours Central Time
SEND_HOUR_START = 8   # 8 AM Central
SEND_HOUR_END = 16    # 4 PM Central

# Opt-out keywords — if agent replies with these, block permanently
OPT_OUT_KEYWORDS = [
    "remove", "stop", "unsubscribe", "do not contact",
    "take me off", "don't contact", "not interested",
    "cease", "desist", "opt out", "optout"
]


def load_log() -> dict:
    """Load the sent leads dedup log."""
    path = DEDUP["log_file"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        return {
            "properties": {},
            "agents": {},
            "opted_out": [],
            "bad_emails": [],
        }
    try:
        with open(path, "r") as f:
            data = json.load(f)
            # Ensure all keys exist for older log files
            if "opted_out" not in data:
                data["opted_out"] = []
            if "bad_emails" not in data:
                data["bad_emails"] = []
            return data
    except Exception:
        return {
            "properties": {},
            "agents": {},
            "opted_out": [],
            "bad_emails": [],
        }


def save_log(data: dict):
    """Save the dedup log."""
    path = DEDUP["log_file"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def is_business_hours() -> bool:
    """
    Gate 1 — Time of day check.
    Only send emails between 8 AM and 4 PM Central Time Mon-Fri.
    Protects against manual runs firing at bad times.
    """
    from datetime import timezone
    import zoneinfo
    try:
        central = zoneinfo.ZoneInfo("America/Chicago")
        now_central = datetime.now(central)
        weekday = now_central.weekday()  # 0=Mon 6=Sun
        hour = now_central.hour

        # Weekend block
        if weekday >= 5:
            log.warning(f"Weekend block — no sends on Saturday/Sunday")
            return False

        # Business hours block
        if hour < SEND_HOUR_START or hour >= SEND_HOUR_END:
            log.warning(
                f"Outside business hours ({now_central.strftime('%I:%M %p')} Central) "
                f"— sends only between {SEND_HOUR_START}AM-{SEND_HOUR_END//12}PM Central"
            )
            return False

        return True
    except Exception as e:
        log.warning(f"Timezone check failed ({e}) — allowing send")
        return True


def is_opted_out(agent_email: str) -> bool:
    """
    Gate 2 — Opt-out check.
    If agent has ever replied with a stop/remove request → permanently blocked.
    """
    if not agent_email:
        return False
    log_data = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower in [e.lower() for e in log_data.get("opted_out", [])]:
        log.info(f"SKIP (opted out): {agent_email}")
        return True
    return False


def is_bad_email(agent_email: str) -> bool:
    """
    Gate 3 — Bounced email check.
    If email has previously bounced → never retry.
    """
    if not agent_email:
        return False
    log_data = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower in [e.lower() for e in log_data.get("bad_emails", [])]:
        log.info(f"SKIP (bounced email): {agent_email}")
        return True
    return False


def is_duplicate_property(address: str) -> bool:
    """
    Gate 4 — Property dedup.
    Once emailed — never email again permanently.
    """
    log_data = load_log()
    address_key = address.lower().strip()
    if address_key in log_data["properties"]:
        log.info(f"SKIP (already emailed): {address}")
        return True
    return False


def is_agent_cooldown(agent_email: str) -> bool:
    """
    Gate 5 — Agent 7-day cooldown.
    Don't contact same agent more than once per week.
    """
    if not agent_email:
        return False
    log_data = load_log()
    agent_key = agent_email.lower().strip()
    if agent_key in log_data["agents"]:
        last_sent = datetime.fromisoformat(
            log_data["agents"][agent_key]["last_sent"]
        )
        if datetime.now() - last_sent < timedelta(days=7):
            log.info(f"SKIP (7-day cooldown): {agent_email}")
            return True
    return False


def is_agent_maxed_out(agent_email: str) -> bool:
    """
    Gate 6 — Lifetime agent contact cap.
    Never contact same agent more than 3 times total ever.
    Prevents us from becoming spam to any single agent.
    """
    if not agent_email:
        return False
    log_data = load_log()
    agent_key = agent_email.lower().strip()
    if agent_key in log_data["agents"]:
        total = log_data["agents"][agent_key].get("total_contacted", 0)
        if total >= MAX_AGENT_CONTACTS_EVER:
            log.info(
                f"SKIP (lifetime cap — {total}/{MAX_AGENT_CONTACTS_EVER}): "
                f"{agent_email}"
            )
            return True
    return False


def should_send(listing: dict, check_hours: bool = True) -> bool:
    """
    Master dedup check — runs all 6 gates in order.
    Returns True only if listing passes every single gate.

    Gates:
    1. Business hours (8AM-4PM Central, Mon-Fri)
    2. Agent not opted out
    3. Agent email not bounced
    4. Property address never emailed before
    5. Agent not in 7-day cooldown
    6. Agent not at lifetime contact cap (3 max)
    """
    address = listing.get("address", "")
    agent_email = listing.get("agent_email", "")

    # Gate 1 — Business hours (optional for batch pre-filtering)
    if check_hours and not is_business_hours():
        return False

    # Gate 2 — Opt-out
    if is_opted_out(agent_email):
        return False

    # Gate 3 — Bounced email
    if is_bad_email(agent_email):
        return False

    # Gate 4 — Duplicate property
    if is_duplicate_property(address):
        return False

    # Gate 5 — Agent cooldown
    if is_agent_cooldown(agent_email):
        return False

    # Gate 6 — Lifetime cap
    if is_agent_maxed_out(agent_email):
        return False

    return True


def mark_sent(listing: dict, email_sent: dict):
    """
    Log this property and agent as contacted.
    Called immediately after successful send.
    """
    log_data = load_log()
    now = datetime.now().isoformat()

    address_key = listing.get("address", "").lower().strip()
    agent_email = listing.get("agent_email", "").lower().strip()

    # Log property — permanent
    log_data["properties"][address_key] = {
        "address": listing.get("address"),
        "market": listing.get("market"),
        "agent_email": agent_email,
        "list_price": listing.get("list_price"),
        "days_on_market": listing.get("days_on_market"),
        "score": listing.get("score"),
        "sent_at": now,
        "subject": email_sent.get("subject"),
        "offer_type": listing.get("offer", {}).get("offer_type"),
        "zillow_url": listing.get("url"),
    }

    # Log agent — cooldown + lifetime counter
    if agent_email:
        if agent_email not in log_data["agents"]:
            log_data["agents"][agent_email] = {
                "total_contacted": 0,
                "properties": [],
                "first_contact": now,
            }
        log_data["agents"][agent_email]["last_sent"] = now
        log_data["agents"][agent_email]["total_contacted"] += 1
        log_data["agents"][agent_email]["properties"].append(address_key)

    save_log(log_data)
    log.info(
        f"Logged: {listing.get('address')} | "
        f"Agent: {agent_email} | "
        f"Total agent contacts: "
        f"{log_data['agents'].get(agent_email, {}).get('total_contacted', 1)}"
        f"/{MAX_AGENT_CONTACTS_EVER}"
    )


def mark_opted_out(agent_email: str):
    """
    Permanently block an agent who replied with a stop/remove request.
    Call this when processing inbox replies.
    """
    if not agent_email:
        return
    log_data = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower not in log_data["opted_out"]:
        log_data["opted_out"].append(email_lower)
        save_log(log_data)
        log.info(f"Opted out permanently: {agent_email}")


def mark_bounced(agent_email: str):
    """
    Mark an email address as bad after a bounce.
    Call this when Gmail SMTP throws a bounce error.
    """
    if not agent_email:
        return
    log_data = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower not in log_data["bad_emails"]:
        log_data["bad_emails"].append(email_lower)
        save_log(log_data)
        log.info(f"Marked as bounced: {agent_email}")


def get_stats() -> dict:
    """Return full stats on the dedup log."""
    log_data = load_log()
    agents = log_data.get("agents", {})

    # Count agents at lifetime cap
    maxed_agents = sum(
        1 for a in agents.values()
        if a.get("total_contacted", 0) >= MAX_AGENT_CONTACTS_EVER
    )

    return {
        "total_properties_emailed": len(log_data["properties"]),
        "total_agents_contacted": len(agents),
        "opted_out_count": len(log_data.get("opted_out", [])),
        "bounced_email_count": len(log_data.get("bad_emails", [])),
        "agents_at_lifetime_cap": maxed_agents,
    }
