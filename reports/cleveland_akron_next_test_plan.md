# Cleveland / Akron Next Test Plan

## Why Little Rock / OKC Are Paused For Email-First Outreach

The current Little Rock / OKC contact research queue found 0 verified direct listing-agent emails out of 25 researched records. Those markets can still be worked by phone, manual contact forms, or manually approved brokerage outreach, but they should not be prioritized for Gmail-first testing until verified direct agent emails are available.

## Why Cleveland / Akron Are Next

Human-verified Zillow screenshots showed Cleveland and Akron listings exposing direct listing-agent emails in the Zillow Listed By section. The examples were MLS Now / Akron Cleveland Association of REALTORS and MLS Now / Lorain County Association of REALTORS patterns, which appear more promising for email-first outreach than the researched Little Rock / OKC sample.

## Safe Future Run Settings

- `dry_run=true`
- `force_run=true`
- `target_markets=cleveland,akron`
- `apify_enabled=true` only when Apify credits are available
- `email_enrichment_enabled=false`
- `live_send_enabled=false`
- `clear_overflow_before_run=false`

The first future run should scrape only Cleveland and Akron with small caps if possible. Use the existing workflow caps (`MAX_APIFY_RUNS_PER_WORKFLOW`, `max_email_enrichment_calls`, and `max_leads_to_enrich`) to keep the paid scrape bounded. Do not send Gmail until the review queue shows verified direct listing-agent emails and those emails pass manual review.

## Implementation Notes

- Cleveland and Akron are configured as inactive test markets, not live-send markets.
- Both markets are capped around $125,000 for cheap/investor inventory.
- The parser now reads visible Zillow Listed By text when present and extracts only explicitly visible emails and phone numbers.
- Email extraction does not infer or pattern-match emails from names or brokerage domains.
