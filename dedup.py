import json
import os
import logging
from datetime import datetime, timedelta
from config import DEDUP

log = logging.getLogger(__name__)


def load_log() -> dict:
    """Load the sent leads dedup log."""
    path = DEDUP["log_file"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        return {"properties": {}, "agents": {}}
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {"properties": {}, "agents": {}}


def save_log(data: dict):
    """Save the dedup log."""
    path = DEDUP["log_file"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def is_duplicate_property(address: str) -> bool:
    """
    Check if we've already emailed this property address.
    Once emailed — never email again.
    """
    log_data = load_log()
    address_key = address.lower().strip()
    if address_key in log_data["properties"]:
        log.info(f"SKIP (already emailed): {address}")
        return True
    return False


def is_agent_cooldown(agent_email: str) -> bool:
    """
    Check if we've emailed this agent in the last 7 days.
    Prevents hammering same agent across different properties.
    """
    if not agent_email:
        return False
    log_data = load_log()
    agent_key = agent_email.lower().strip()
    if agent_key in log_data["agents"]:
        last_sent = datetime.fromisoformat(log_data["agents"][agent_key]["last_sent"])
        cooldown_days = 7
        if datetime.now() - last_sent < timedelta(days=cooldown_days):
            log.info(f"SKIP (agent cooldown {cooldown_days}d): {agent_email}")
            return True
    return False


def should_send(listing: dict) -> bool:
    """
    Master dedup check. Returns True if we should send to this listing.
    Checks:
    1. Property address never emailed before
    2. Agent not in 7-day cooldown
    """
    address = listing.get("address", "")
    agent_email = listing.get("agent_email", "")

    if is_duplicate_property(address):
        return False
    if is_agent_cooldown(agent_email):
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

    # Log property — permanent, never email again
    log_data["properties"][address_key] = {
        "address": listing.get("address"),
        "market": listing.get("market"),
        "agent_email": agent_email,
        "list_price": listing.get("list_price"),
        "days_on_market": listing.get("days_on_market"),
        "score": listing.get("score"),
        "sent_at": now,
        "subject": email_sent.get("subject"),
        "zillow_url": listing.get("url"),
    }

    # Log agent — 7 day cooldown
    if agent_email:
        if agent_email not in log_data["agents"]:
            log_data["agents"][agent_email] = {"total_contacted": 0, "properties": []}
        log_data["agents"][agent_email]["last_sent"] = now
        log_data["agents"][agent_email]["total_contacted"] += 1
        log_data["agents"][agent_email]["properties"].append(address_key)

    save_log(log_data)
    log.info(f"Logged: {listing.get('address')} | Agent: {agent_email}")


def get_stats() -> dict:
    """Return quick stats on the dedup log."""
    log_data = load_log()
    return {
        "total_properties_emailed": len(log_data["properties"]),
        "total_agents_contacted": len(log_data["agents"]),
    }
