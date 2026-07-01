# Zillow Email Visibility Audit

Audit date: 2026-06-30

## Scope

Markets requested:

- Cleveland, OH
- Akron, OH
- Toledo, OH
- Detroit, MI
- Milwaukee, WI
- Saint Louis, MO

Goal: check a small no-cost, manual-style sample of cheap/investor Zillow listing detail pages for direct listing-agent email visibility.

## Access Result

No expansion-market Zillow listing detail pages were verified in this run.

Zillow city/search pages returned a human-check page with `px-captcha` / "Access to this page has been denied" when requested through the available public shell browser path. Public search queries in the available search channel did not return usable Zillow detail URLs for the requested markets. Because of that, this audit does not fabricate listing rows and does not infer contact visibility.

## Summary By Market

| market | listings checked | direct_agent_email_visible | brokerage_email_visible | phone_only | contact_form_only | no_contact_found | email visibility percentage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Cleveland, OH | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| Akron, OH | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| Toledo, OH | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| Detroit, MI | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| Milwaukee, WI | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| Saint Louis, MO | 0 | 0 | 0 | 0 | 0 | 0 | n/a |

## Market Ranking

No market can be ranked by direct agent email visibility from this run because no requested-market Zillow detail pages were verifiably accessible.

## MLS / Source Pattern Notes

No MLS source patterns were verified for the requested markets in this run. The audit could not confirm MLS Now, Realcomp, MLS Grid, or other local feed behavior from Zillow detail pages.

## Recommendation

Top 2 markets to scrape next: none selected from this audit. A market should not be prioritized for email-first outreach until a real sample of public listing detail pages is verified.

Cleveland and Akron do not currently look better than Little Rock / OKC for email-first outreach based on this run. The result is inconclusive, not negative: the available public access path was blocked before listing detail pages could be sampled.

Do not pause Little Rock / OKC solely because of this audit. Keep the current contact-policy guardrails: only `verified_agent_email` should be eligible for first live email testing after manual review; brokerage emails require separate manual approval.

## Next Safe No-Cost Step

Use a normal signed-in browser manually, not Apify or paid enrichment, to open 10 Zillow detail pages per market and record only visibly published email/phone/contact information. If Zillow continues to block search pages, collect candidate listing URLs from a human browser session or from the listing brokerage's public site, then re-run this audit manually with the actual Zillow detail URLs.
