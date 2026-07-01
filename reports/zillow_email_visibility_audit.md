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

Goal: check whether cheap/investor Zillow listing detail pages expose direct listing-agent emails.

## Codex-Accessible Sample Results

Codex could not complete a reliable automated/public-browser sample for the expansion markets.

Zillow city/search pages returned a human-check page with `px-captcha` / "Access to this page has been denied" when requested through the available public shell browser path. Public search queries in the available search channel did not return enough usable Zillow detail URLs for the requested markets. Because of that, the Codex-accessible portion of the audit remains inconclusive and should not be treated as evidence that a market does or does not expose emails.

## Human-Verified Screenshot Examples

The following examples were manually verified from human screenshots of Zillow listing detail pages. These are not guessed or inferred emails.

| market | address | days on Zillow | agent | brokerage | email | phone | source pattern | status |
|---|---|---:|---|---|---|---|---|---|
| Cleveland, OH | 4297 E 139th St, Cleveland, OH 44105 | 36 | Rakesh Baniya | Cleveland Property Management Group, LLC | rbaniya@clevelandpropertymanagement.com | 440-901-7145 | MLS Now / Akron Cleveland Association of REALTORS | direct_agent_email_visible |
| Cleveland, OH | 10712 Grantwood Ave, Cleveland, OH 44108 | 88 | Leilani M Bowersock | Coldwell Banker Schmidt Realty | leilani7b@gmail.com | 440-570-9514 | Zillow Listed By screenshot | direct_agent_email_visible |
| Akron, OH | 840 Work Dr, Akron, OH 44320 | 40 | Christopher A Frederick | Coldwell Banker Schmidt Realty | thefrederickteam@gmail.com | 216-210-7653 | MLS Now / Lorain County Association of REALTORS | direct_agent_email_visible |

Additional observed Akron example: a Marshall Stephens example was mentioned, but it is not added to the CSV because the address and Zillow URL were not clear enough from the provided information.

## Summary By Market

This table combines only verified rows currently recorded in `data/zillow_email_visibility_audit.csv`.

| market | listings checked | direct_agent_email_visible | brokerage_email_visible | phone_only | contact_form_only | no_contact_found | email visibility percentage |
|---|---:|---:|---:|---:|---:|---:|---:|
| Cleveland, OH | 2 | 2 | 0 | 0 | 0 | 0 | 100% |
| Akron, OH | 1 | 1 | 0 | 0 | 0 | 0 | 100% |
| Toledo, OH | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| Detroit, MI | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| Milwaukee, WI | 0 | 0 | 0 | 0 | 0 | 0 | n/a |
| Saint Louis, MO | 0 | 0 | 0 | 0 | 0 | 0 | n/a |

## Best Markets Ranked By Direct Agent Email Visibility

1. Cleveland, OH: 2 verified examples, 2 direct agent emails visible.
2. Akron, OH: 1 verified example, 1 direct agent email visible.
3. Toledo, OH: no verified sample yet.
4. Detroit, MI: no verified sample yet.
5. Milwaukee, WI: no verified sample yet.
6. Saint Louis, MO: no verified sample yet.

## MLS / Source Pattern Notes

- Cleveland example 1 showed MLS Now / Akron Cleveland Association of REALTORS and a direct agent email in Zillow's Listed By section.
- Akron example 1 showed MLS Now / Lorain County Association of REALTORS and a direct agent email in Zillow's Listed By section.
- The screenshot evidence suggests MLS Now-fed Zillow listings may expose direct listing-agent emails more often than the Little Rock / OKC samples researched so far.

## Recommendation

Recommended next two markets for email-first testing:

1. Cleveland, OH
2. Akron, OH

Reason: the Little Rock / OKC researched contact queue found 0 direct agent emails out of 25, while human screenshots show Cleveland/Akron MLS Now listings exposing direct listing-agent emails directly in Zillow's Listed By section.

Pause Little Rock / OKC for email-first outreach until direct agent emails are available or a human explicitly approves brokerage/office outreach. Keep those markets active for phone/manual/contact-form workflows, but do not prioritize Gmail-first outreach there.

Codex automated audit remains inconclusive due to Zillow/search access limits. The recommendation to test Cleveland/Akron is based on the human-verified screenshot examples, not on a completed automated sample.

## Next Safe No-Cost Step

Use a normal human browser to collect 10 Zillow detail URLs per Cleveland and Akron. Record only visibly published contact information from the Zillow Listed By section or official brokerage/agent pages. Do not infer email patterns.
