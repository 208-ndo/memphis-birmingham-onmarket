"""
agent_email_finder.py
Finds published agent email using Google Search via Apify.
Uses agent name + brokerage to find their published business email.
"""

import os
import re
import time
import logging
from apify_client import ApifyClient

logger = logging.getLogger(__name__)

APIFY_TOKEN      = os.environ.get("APIFY_API_TOKEN")
GOOGLE_ACTOR_ID  = "apify/google-search-scraper"

# Regex to extract email from text
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Domains that are NOT agent emails — skip these
SKIP_DOMAINS = {
    "zillow.com", "realtor.com", "redfin.com", "homes.com",
    "trulia.com", "gmail.com", "yahoo.com", "hotmail.com",
    "outlook.com", "icloud.com", "aol.com", "example.com",
}


def is_valid_agent_email(email: str) -> bool:
    """Return True if email looks like a real brokerage/agent email."""
    if not email:
        return False
    domain = email.split("@")[-1].lower()
    return domain not in SKIP_DOMAINS


def search_agent_email(agent_name: str, brokerage: str, city: str, client: ApifyClient) -> str:
    """
    Google search for agent's published business email.
    Returns email string or empty string.
    """
    if not agent_name and not brokerage:
        return ""

    # Build search queries — try most specific first
    queries = []
    if agent_name and brokerage:
        queries.append(f'"{agent_name}" "{brokerage}" email {city}')
        queries.append(f'"{agent_name}" "{brokerage}" contact')
    elif agent_name:
        queries.append(f'"{agent_name}" real estate agent email {city}')
    elif brokerage:
        queries.append(f'"{brokerage}" {city} real estate agent contact email')

    for query in queries:
        try:
            run = client.actor(GOOGLE_ACTOR_ID).call(
                run_input={
                    "queries":        query,
                    "maxPagesPerQuery": 1,
                    "resultsPerPage": 5,
                    "languageCode":   "en",
                    "countryCode":    "us",
                },
                timeout_secs=60
            )
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

            for item in items:
                # Check organic results
                for result in item.get("organicResults", []):
                    text = " ".join([
                        result.get("title", ""),
                        result.get("description", ""),
                        result.get("url", ""),
                    ])
                    emails = EMAIL_RE.findall(text)
                    for email in emails:
                        if is_valid_agent_email(email):
                            logger.info(f"Found email via Google: {email} for {agent_name} / {brokerage}")
                            return email.lower()

            time.sleep(2)

        except Exception as e:
            logger.debug(f"Google search failed for '{query}': {e}")
            continue

    # Fallback: try brokerage website directly
    if brokerage:
        try:
            brokerage_domain = brokerage.lower().replace(" ", "").replace(",", "").replace(".", "")[:20]
            fallback_query = f'site:{brokerage_domain}.com "{agent_name}"'
            run = client.actor(GOOGLE_ACTOR_ID).call(
                run_input={
                    "queries":          fallback_query,
                    "maxPagesPerQuery": 1,
                    "resultsPerPage":   3,
                },
                timeout_secs=60
            )
            items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
            for item in items:
                for result in item.get("organicResults", []):
                    text = result.get("description", "") + " " + result.get("title", "")
                    emails = EMAIL_RE.findall(text)
                    for email in emails:
                        if is_valid_agent_email(email):
                            logger.info(f"Found email via brokerage site: {email}")
                            return email.lower()
        except Exception:
            pass

    return ""


def enrich_leads_with_emails(leads: list, market: dict, client: ApifyClient) -> list:
    """
    For each lead missing an agent email, try to find one via Google.
    Returns leads list with emails filled in where found.
    """
    city          = market.get("city", "")
    needs_email   = [l for l in leads if not l.get("agent_email")]
    has_email     = [l for l in leads if l.get("agent_email")]

    logger.info(f"Email lookup: {len(needs_email)} leads need emails, {len(has_email)} already have one")

    # Deduplicate by brokerage — don't search same brokerage twice
    brokerage_emails = {}

    for lead in needs_email:
        agent_name = lead.get("agent_name", "")
        brokerage  = lead.get("brokerName") or lead.get("agent_name", "")

        # Check if we already found an email for this brokerage
        if brokerage in brokerage_emails:
            lead["agent_email"] = brokerage_emails[brokerage]
            logger.info(f"Reused cached email for {brokerage}: {lead['agent_email']}")
            continue

        email = search_agent_email(agent_name, brokerage, city, client)
        if email:
            lead["agent_email"] = email
            brokerage_emails[brokerage] = email
        else:
            brokerage_emails[brokerage] = ""  # Cache miss too
            logger.info(f"No email found for {agent_name} / {brokerage}")

        time.sleep(1)

    found = sum(1 for l in needs_email if l.get("agent_email"))
    logger.info(f"Email enrichment complete: found {found}/{len(needs_email)} emails")

    return has_email + needs_email
