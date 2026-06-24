import requests
import logging
import random
from datetime import datetime
from config import GHL, MARKETS

log = logging.getLogger(__name__)

GHL_BASE_URL = "https://rest.gohighlevel.com/v1"

def get_headers():
    return {
        "Authorization": f"Bearer {GHL['api_key']}",
        "Content-Type": "application/json",
        "Version": "2021-04-15"
    }

def find_contact_by_email(email: str) -> str | None:
    """Check if contact already exists in GHL by email."""
    try:
        resp = requests.get(
            f"{GHL_BASE_URL}/contacts/",
            headers=get_headers(),
            params={"email": email, "locationId": GHL["location_id"]},
            timeout=10
        )
        if resp.status_code == 200:
            contacts = resp.json().get("contacts", [])
            if contacts:
                return contacts[0]["id"]
    except Exception as e:
        log.error(f"GHL contact lookup error: {e}")
    return None

def create_contact(listing: dict, offer: dict, market_key: str) -> str | None:
    """
    Create a new contact in GHL for the listing agent.
    Checks for existing contact first — never creates duplicates.
    Returns contact ID on success.
    """
    agent_email  = listing.get("agent_email", "")
    agent_name   = listing.get("listing_agent", "Unknown Agent")
    agent_phone  = listing.get("agent_phone", "")
    address      = listing.get("address", "")
    city         = listing.get("city", "")
    state        = listing.get("state", "")

    if agent_email:
        existing_id = find_contact_by_email(agent_email)
        if existing_id:
            log.info(f"Contact exists in GHL: {agent_email} ({existing_id})")
            return existing_id

    payload = {
        "locationId": GHL["location_id"],
        "firstName": agent_name.split()[0] if agent_name else "Agent",
        "lastName": " ".join(agent_name.split()[1:]) if len(agent_name.split()) > 1 else "",
        "email": agent_email,
        "phone": agent_phone,
        "source": "On-Market Wholesale Pipeline",
        "tags": [
            f"market-{market_key}",
            "on-market",
            "listing-agent",
            "offer-sent",
        ],
        "customField": {
            "property_address":     address,
            "property_city":        f"{city}, {state}",
            "list_price":           f"${listing.get('list_price', 0):,}",
            "days_on_market":       str(listing.get("days_on_market", 0)),
            "distress_score":       str(listing.get("score", 0)),
            "owner_finance_offer":  f"${offer.get('owner_finance_offer', 0):,}",
            "cash_offer":           f"${offer.get('cash_offer', 0):,}",
            "your_fee_estimate":    f"${offer.get('your_fee_estimate', 0):,}",
            "offer_type":           offer.get("offer_type", ""),
            "pitch_holds":          str(offer.get("pitch_holds", False)),
            "zillow_url":           listing.get("url", ""),
            "pipeline_date":        datetime.now().strftime("%Y-%m-%d"),
        }
    }

    try:
        resp = requests.post(
            f"{GHL_BASE_URL}/contacts/",
            headers=get_headers(),
            json=payload,
            timeout=10
        )
        if resp.status_code in [200, 201]:
            contact_id = resp.json().get("contact", {}).get("id")
            log.info(f"GHL contact created: {agent_email} | ID: {contact_id}")
            return contact_id
        else:
            log.error(f"GHL contact creation failed: {resp.status_code} {resp.text}")
    except Exception as e:
        log.error(f"GHL create contact error: {e}")
    return None

def send_sms(contact_id: str, listing: dict, offer: dict, market_key: str) -> bool:
    """
    Send SMS to listing agent via GHL immediately after contact creation.
    NOTE: The 5-minute delay is handled by GHL's own workflow automation
    (Day 0 trigger in the Agent Offer Follow-Up workflow), NOT here.
    This fires the initial SMS — GHL handles the follow-up sequence.
    """
    market      = MARKETS[market_key]
    from_number = market.get("ghl_phone_number")
    agent_name  = listing.get("listing_agent", "")
    first_name  = agent_name.split()[0] if agent_name else "there"
    address     = listing.get("address", "")

    # 4 rotating casual text variations — same as before
    texts = [
        f"Hey {first_name}, just sent you an email about {address} — still available? What's the deal with it?",
        f"Hey {first_name} — offer sent on {address}. Let me know what we can do to help your client close this.",
        f"Hey {first_name}, you see my email on {address}? We can close fast as-is — open to chat?",
        f"{first_name} — sent an offer on {address}. Cash or owner finance, 14 days close. Worth a quick call?",
    ]
    message = random.choice(texts)

    if not from_number:
        log.error(f"No GHL phone number configured for market: {market_key}")
        return False

    payload = {
        "type":       "SMS",
        "message":    message,
        "fromNumber": from_number,
        "contactId":  contact_id,
        "locationId": GHL["location_id"],
    }

    try:
        resp = requests.post(
            f"{GHL_BASE_URL}/conversations/messages",
            headers=get_headers(),
            json=payload,
            timeout=10
        )
        if resp.status_code in [200, 201]:
            log.info(f"SMS sent to {contact_id} | {address} | '{message[:50]}...'")
            return True
        else:
            log.error(f"SMS failed: {resp.status_code} {resp.text}")
    except Exception as e:
        log.error(f"GHL SMS error: {e}")
    return False

def push_to_ghl(listing: dict, offer: dict, email_sent: dict, market_key: str) -> bool:
    """
    Master GHL push function.
    1. Creates or finds contact
    2. Fires initial SMS immediately (no sleep — GHL workflow handles delay)
    Returns True on full success.
    """
    contact_id = create_contact(listing, offer, market_key)
    if not contact_id:
        log.error(f"Could not create GHL contact for {listing.get('address')}")
        return False

    # Fire SMS immediately — GHL's Agent Offer Follow-Up workflow
    # handles the Day 0/4/8/14 sequence with its own timing
    sms_success = send_sms(contact_id, listing, offer, market_key)

    if sms_success:
        log.info(f"GHL push complete: {listing.get('address')}")
    else:
        log.warning(f"GHL contact created but SMS failed: {listing.get('address')}")

    return sms_success
