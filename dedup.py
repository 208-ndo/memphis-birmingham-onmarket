import json
import os
import logging
from datetime import datetime, timedelta
from config import DEDUP

log = logging.getLogger(__name__)

MAX_AGENT_CONTACTS_EVER = 3
SEND_HOUR_START = 8
SEND_HOUR_END   = 16

OPT_OUT_KEYWORDS = [
    "remove", "stop", "unsubscribe", "do not contact",
    "take me off", "don't contact", "not interested",
    "cease", "desist", "opt out", "optout"
]

# If FORCE_RUN=true, bypass time/weekend gates
FORCE_RUN = os.environ.get("FORCE_RUN", "").lower() == "true"


def load_log() -> dict:
    path = DEDUP["log_file"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        return {"properties": {}, "agents": {}, "opted_out": [], "bad_emails": []}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        if "opted_out"   not in data: data["opted_out"]   = []
        if "bad_emails"  not in data: data["bad_emails"]  = []
        return data
    except Exception:
        return {"properties": {}, "agents": {}, "opted_out": [], "bad_emails": []}


def save_log(data: dict):
    path = DEDUP["log_file"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def is_business_hours() -> bool:
    """Gate 1 — Time/day check. Bypassed if FORCE_RUN=true."""
    if FORCE_RUN:
        log.info("FORCE_RUN=true — bypassing business hours gate")
        return True
    try:
        import zoneinfo
        central    = zoneinfo.ZoneInfo("America/Chicago")
        now_central = datetime.now(central)
        weekday    = now_central.weekday()
        hour       = now_central.hour

        if weekday >= 5:
            log.warning("Weekend block — no sends on Saturday/Sunday")
            return False

        if hour < SEND_HOUR_START or hour >= SEND_HOUR_END:
            log.warning(
                f"Outside business hours ({now_central.strftime('%I:%M %p')} Central) "
                f"— sends only {SEND_HOUR_START}AM-{SEND_HOUR_END//12}PM Central"
            )
            return False

        return True
    except Exception as e:
        log.warning(f"Timezone check failed ({e}) — allowing send")
        return True


def is_opted_out(agent_email: str) -> bool:
    if not agent_email:
        return False
    log_data   = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower in [e.lower() for e in log_data.get("opted_out", [])]:
        log.info(f"SKIP (opted out): {agent_email}")
        return True
    return False


def is_bad_email(agent_email: str) -> bool:
    if not agent_email:
        return False
    log_data   = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower in [e.lower() for e in log_data.get("bad_emails", [])]:
        log.info(f"SKIP (bounced email): {agent_email}")
        return True
    return False


def is_duplicate_property(address: str) -> bool:
    log_data    = load_log()
    address_key = address.lower().strip()
    if address_key in log_data["properties"]:
        log.info(f"SKIP (already emailed): {address}")
        return True
    return False


def is_agent_cooldown(agent_email: str) -> bool:
    if not agent_email:
        return False
    log_data  = load_log()
    agent_key = agent_email.lower().strip()
    if agent_key in log_data["agents"]:
        last_sent = datetime.fromisoformat(log_data["agents"][agent_key]["last_sent"])
        if datetime.now() - last_sent < timedelta(days=7):
            log.info(f"SKIP (7-day cooldown): {agent_email}")
            return True
    return False


def is_agent_maxed_out(agent_email: str) -> bool:
    if not agent_email:
        return False
    log_data  = load_log()
    agent_key = agent_email.lower().strip()
    if agent_key in log_data["agents"]:
        total = log_data["agents"][agent_key].get("total_contacted", 0)
        if total >= MAX_AGENT_CONTACTS_EVER:
            log.info(f"SKIP (lifetime cap — {total}/{MAX_AGENT_CONTACTS_EVER}): {agent_email}")
            return True
    return False


def should_send(listing: dict, check_hours: bool = True) -> bool:
    address     = listing.get("address", "")
    agent_email = listing.get("agent_email", "")

    if check_hours and not is_business_hours():
        return False
    if is_opted_out(agent_email):
        return False
    if is_bad_email(agent_email):
        return False
    if is_duplicate_property(address):
        return False
    if is_agent_cooldown(agent_email):
        return False
    if is_agent_maxed_out(agent_email):
        return False

    return True


def mark_sent(listing: dict, email_sent: dict):
    log_data = load_log()
    now      = datetime.now().isoformat()

    address_key = listing.get("address", "").lower().strip()
    agent_email = listing.get("agent_email", "").lower().strip()

    log_data["properties"][address_key] = {
        "address":        listing.get("address"),
        "market":         listing.get("market"),
        "agent_email":    agent_email,
        "list_price":     listing.get("list_price"),
        "days_on_market": listing.get("days_on_market"),
        "sent_at":        now,
        "subject":        email_sent.get("subject"),
        "offer_type":     listing.get("offer", {}).get("offer_type"),
        "zillow_url":     listing.get("url"),
    }

    if agent_email:
        if agent_email not in log_data["agents"]:
            log_data["agents"][agent_email] = {
                "total_contacted": 0,
                "properties":      [],
                "first_contact":   now,
            }
        log_data["agents"][agent_email]["last_sent"]        = now
        log_data["agents"][agent_email]["total_contacted"] += 1
        log_data["agents"][agent_email]["properties"].append(address_key)

    save_log(log_data)
    log.info(
        f"Logged: {listing.get('address')} | Agent: {agent_email} | "
        f"Total: {log_data['agents'].get(agent_email, {}).get('total_contacted', 1)}/{MAX_AGENT_CONTACTS_EVER}"
    )


def mark_opted_out(agent_email: str):
    if not agent_email:
        return
    log_data    = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower not in log_data["opted_out"]:
        log_data["opted_out"].append(email_lower)
        save_log(log_data)
    log.info(f"Opted out permanently: {agent_email}")


def mark_bounced(agent_email: str):
    if not agent_email:
        return
    log_data    = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower not in log_data["bad_emails"]:
        log_data["bad_emails"].append(email_lower)
        save_log(log_data)
    log.info(f"Marked as bounced: {agent_email}")


def get_stats() -> dict:
    log_data     = load_log()
    agents       = log_data.get("agents", {})
    maxed_agents = sum(1 for a in agents.values() if a.get("total_contacted", 0) >= MAX_AGENT_CONTACTS_EVER)
    return {
        "total_properties_emailed": len(log_data["properties"]),
        "total_agents_contacted":   len(agents),
        "opted_out_count":          len(log_data.get("opted_out", [])),
        "bounced_email_count":      len(log_data.get("bad_emails", [])),
        "agents_at_lifetime_cap":   maxed_agents,
    }
