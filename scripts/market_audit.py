"""
scripts/market_audit.py — Read-only market audit tool for 229 Holdings LLC.

Scrapes candidate markets via Apify and reports DOM distribution, lead quality,
and inventory depth WITHOUT sending emails, pushing to GHL, writing dedup history,
or modifying any production data files.

Usage:
    APIFY_API_TOKEN=xxx python scripts/market_audit.py
    APIFY_API_TOKEN=xxx python scripts/market_audit.py --markets huntsville montgomery
    APIFY_API_TOKEN=xxx python scripts/market_audit.py --dry   # skip Apify, generate sample report

Safety guarantees (enforced in code):
    - No Gmail send
    - No GHL push
    - No dedup_log.json write
    - No pipeline_log.json write
    - No mark_sent
    - No offer email generation
    - Output only to reports/ directory
"""

import os
import sys
import json
import time
import re
import csv
import logging
import argparse
from datetime import datetime
from urllib.parse import quote

# ── Safety guard: abort if production env vars would trigger sends ─────────────
_SEND_GUARDS = ["GMAIL_USER_MEMPHIS", "GMAIL_USER_BIRMINGHAM"]
# (We don't block env vars from existing — audit only calls Apify, not Gmail/GHL)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger("market_audit")

# ── Audit-only constants — do NOT import from config.py (avoids production coupling) ─
MIN_DOM_AUTOSEND = 30   # hard rule — never changes without explicit approval
ACTOR_ID         = "maxcopell/zillow-scraper"

AUDIT_PRICE_BANDS = [
    {"min": 30000,  "max": 55000,  "label": "$30k-$55k",  "lane": "OF"},
    {"min": 55001,  "max": 80000,  "label": "$55k-$80k",  "lane": "OF"},
    {"min": 80001,  "max": 100000, "label": "$80k-$100k", "lane": "AUDIT_ONLY"},
    {"min": 100001, "max": 150000, "label": "$100k-$150k","lane": "CASH_MANUAL"},
]

# Candidate markets — NOT in production config
CANDIDATE_MARKETS = {
    "huntsville": {
        "label": "Huntsville / Decatur / Madison / Athens, AL",
        "cities": ["Huntsville", "Decatur", "Madison", "Athens"],
        "state": "AL",
        "bounds": {"west": -87.1, "east": -86.3, "south": 34.4, "north": 34.9},
        "pop_est": "500k metro",
        "landlord_friendly": True,
        "investor_notes": "Strong military/defense economy, growing tech hub, active investor market.",
        "legal_note": "needs_legal_review",
    },
    "montgomery": {
        "label": "Montgomery, AL",
        "cities": ["Montgomery"],
        "state": "AL",
        "bounds": {"west": -86.5, "east": -86.1, "south": 32.2, "north": 32.5},
        "pop_est": "380k metro",
        "landlord_friendly": True,
        "investor_notes": "State capital, affordable housing, active rental market.",
        "legal_note": "needs_legal_review",
    },
    "mobile": {
        "label": "Mobile, AL",
        "cities": ["Mobile"],
        "state": "AL",
        "bounds": {"west": -88.2, "east": -87.9, "south": 30.6, "north": 30.8},
        "pop_est": "430k metro",
        "landlord_friendly": True,
        "investor_notes": "Port city, affordable, steady rental demand.",
        "legal_note": "needs_legal_review",
    },
    "little_rock": {
        "label": "Little Rock / North Little Rock / Conway, AR",
        "cities": ["Little Rock", "North Little Rock", "Conway"],
        "state": "AR",
        "bounds": {"west": -92.5, "east": -92.0, "south": 34.6, "north": 35.0},
        "pop_est": "750k metro",
        "landlord_friendly": True,
        "investor_notes": "Low cost of living, diverse economy, active wholesaling community.",
        "legal_note": "needs_legal_review",
    },
    "oklahoma_city": {
        "label": "Oklahoma City, OK",
        "cities": ["Oklahoma City"],
        "state": "OK",
        "bounds": {"west": -97.7, "east": -97.2, "south": 35.3, "north": 35.7},
        "pop_est": "1.4M metro",
        "landlord_friendly": True,
        "investor_notes": "Energy sector economy, very landlord friendly, active investor/wholesaling market.",
        "legal_note": "needs_legal_review",
    },
    "tulsa": {
        "label": "Tulsa, OK",
        "cities": ["Tulsa"],
        "state": "OK",
        "bounds": {"west": -96.1, "east": -95.7, "south": 36.0, "north": 36.3},
        "pop_est": "1.0M metro",
        "landlord_friendly": True,
        "investor_notes": "Affordable, diverse economy, strong investor activity.",
        "legal_note": "needs_legal_review",
    },
    "knoxville": {
        "label": "Knoxville, TN",
        "cities": ["Knoxville"],
        "state": "TN",
        "bounds": {"west": -84.2, "east": -83.8, "south": 35.9, "north": 36.1},
        "pop_est": "900k metro",
        "landlord_friendly": True,
        "investor_notes": "University town, tourism, growing market. Similar to Memphis dynamics.",
        "legal_note": "needs_legal_review",
    },
    "chattanooga": {
        "label": "Chattanooga, TN",
        "cities": ["Chattanooga"],
        "state": "TN",
        "bounds": {"west": -85.4, "east": -85.1, "south": 35.0, "north": 35.2},
        "pop_est": "580k metro",
        "landlord_friendly": True,
        "investor_notes": "Growing tech and tourism hub, affordable, strong rental demand.",
        "legal_note": "needs_legal_review",
    },
    "augusta": {
        "label": "Augusta, GA",
        "cities": ["Augusta"],
        "state": "GA",
        "bounds": {"west": -82.1, "east": -81.8, "south": 33.3, "north": 33.6},
        "pop_est": "620k metro",
        "landlord_friendly": True,
        "investor_notes": "Military (Ft. Eisenhower), medical hub, affordable housing.",
        "legal_note": "needs_legal_review",
    },
    "columbus_ga": {
        "label": "Columbus, GA",
        "cities": ["Columbus"],
        "state": "GA",
        "bounds": {"west": -85.0, "east": -84.8, "south": 32.4, "north": 32.6},
        "pop_est": "375k metro",
        "landlord_friendly": True,
        "investor_notes": "Military (Ft. Moore), steady rental demand, affordable.",
        "legal_note": "needs_legal_review",
    },
}


# ── Zillow URL builder (audit variant) ───────────────────────────────────────────
def build_audit_url(bounds: dict, price_min: int, price_max: int, price_reduced: bool = False) -> str:
    filter_state = {
        "price": {"min": price_min, "max": price_max},
        "beds":  {"min": 1},
        "sqft":  {"min": 750},
        "isForSaleByAgent":  {"value": True},
        "isForSaleByOwner":  {"value": False},
        "isNewConstruction": {"value": False},
        "isAuction":         {"value": False},
        "isMakeMeMove":      {"value": False},
        "sort":              {"value": "days"},  # oldest first
    }
    if price_reduced:
        filter_state["isReducedPrice"] = {"value": True}

    state_obj = {
        "isMapVisible": True,
        "mapBounds":    bounds,
        "filterState":  filter_state,
        "isListVisible": True,
    }
    encoded = quote(json.dumps(state_obj, separators=(",", ":")))
    return f"https://www.zillow.com/homes/for_sale/?searchQueryState={encoded}"


# ── DOM extraction (mirrors scraper.py logic) ────────────────────────────────────
def get_dom(listing: dict):
    import ast
    for key in ["daysOnZillow", "timeOnZillow", "days_on_zillow"]:
        val = listing.get(key)
        if val and isinstance(val, int) and val < 10000:
            return val
    hdp_raw = listing.get("hdpData", "")
    if hdp_raw:
        try:
            hdp = ast.literal_eval(hdp_raw) if isinstance(hdp_raw, str) else hdp_raw
            home_info = hdp.get("homeInfo", {})
            for key in ["daysOnZillow", "timeOnZillow"]:
                val = home_info.get(key)
                if val and isinstance(val, (int, float)) and val < 10000:
                    return int(val)
        except Exception:
            pass
    flex = str(listing.get("flexFieldText", ""))
    day_match = re.search(r"(\d+)\s*day", flex, re.IGNORECASE)
    if day_match:
        return int(day_match.group(1))
    if re.search(r"\d+\s*hour", flex, re.IGNORECASE):
        return 0
    return None


def parse_price(val) -> int:
    if not val:
        return 0
    if isinstance(val, (int, float)):
        return int(val)
    cleaned = re.sub(r"[^\d]", "", str(val))
    return int(cleaned) if cleaned else 0


# ── DOM bucket classifier ─────────────────────────────────────────────────────────
def dom_bucket(dom) -> str:
    if dom is None:
        return "unknown"
    if dom == 0:
        return "dom_0_fresh"
    if dom <= 6:
        return "dom_1_6"
    if dom <= 29:
        return "dom_7_29"
    return "dom_30_plus"


# ── Dedup by zpid/url/address ────────────────────────────────────────────────────
def dedup_key(item: dict) -> str:
    zpid = str(item.get("zpid") or "").strip()
    if zpid and zpid != "0":
        return f"zpid:{zpid}"
    url = item.get("detailUrl") or item.get("hdpUrl") or ""
    m = re.search(r"(\d+)_zpid", url)
    if m:
        return f"zpid:{m.group(1)}"
    addr = (item.get("address") or item.get("streetAddress") or "").lower().strip()
    return addr or "unknown"


# ── Scrape one band from Apify ───────────────────────────────────────────────────
def scrape_band(client, market_key: str, bounds: dict, band: dict,
                price_reduced: bool = False) -> dict:
    variant = "price_reduced" if price_reduced else "base"
    label   = f"{market_key} {band['label']} [{variant}]"

    url = build_audit_url(bounds, band["min"], band["max"], price_reduced=price_reduced)
    log.info(f"  Scraping: {label}")

    result = {
        "market":       market_key,
        "band":         band["label"],
        "lane":         band["lane"],
        "variant":      variant,
        "url":          url,
        "raw_count":    0,
        "unique_count": 0,
        "dom_unknown":  0,
        "dom_0_fresh":  0,
        "dom_1_6":      0,
        "dom_7_29":     0,
        "dom_30_plus":  0,
        "autosend_eligible": 0,
        "top_leads":    [],
        "usable":       False,
        "error":        None,
    }

    try:
        run   = client.actor(ACTOR_ID).call(
            run_input={"searchUrls": [{"url": url}]},
        )
        items = list(client.dataset(run["defaultDatasetId"]).iterate_items())
        result["raw_count"] = len(items)

        seen = set()
        leads = []
        for item in items:
            status = (item.get("statusType") or "").upper()
            if status and status not in ("FOR_SALE", "FORSALE", "ACTIVE", ""):
                continue
            key = dedup_key(item)
            if key in seen:
                continue
            seen.add(key)

            dom    = get_dom(item)
            bucket = dom_bucket(dom)
            result[bucket] = result.get(bucket, 0) + 1

            price = parse_price(item.get("unformattedPrice") or item.get("price"))
            addr  = item.get("address") or item.get("streetAddress") or ""
            agent = item.get("brokerName") or item.get("agentName") or ""
            zpid  = str(item.get("zpid") or "")
            detail_url = item.get("detailUrl") or item.get("hdpUrl") or ""
            if detail_url and not detail_url.startswith("http"):
                detail_url = "https://www.zillow.com" + detail_url
            if not detail_url and zpid:
                detail_url = f"https://www.zillow.com/homedetails/{zpid}_zpid/"

            leads.append({
                "address":   addr,
                "price":     price,
                "dom":       dom,
                "dom_bucket": bucket,
                "agent":     agent,
                "zpid":      zpid,
                "url":       detail_url,
                "autosend_eligible": dom is not None and dom >= MIN_DOM_AUTOSEND,
            })

        result["unique_count"]     = len(leads)
        result["autosend_eligible"] = sum(1 for l in leads if l["autosend_eligible"])
        result["usable"]           = result["autosend_eligible"] >= 3

        # Top 10: prioritize DOM >= 30, then by descending DOM
        eligible   = sorted([l for l in leads if l["autosend_eligible"]], key=lambda x: -(x["dom"] or 0))
        ineligible = sorted([l for l in leads if not l["autosend_eligible"]], key=lambda x: -(x["dom"] or 0))
        result["top_leads"] = (eligible + ineligible)[:10]

    except Exception as e:
        result["error"] = str(e)
        log.error(f"  Failed: {label} — {e}")

    log.info(
        f"  {label}: raw={result['raw_count']} | unique={result['unique_count']} | "
        f"DOM30+={result['dom_30_plus']} | eligible={result['autosend_eligible']} | "
        f"usable={result['usable']}"
    )
    return result


# ── Fake data for --dry mode (no Apify calls) ────────────────────────────────────
def fake_band_result(market_key: str, band: dict, price_reduced: bool = False) -> dict:
    import random
    random.seed(hash(f"{market_key}{band['label']}{price_reduced}"))
    raw = random.randint(8, 40)
    d30 = random.randint(0, min(raw, 8))
    d7  = random.randint(0, raw - d30)
    d06 = raw - d30 - d7
    leads = []
    for i in range(min(raw, 10)):
        dom = random.choice([None, 0, 5, 15, 22, 31, 45, 60, 90])
        leads.append({
            "address": f"{100+i} Sample St, {market_key.title()}, XX 00000",
            "price":   random.randint(band["min"], band["max"]),
            "dom":     dom,
            "dom_bucket": dom_bucket(dom),
            "agent":   "Sample Agent LLC",
            "zpid":    str(random.randint(10000000, 99999999)),
            "url":     f"https://www.zillow.com/homedetails/sample/{i}_zpid/",
            "autosend_eligible": dom is not None and dom >= MIN_DOM_AUTOSEND,
        })
    return {
        "market": market_key, "band": band["label"], "lane": band["lane"],
        "variant": "price_reduced" if price_reduced else "base",
        "url": "https://www.zillow.com/dry-run/",
        "raw_count": raw, "unique_count": raw,
        "dom_unknown": 0, "dom_0_fresh": d06 // 2, "dom_1_6": d06 - d06 // 2,
        "dom_7_29": d7, "dom_30_plus": d30,
        "autosend_eligible": d30,
        "top_leads": leads, "usable": d30 >= 3, "error": None,
    }


# ── Report writers ────────────────────────────────────────────────────────────────
def write_json(results: list, market_meta: dict, output_dir: str):
    path = os.path.join(output_dir, "market_audit_results.json")
    payload = {
        "generated_at":    datetime.utcnow().isoformat() + "Z",
        "min_dom_autosend": MIN_DOM_AUTOSEND,
        "markets":         market_meta,
        "results":         results,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    log.info(f"JSON written: {path}")
    return path


def write_csv(results: list, output_dir: str):
    path = os.path.join(output_dir, "market_audit_results.csv")
    fields = [
        "market", "band", "lane", "variant",
        "raw_count", "unique_count",
        "dom_unknown", "dom_0_fresh", "dom_1_6", "dom_7_29", "dom_30_plus",
        "autosend_eligible", "usable", "error",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)
    log.info(f"CSV written: {path}")
    return path


def write_markdown(results: list, market_meta: dict, ranking: list, output_dir: str):
    path = os.path.join(output_dir, "market_audit_summary.md")
    ts   = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# Market Audit — 229 Holdings LLC",
        f"Generated: {ts}  ",
        f"Auto-send threshold: **DOM ≥ {MIN_DOM_AUTOSEND}** (hard rule — never lower without approval)  ",
        f"Cash / no-ARV: **manual review only**  ",
        f"$80k-$100k band: **audit only — not production-routed**",
        "",
        "---",
        "",
        "## Market Rankings (by DOM ≥ 30 OF inventory)",
        "",
        "| Rank | Market | OF DOM30+ | OF Usable Bands | Notes |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(ranking, 1):
        mk     = r["market_key"]
        meta   = market_meta.get(mk, {})
        of30   = r["of_dom30_total"]
        usable = r["usable_of_bands"]
        note   = meta.get("investor_notes", "")[:60]
        lines.append(f"| {i} | {meta.get('label', mk)} | {of30} | {usable} | {note} |")

    lines += ["", "---", ""]

    # Per-market detail sections
    by_market: dict = {}
    for res in results:
        mk = res["market"]
        by_market.setdefault(mk, []).append(res)

    for mk, mresults in by_market.items():
        meta = market_meta.get(mk, {})
        lines += [
            f"## {meta.get('label', mk)}",
            f"**State:** {meta.get('state', '')}  ",
            f"**Population est.:** {meta.get('pop_est', 'unknown')}  ",
            f"**Landlord friendly:** {'Yes' if meta.get('landlord_friendly') else 'No/Unknown'}  ",
            f"**Legal status:** `{meta.get('legal_note', 'needs_legal_review')}`  ",
            f"**Notes:** {meta.get('investor_notes', '')}",
            "",
        ]

        for res in mresults:
            usable_str  = "✅ USABLE" if res["usable"] else "❌ insufficient DOM30+"
            lane_str    = res["lane"]
            eligible    = res["autosend_eligible"]
            error_str   = f" **ERROR: {res['error']}**" if res.get("error") else ""

            lines += [
                f"### {res['band']} [{res['variant']}] — {lane_str} {usable_str}{error_str}",
                f"| Metric | Count |",
                f"|---|---|",
                f"| Raw results | {res['raw_count']} |",
                f"| Unique (after dedup) | {res['unique_count']} |",
                f"| DOM unknown | {res['dom_unknown']} |",
                f"| DOM 0 (fresh) | {res['dom_0_fresh']} |",
                f"| DOM 1-6 | {res['dom_1_6']} |",
                f"| DOM 7-29 (manual review only) | {res['dom_7_29']} |",
                f"| **DOM ≥ 30 (auto-send eligible)** | **{res['dom_30_plus']}** |",
                "",
            ]

            if res["top_leads"]:
                lines += [
                    "**Top leads (DOM ≥ 30 first):**",
                    "",
                    "| Address | Price | DOM | Agent | Eligible |",
                    "|---|---|---|---|---|",
                ]
                for lead in res["top_leads"]:
                    dom_d    = lead["dom"] if lead["dom"] is not None else "?"
                    eligible = "✅" if lead["autosend_eligible"] else "❌"
                    price_s  = f"${lead['price']:,}" if lead.get("price") else "?"
                    url_s    = f"[link]({lead['url']})" if lead.get("url") else ""
                    lines.append(
                        f"| {lead['address']} {url_s} | {price_s} | {dom_d} | {lead['agent'][:30]} | {eligible} |"
                    )
                lines.append("")

    lines += [
        "---",
        "",
        "## Production Sending Rules (unchanged)",
        "",
        "- Auto-send eligible: **DOM ≥ 30 only**",
        "- DOM 7-29: manual review bucket only, never auto-sends",
        "- Cash / no-ARV: manual review only",
        "- $80k-$100k band: audit only, not production-routed",
        "- Daily send cap: **30 emails/day total** (15/inbox × 2 inboxes)",
        "- Adding markets does not increase send volume",
        "- All `legal_note` fields: `needs_legal_review` until verified",
    ]

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    log.info(f"Markdown written: {path}")
    return path


def rank_markets(results: list, market_meta: dict) -> list:
    by_market: dict = {}
    for res in results:
        mk = res["market"]
        by_market.setdefault(mk, [])
        by_market[mk].append(res)

    ranking = []
    for mk, mresults in by_market.items():
        of_results   = [r for r in mresults if r["lane"] in ("OF",) and r["variant"] == "base"]
        of_dom30     = sum(r["dom_30_plus"] for r in of_results)
        usable_bands = sum(1 for r in of_results if r["usable"])
        ranking.append({
            "market_key":    mk,
            "of_dom30_total": of_dom30,
            "usable_of_bands": usable_bands,
        })

    ranking.sort(key=lambda x: (-x["of_dom30_total"], -x["usable_of_bands"]))
    return ranking


# ── Main ──────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="229 Holdings Market Audit — read-only")
    parser.add_argument(
        "--markets", nargs="*",
        default=list(CANDIDATE_MARKETS.keys()),
        choices=list(CANDIDATE_MARKETS.keys()) + ["all"],
        help="Which markets to audit (default: all)"
    )
    parser.add_argument(
        "--dry", action="store_true",
        help="Skip Apify calls, generate sample report with fake data"
    )
    parser.add_argument(
        "--output-dir", default=os.path.join(ROOT, "reports"),
        help="Directory for output files"
    )
    parser.add_argument(
        "--price-reduced", action="store_true",
        help="Also run price-reduced filter variant for each band"
    )
    parser.add_argument(
        "--sleep", type=int, default=3,
        help="Seconds to sleep between Apify calls (default: 3)"
    )
    args = parser.parse_args()

    markets_to_run = (
        list(CANDIDATE_MARKETS.keys())
        if "all" in (args.markets or [])
        else (args.markets or list(CANDIDATE_MARKETS.keys()))
    )

    os.makedirs(args.output_dir, exist_ok=True)

    # ── Safety checks ─────────────────────────────────────────────────────────
    log.info("=" * 60)
    log.info("229 Holdings — Market Audit (READ-ONLY)")
    log.info(f"Markets: {markets_to_run}")
    log.info(f"Dry mode: {args.dry}")
    log.info(f"DOM auto-send threshold: >= {MIN_DOM_AUTOSEND}")
    log.info("AUDIT ONLY — no emails, no GHL, no dedup writes")
    log.info("=" * 60)

    client = None
    if not args.dry:
        token = os.environ.get("APIFY_API_TOKEN", "")
        if not token:
            log.error("APIFY_API_TOKEN not set. Use --dry for a test run.")
            sys.exit(1)
        from apify_client import ApifyClient
        client = ApifyClient(token)

    results     = []
    market_meta = {}

    for mk in markets_to_run:
        mdata = CANDIDATE_MARKETS.get(mk)
        if not mdata:
            log.warning(f"Unknown market: {mk} — skipping")
            continue

        market_meta[mk] = mdata
        log.info(f"\n{'='*50}")
        log.info(f"MARKET: {mdata['label']}")
        log.info(f"{'='*50}")

        for band in AUDIT_PRICE_BANDS:
            # Base search
            if args.dry:
                res = fake_band_result(mk, band, price_reduced=False)
            else:
                res = scrape_band(client, mk, mdata["bounds"], band, price_reduced=False)
                time.sleep(args.sleep)
            results.append(res)

            # Price-reduced variant (optional)
            if args.price_reduced:
                if args.dry:
                    res_pr = fake_band_result(mk, band, price_reduced=True)
                else:
                    res_pr = scrape_band(client, mk, mdata["bounds"], band, price_reduced=True)
                    time.sleep(args.sleep)
                results.append(res_pr)

    # ── Write reports ─────────────────────────────────────────────────────────
    ranking  = rank_markets(results, market_meta)
    json_path = write_json(results, market_meta, args.output_dir)
    csv_path  = write_csv(results, args.output_dir)
    md_path   = write_markdown(results, market_meta, ranking, args.output_dir)

    log.info("")
    log.info("=" * 60)
    log.info("AUDIT COMPLETE — read-only, no production data changed")
    log.info(f"JSON:     {json_path}")
    log.info(f"CSV:      {csv_path}")
    log.info(f"Markdown: {md_path}")
    log.info("")
    log.info("TOP MARKET RANKING (OF DOM ≥ 30):")
    for i, r in enumerate(ranking[:5], 1):
        meta = market_meta.get(r["market_key"], {})
        log.info(f"  {i}. {meta.get('label', r['market_key'])}: DOM30+={r['of_dom30_total']} usable_bands={r['usable_of_bands']}")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
