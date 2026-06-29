import json
import os
import re
import logging
from datetime import datetime, timedelta
from config import DEDUP

log = logging.getLogger(__name__)

MAX_AGENT_CONTACTS_EVER  = 3
AGENT_WINDOW_DAYS        = 35
AGENT_WINDOW_CAP         = 2
SEND_HOUR_START          = 8
SEND_HOUR_END            = 16

OPT_OUT_KEYWORDS = [
    "remove", "stop", "unsubscribe", "do not contact",
    "take me off", "don't contact", "not interested",
    "cease", "desist", "opt out", "optout"
]

# Company name indicators — if any match, name is NOT a person
COMPANY_INDICATORS = [
    "llc", "inc", "corp", "realty", "realtor", "realtors",
    "properties", "group", "associates", "keller", "century",
    "re/max", "remax", "coldwell", "exit", "trelora", "team",
    "partners", "solutions", "investments", "ventures", "investors",
    "brokerage", "homes", "real estate", "agency", "services",
    "management", "brokers", "co.", "company",
]

FORCE_RUN = os.environ.get("FORCE_RUN", "").lower() == "true"


# ── File I/O ───────────────────────────────────────────────────────────────────

def load_log() -> dict:
    path = DEDUP["log_file"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        return {"properties": {}, "agents": {}, "opted_out": [], "bad_emails": []}
    try:
        with open(path, "r") as f:
            data = json.load(f)
        for key in ("opted_out", "bad_emails"):
            if key not in data:
                data[key] = []
        return data
    except Exception:
        return {"properties": {}, "agents": {}, "opted_out": [], "bad_emails": []}


def save_log(data: dict):
    path = DEDUP["log_file"]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


# ── Property key helpers ───────────────────────────────────────────────────────

def _zpid_from_url(url: str) -> str:
    """Extract zpid from a Zillow URL like .../42157772_zpid/"""
    if not url:
        return ""
    m = re.search(r"(\d+)_zpid", url)
    return m.group(1) if m else ""


def _property_keys(listing: dict) -> list:
    """
    Return a priority-ordered list of stable keys for this property.
    First key is used for new writes. All keys are checked on lookup.
    """
    keys = []

    zpid = str(listing.get("zpid") or "").strip()
    if zpid and zpid != "0":
        keys.append(f"zpid:{zpid}")

    url = listing.get("url") or listing.get("zillow_url") or ""
    zpid_from_url = _zpid_from_url(url)
    if zpid_from_url and f"zpid:{zpid_from_url}" not in keys:
        keys.append(f"zpid:{zpid_from_url}")

    addr   = listing.get("address", "").lower().strip()
    city   = listing.get("city", "").lower().strip()
    state  = listing.get("state", "").lower().strip()
    zipcode = str(listing.get("zip") or "").strip()
    if addr:
        full = ", ".join(p for p in [addr, city, state, zipcode] if p)
        keys.append(full)
        # Also bare address for backward compat with old records like "2276 redwood ave..."
        keys.append(addr)

    return keys


def _write_property_key(listing: dict) -> str:
    """Return the single key to use when writing a new property record."""
    keys = _property_keys(listing)
    return keys[0] if keys else listing.get("address", "").lower().strip()


# ── Agent person key helpers ───────────────────────────────────────────────────

def _is_company_name(name: str) -> bool:
    """Return True if the name looks like a brokerage/company, not a person."""
    if not name:
        return True
    name_lower = name.lower()
    return any(ind in name_lower for ind in COMPANY_INDICATORS)


def _normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.lower().strip())


def agent_person_key(listing: dict) -> tuple[str, str]:
    """
    Return (agent_key, confidence) for use in the 35-day window cap.
    confidence: 'high' (person name), 'medium' (personal email domain), 'low' (company fallback)
    """
    name  = (listing.get("agent_name") or "").strip()
    email = (listing.get("agent_email") or "").lower().strip()

    if name and not _is_company_name(name):
        return _normalize_name(name), "high"

    if email:
        return email, "medium"

    if name:
        log.warning(f"Agent key falling back to company name (low confidence): {name!r}")
        return _normalize_name(name), "low"

    return "unknown_agent", "low"


# ── Gate: business hours ───────────────────────────────────────────────────────

def is_business_hours() -> bool:
    if FORCE_RUN:
        log.info("FORCE_RUN=true — bypassing business hours gate")
        return True
    try:
        import zoneinfo
        central     = zoneinfo.ZoneInfo("America/Chicago")
        now_central = datetime.now(central)
        weekday     = now_central.weekday()
        hour        = now_central.hour

        if weekday >= 5:
            log.warning("Weekend block — no sends on Saturday/Sunday")
            return False

        if hour < SEND_HOUR_START or hour >= SEND_HOUR_END:
            log.warning(
                f"Outside business hours ({now_central.strftime('%I:%M %p')} Central) "
                f"— sends only {SEND_HOUR_START}AM-{SEND_HOUR_END // 12}PM Central"
            )
            return False

        return True
    except Exception as e:
        log.warning(f"Timezone check failed ({e}) — allowing send")
        return True


# ── Gate: opt-out ─────────────────────────────────────────────────────────────

def is_opted_out(agent_email: str) -> bool:
    if not agent_email:
        return False
    log_data    = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower in [e.lower() for e in log_data.get("opted_out", [])]:
        log.info(f"SKIP (opted out): {agent_email}")
        return True
    return False


# ── Gate: bounce ──────────────────────────────────────────────────────────────

def is_bad_email(agent_email: str) -> bool:
    if not agent_email:
        return False
    log_data    = load_log()
    email_lower = agent_email.lower().strip()
    if email_lower in [e.lower() for e in log_data.get("bad_emails", [])]:
        log.info(f"SKIP (bounced email): {agent_email}")
        return True
    return False


# ── Gate: property already contacted ─────────────────────────────────────────

def is_duplicate_property(listing: dict) -> bool:
    log_data = load_log()
    props    = log_data.get("properties", {})

    for key in _property_keys(listing):
        if key in props:
            rec      = props[key]
            last     = rec.get("sent_at", "")[:10]
            address  = rec.get("address") or listing.get("address", "")
            log.info(f"SKIP (property already contacted): {address} | last_sent={last}")
            return True

    return False


# ── Gate: 7-day agent cooldown (kept for backward compat — superseded by window cap) ──

def is_agent_cooldown(agent_email: str) -> bool:
    if not agent_email:
        return False
    log_data  = load_log()
    agent_key = agent_email.lower().strip()
    if agent_key in log_data.get("agents", {}):
        last_sent = datetime.fromisoformat(
            log_data["agents"][agent_key]["last_sent"]
        )
        if datetime.now() - last_sent < timedelta(days=7):
            log.info(f"SKIP (7-day cooldown): {agent_email}")
            return True
    return False


# ── Gate: 35-day / 2-listing rolling window cap ───────────────────────────────

def is_agent_window_maxed(listing: dict) -> bool:
    """
    Skip if the agent person has already received offers on 2+ different
    properties in the last 35 days.
    """
    log_data = load_log()
    agents   = log_data.get("agents", {})

    person_key, confidence = agent_person_key(listing)
    agent_email = (listing.get("agent_email") or "").lower().strip()
    agent_name  = (listing.get("agent_name") or "").strip()
    cutoff      = datetime.now() - timedelta(days=AGENT_WINDOW_DAYS)

    # Count sends in window across ALL agent records that share this person_key
    window_sends = []
    for email_key, rec in agents.items():
        if rec.get("person_key") == person_key:
            for entry in rec.get("sends_in_window", []):
                try:
                    sent_dt = datetime.fromisoformat(entry["sent_at"])
                    if sent_dt >= cutoff:
                        window_sends.append(entry)
                except Exception:
                    pass

    if len(window_sends) >= AGENT_WINDOW_CAP:
        log.info(
            f"SKIP (agent cap {AGENT_WINDOW_CAP}/{AGENT_WINDOW_DAYS} days): "
            f"{agent_name or 'unknown'} | {agent_email} | "
            f"already_sent={len(window_sends)} | window={AGENT_WINDOW_DAYS}d | "
            f"confidence={confidence}"
        )
        return True

    return False


# ── Gate: lifetime cap ────────────────────────────────────────────────────────

def is_agent_maxed_out(agent_email: str) -> bool:
    if not agent_email:
        return False
    log_data  = load_log()
    agent_key = agent_email.lower().strip()
    if agent_key in log_data.get("agents", {}):
        total = log_data["agents"][agent_key].get("total_contacted", 0)
        if total >= MAX_AGENT_CONTACTS_EVER:
            log.info(
                f"SKIP (lifetime cap — {total}/{MAX_AGENT_CONTACTS_EVER}): {agent_email}"
            )
            return True
    return False


# ── Combined gate ─────────────────────────────────────────────────────────────

def should_send(listing: dict, check_hours: bool = True) -> bool:
    address     = listing.get("address", "")
    agent_email = listing.get("agent_email", "")

    if check_hours and not is_business_hours():
        return False
    if is_opted_out(agent_email):
        return False
    if is_bad_email(agent_email):
        return False
    if is_duplicate_property(listing):
        return False
    if is_agent_cooldown(agent_email):
        return False
    if is_agent_window_maxed(listing):
        return False
    if is_agent_maxed_out(agent_email):
        return False

    return True


# ── Write: mark sent (only on confirmed live send success) ────────────────────

def mark_sent(listing: dict, email_sent: dict):
    """
    Write property and agent history to dedup_log.json.
    MUST only be called after a confirmed live Gmail send succeeds.
    Do NOT call during dry runs.
    """
    log_data = load_log()
    now      = datetime.now().isoformat()

    # ── Property record ────────────────────────────────────────────────────────
    prop_key    = _write_property_key(listing)
    agent_email = (listing.get("agent_email") or "").lower().strip()
    agent_name  = (listing.get("agent_name") or "").strip()
    brokerage   = (listing.get("brokerName") or listing.get("brokerage") or "").strip()
    zpid        = str(listing.get("zpid") or "").strip()
    url         = listing.get("url") or listing.get("zillow_url") or ""
    offer       = listing.get("offer") or {}

    # Normalize address for backward compat
    addr_key = (listing.get("address") or "").lower().strip()

    log_data["properties"][prop_key] = {
        "address":      listing.get("address"),
        "address_key":  addr_key,
        "property_key": prop_key,
        "zpid":         zpid,
        "zillow_url":   url,
        "market":       listing.get("market"),
        "agent_name":   agent_name,
        "agent_email":  agent_email,
        "brokerage":    brokerage,
        "list_price":   listing.get("list_price") or listing.get("price"),
        "days_on_market": listing.get("days_on_market"),
        "offer_type":   offer.get("offer_type"),
        "email_subject": email_sent.get("subject"),
        "sent_at":      now,
        "status":       "sent",
    }

    # Also write address key for backward compat lookup on old records
    if addr_key and addr_key != prop_key and addr_key not in log_data["properties"]:
        log_data["properties"][addr_key] = log_data["properties"][prop_key]

    # ── Agent record ───────────────────────────────────────────────────────────
    person_key, confidence = agent_person_key(listing)
    agent_rec_key = agent_email if agent_email else person_key

    if agent_rec_key not in log_data["agents"]:
        log_data["agents"][agent_rec_key] = {
            "person_key":        person_key,
            "person_confidence": confidence,
            "agent_name":        agent_name,
            "brokerage":         brokerage,
            "total_contacted":   0,
            "sends_in_window":   [],
            "properties":        [],
            "first_contact":     now,
        }

    rec = log_data["agents"][agent_rec_key]
    rec["last_sent"]        = now
    rec["total_contacted"]  = rec.get("total_contacted", 0) + 1
    rec["person_key"]       = person_key
    rec["person_confidence"] = confidence
    if "sends_in_window" not in rec:
        rec["sends_in_window"] = []
    rec["sends_in_window"].append({
        "address":  listing.get("address"),
        "prop_key": prop_key,
        "sent_at":  now,
    })
    if prop_key not in rec.get("properties", []):
        rec.setdefault("properties", []).append(prop_key)

    save_log(log_data)
    log.info(
        f"Logged: {listing.get('address')} | Agent: {agent_rec_key} | "
        f"Total: {rec['total_contacted']}/{MAX_AGENT_CONTACTS_EVER} | "
        f"Window: {len([s for s in rec['sends_in_window'] if (datetime.now() - datetime.fromisoformat(s['sent_at'])).days < AGENT_WINDOW_DAYS])}/{AGENT_WINDOW_CAP} in {AGENT_WINDOW_DAYS}d"
    )


# ── Write: opt-out / bounce ───────────────────────────────────────────────────

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


# ── Stats ─────────────────────────────────────────────────────────────────────

def get_stats() -> dict:
    log_data     = load_log()
    agents       = log_data.get("agents", {})
    maxed_agents = sum(
        1 for a in agents.values()
        if a.get("total_contacted", 0) >= MAX_AGENT_CONTACTS_EVER
    )
    return {
        "total_properties_emailed": len(log_data["properties"]),
        "total_agents_contacted":   len(agents),
        "opted_out_count":          len(log_data.get("opted_out", [])),
        "bounced_email_count":      len(log_data.get("bad_emails", [])),
        "agents_at_lifetime_cap":   maxed_agents,
    }
