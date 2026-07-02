"""
offer.py — 229 Holdings LLC
Two offer lanes:
  1. Owner Finance: full list, 5% down, seller carries, clean broker-comp language
  2. Cash Lowball:  MAO-capped + Listed Property Visible Spread Rule
                    ARV required — no ARV = no cash offer
"""

from config import (
    OF_MIN_PRICE, OF_MAX_PRICE, OF_DOWN_PCT, OF_NUM_PAYMENTS,
    OF_SELLER_RATE, OF_BUYER_DOWN_PCT, OF_BUYER_RATE, OF_BUYER_TERM_YRS,
    OF_EARNEST, OF_CLOSE_DAYS, OF_DD_DAYS,
    BUYER_MAO_MULTIPLIER, REPAIR_MULTIPLIER,
    ASSIGNMENT_FEE_MIN, ASSIGNMENT_FEE_MAX, ASSIGNMENT_FEE_PCT,
    CLOSING_BUFFER_MIN, CLOSING_BUFFER_PCT,
    INITIAL_OFFER_LOW, INITIAL_OFFER_HIGH,
    CASH_MAX_AUTO, SPREAD_RULES, COMMISSION_LANGUAGE,
    ASSIGNMENT_FEE_MIN_SMALL, ASSIGNMENT_FEE_MAX_SMALL, TRUE_WALKAWAY_PCT,
)

SELLER_FINANCE_PHRASES = (
    "owner financing",
    "seller financing",
    "owner finance",
    "seller finance",
    "no ppp",
    "no prepayment penalty",
    "amortization",
    "interest",
    "down payment",
    "owner will carry",
    "seller will carry",
)
SELLER_FINANCE_MIN_DOWN = 5000.0
SELLER_FINANCE_REVIEW_DOM = 100
RENT_CHECK_MIN_PRICE = 80000.0
RENT_CHECK_MAX_PRICE = 100000.0
MANUAL_OF_REVIEW_MAX_PRICE = 125000.0
MINIMUM_CASHFLOW_REQUIRED = 200.0
MAX_PAYMENT_TO_RENT_RATIO = 0.65
OHIO_EMAIL_FIRST_MARKETS = {"cleveland", "akron"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def round_down_1k(val: float) -> float:
    return float(int(val / 1000) * 1000)


def calc_effective_repairs(repairs: float, arv: float) -> float:
    """effective_repairs = max(estimated_repairs, arv * 0.05, 10000)"""
    return max(repairs, arv * 0.05, 10000.0)


def calc_assignment_fee(arv: float, buyer_mao: float = 0, override: float = None) -> float:
    """ARV * 8%, clamped. Small-deal override if buyer_mao < 50k."""
    if override:
        return float(override)
    base = arv * ASSIGNMENT_FEE_PCT
    if buyer_mao > 0 and buyer_mao < 50000:
        return max(ASSIGNMENT_FEE_MIN_SMALL, min(ASSIGNMENT_FEE_MAX_SMALL, base))
    return max(ASSIGNMENT_FEE_MIN, min(ASSIGNMENT_FEE_MAX, base))


def calc_buyer_mao(arv: float, repairs: float) -> float:
    """Buyer MAO = ARV * 0.90 - (repairs * 2)"""
    return max(0.0, arv * BUYER_MAO_MULTIPLIER - repairs * REPAIR_MULTIPLIER)


def calc_closing_buffer(buyer_mao: float) -> float:
    """max(2500, buyer_mao * 2%)"""
    return max(CLOSING_BUFFER_MIN, buyer_mao * CLOSING_BUFFER_PCT)


def required_visible_spread(list_price: float) -> float:
    """Return required visible spread for a given list price."""
    for (lo, hi, flat, pct) in SPREAD_RULES:
        if lo <= list_price < hi:
            return max(flat, list_price * pct)
    return None  # 500k+ manual review


def calc_visible_spread(list_price: float, contract_price: float,
                         assignment_fee: float) -> float:
    """visible_spread = list_price - (contract_price + assignment_fee)"""
    return list_price - (contract_price + assignment_fee)


def has_seller_finance_terms(listing: dict) -> bool:
    """Detect whether the listing already advertises seller-finance terms."""
    text_parts = [
        listing.get("description"),
        listing.get("listing_description"),
        listing.get("remarks"),
        listing.get("public_remarks"),
        listing.get("listedByText"),
    ]
    text = " ".join(str(part or "") for part in text_parts).lower()
    return any(phrase in text for phrase in SELLER_FINANCE_PHRASES)


def _listing_dom(listing: dict) -> int:
    for key in ("days_on_zillow", "days_on_market", "dom"):
        try:
            return int(float(listing.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return 0


def _is_ohio_email_first_market(listing: dict) -> bool:
    market_key = str(listing.get("market_key") or listing.get("market") or "").lower()
    city = str(listing.get("city") or "").lower()
    return any(key in market_key or key in city for key in OHIO_EMAIL_FIRST_MARKETS)


def _estimate_taxes_insurance(purchase_price: float) -> float:
    return max(250.0, 0.0035 * purchase_price)


def _estimate_repairs_vacancy_management(estimated_rent: float) -> float:
    return max(150.0, 0.15 * estimated_rent)


def _calc_terms_offer_base(list_price: float, min_down: float = 0.0) -> tuple[float, float, float, float]:
    offer_price = list_price
    dp = max(min_down, offer_price * OF_DOWN_PCT)
    balance = offer_price - dp
    monthly = balance / OF_NUM_PAYMENTS
    return offer_price, dp, balance, monthly


# ── Main entry point ───────────────────────────────────────────────────────────

def calculate_offer(listing: dict) -> dict | None:
    list_price = float(listing.get("list_price") or listing.get("price") or 0)
    if not list_price:
        return None
    if has_seller_finance_terms(listing):
        return _calc_seller_finance_counter(listing, list_price)

    # Lane 1 — Owner Finance
    if OF_MIN_PRICE <= list_price <= OF_MAX_PRICE:
        return _calc_owner_finance(listing, list_price)

    if _is_ohio_email_first_market(listing):
        if OF_MAX_PRICE < list_price <= RENT_CHECK_MAX_PRICE:
            return _calc_owner_finance_rent_check(listing, list_price)
        if RENT_CHECK_MAX_PRICE < list_price <= MANUAL_OF_REVIEW_MAX_PRICE:
            return _calc_owner_finance_manual_review(listing, list_price)

    # Lane 2 — Cash
    if list_price > OF_MAX_PRICE:
        if list_price >= CASH_MAX_AUTO:
            return {
                "offer_type":         "manual_review",
                "list_price":         list_price,
                "skip_reason":        "MANUAL REVIEW — $500k+ requires manual underwriting",
                "pitch_holds":        False,
                "commission_language": COMMISSION_LANGUAGE,
            }
        return _calc_cash_lowball(listing, list_price)

    return None


# ── Lane 1: Owner Finance ──────────────────────────────────────────────────────

def _calc_owner_finance(listing: dict, list_price: float) -> dict:
    offer_price = list_price
    dp          = offer_price * OF_DOWN_PCT
    balance     = offer_price - dp
    monthly     = balance / OF_NUM_PAYMENTS   # 0% interest

    # End buyer resale
    buyer_down = offer_price * OF_BUYER_DOWN_PCT
    buyer_bal  = offer_price - buyer_down
    r          = OF_BUYER_RATE / 12
    n          = OF_BUYER_TERM_YRS * 12
    buyer_mo   = (buyer_bal * r) / (1 - (1 + r) ** -n) if r > 0 else buyer_bal / n
    your_cf    = buyer_mo - monthly
    your_fee   = buyer_down - dp

    return {
        "offer_type":            "owner_finance",
        "list_price":            list_price,
        "owner_finance_offer":   offer_price,
        "down_payment":          dp,
        "down_pct":              OF_DOWN_PCT * 100,
        "financed_balance":      balance,
        "monthly_payment":       monthly,
        "num_payments":          OF_NUM_PAYMENTS,
        "seller_rate":           OF_SELLER_RATE,
        "earnest":               OF_EARNEST,
        "close_days":            OF_CLOSE_DAYS,
        "due_diligence_days":    OF_DD_DAYS,
        "buyer_down_pct":        OF_BUYER_DOWN_PCT * 100,
        "buyer_down":            buyer_down,
        "buyer_rate":            OF_BUYER_RATE * 100,
        "buyer_term_yrs":        OF_BUYER_TERM_YRS,
        "buyer_monthly":         buyer_mo,
        "your_monthly_cashflow": your_cf,
        "your_fee_estimate":     your_fee,
        "pitch_holds":           True,
        "commission_language":   COMMISSION_LANGUAGE,
    }


# ── Lane 2: Cash Lowball ───────────────────────────────────────────────────────

def _calc_seller_finance_counter(listing: dict, list_price: float) -> dict:
    offer_price = float(listing.get("purchase_price_override") or list_price)
    dp          = max(SELLER_FINANCE_MIN_DOWN, offer_price * OF_DOWN_PCT)
    balance     = offer_price - dp
    monthly     = balance / OF_NUM_PAYMENTS
    dom         = _listing_dom(listing)
    stale       = dom >= SELLER_FINANCE_REVIEW_DOM
    review_note = ""
    if stale:
        review_note = (
            "Stale seller-finance listing: lead with list price on better terms first. "
            "Only ask for a price discount later if seller rejects better terms."
        )

    return {
        "offer_type":                "seller_finance_counter",
        "list_price":                list_price,
        "owner_finance_offer":       offer_price,
        "purchase_price":            offer_price,
        "down_payment":              dp,
        "down_pct":                  (dp / offer_price * 100) if offer_price else 0,
        "financed_balance":          balance,
        "monthly_payment":           monthly,
        "num_payments":              OF_NUM_PAYMENTS,
        "seller_rate":               0.0,
        "interest_rate":             0.0,
        "prepayment_penalty":        "None",
        "earnest":                   OF_EARNEST,
        "close_days":                OF_CLOSE_DAYS,
        "due_diligence_days":        OF_DD_DAYS,
        "seller_finance_advertised": True,
        "stale_seller_finance":      stale,
        "requires_review":           stale or list_price > OF_MAX_PRICE,
        "manual_review":             stale or list_price > OF_MAX_PRICE,
        "review_note":               review_note,
        "pitch_holds":               not stale and list_price <= OF_MAX_PRICE,
        "commission_language":       COMMISSION_LANGUAGE,
    }


def _calc_owner_finance_rent_check(listing: dict, list_price: float) -> dict:
    offer_price, dp, balance, monthly = _calc_terms_offer_base(list_price)
    estimated_rent = float(listing.get("estimated_rent") or 0)
    taxes_insurance = _estimate_taxes_insurance(offer_price)
    repairs_vacancy_management = (
        _estimate_repairs_vacancy_management(estimated_rent) if estimated_rent else 0.0
    )
    estimated_cashflow = (
        estimated_rent - monthly - taxes_insurance - repairs_vacancy_management
        if estimated_rent else None
    )
    payment_to_rent_ratio = monthly / estimated_rent if estimated_rent else None
    rent_check_pass = bool(
        estimated_rent
        and estimated_cashflow >= MINIMUM_CASHFLOW_REQUIRED
        and payment_to_rent_ratio <= MAX_PAYMENT_TO_RENT_RATIO
    )
    rent_check_status = "PASS" if rent_check_pass else ("FAIL" if estimated_rent else "RENT_CHECK_REQUIRED")
    approved_to_send = bool(listing.get("approved_to_send"))
    live_send_allowed = bool(rent_check_pass and approved_to_send)

    return {
        "offer_type":              "owner_finance_rent_check",
        "list_price":              list_price,
        "owner_finance_offer":     offer_price,
        "purchase_price":          offer_price,
        "down_payment":            dp,
        "down_pct":                OF_DOWN_PCT * 100,
        "financed_balance":        balance,
        "monthly_payment":         monthly,
        "num_payments":            OF_NUM_PAYMENTS,
        "seller_rate":             OF_SELLER_RATE,
        "interest_rate":           OF_SELLER_RATE,
        "earnest":                 OF_EARNEST,
        "close_days":              OF_CLOSE_DAYS,
        "due_diligence_days":      OF_DD_DAYS,
        "estimated_rent":          estimated_rent,
        "estimated_taxes_insurance": taxes_insurance,
        "estimated_repairs_vacancy_management": repairs_vacancy_management,
        "estimated_monthly_cashflow": estimated_cashflow,
        "minimum_cashflow_required": MINIMUM_CASHFLOW_REQUIRED,
        "payment_to_rent_ratio":   payment_to_rent_ratio,
        "max_payment_to_rent_ratio": MAX_PAYMENT_TO_RENT_RATIO,
        "rent_check_status":       rent_check_status,
        "rent_check_pass":         rent_check_pass,
        "eligible_for_human_review": rent_check_pass,
        "approved_to_send":        approved_to_send,
        "live_send_allowed":       live_send_allowed,
        "live_send_blocked":       not live_send_allowed,
        "requires_review":         True,
        "manual_review":           True,
        "review_note":             "" if rent_check_pass else "RENT_CHECK_REQUIRED",
        "pitch_holds":             live_send_allowed,
        "commission_language":     COMMISSION_LANGUAGE,
    }


def _calc_owner_finance_manual_review(listing: dict, list_price: float) -> dict:
    offer_price, dp, balance, monthly = _calc_terms_offer_base(list_price)
    estimated_rent = float(listing.get("estimated_rent") or 0)
    taxes_insurance = _estimate_taxes_insurance(offer_price)
    repairs_vacancy_management = (
        _estimate_repairs_vacancy_management(estimated_rent) if estimated_rent else 0.0
    )
    estimated_cashflow = (
        estimated_rent - monthly - taxes_insurance - repairs_vacancy_management
        if estimated_rent else None
    )
    payment_to_rent_ratio = monthly / estimated_rent if estimated_rent else None

    return {
        "offer_type":              "owner_finance_manual_review",
        "list_price":              list_price,
        "owner_finance_offer":     offer_price,
        "purchase_price":          offer_price,
        "down_payment":            dp,
        "down_pct":                OF_DOWN_PCT * 100,
        "financed_balance":        balance,
        "monthly_payment":         monthly,
        "num_payments":            OF_NUM_PAYMENTS,
        "seller_rate":             OF_SELLER_RATE,
        "interest_rate":           OF_SELLER_RATE,
        "earnest":                 OF_EARNEST,
        "close_days":              OF_CLOSE_DAYS,
        "due_diligence_days":      OF_DD_DAYS,
        "estimated_rent":          estimated_rent,
        "estimated_taxes_insurance": taxes_insurance,
        "estimated_repairs_vacancy_management": repairs_vacancy_management,
        "estimated_monthly_cashflow": estimated_cashflow,
        "minimum_cashflow_required": MINIMUM_CASHFLOW_REQUIRED,
        "payment_to_rent_ratio":   payment_to_rent_ratio,
        "max_payment_to_rent_ratio": MAX_PAYMENT_TO_RENT_RATIO,
        "rent_check_status":       "MANUAL_REVIEW",
        "rent_check_pass":         False,
        "eligible_for_human_review": False,
        "approved_to_send":        bool(listing.get("approved_to_send")),
        "live_send_allowed":       False,
        "live_send_blocked":       True,
        "requires_review":         True,
        "manual_review":           True,
        "review_note":             "OWNER_FINANCE_MANUAL_REVIEW_100_125",
        "pitch_holds":             False,
        "commission_language":     COMMISSION_LANGUAGE,
    }


def _calc_cash_lowball(listing: dict, list_price: float) -> dict:
    arv     = float(listing.get("arv") or 0)
    repairs = float(listing.get("repairs") or 0)

    # ARV required for cash offers
    if not arv:
        return {
            "offer_type":         "no_arv",
            "list_price":         list_price,
            "skip_reason":        "ARV required for auto cash offer — send to manual review",
            "reason":             "ARV required for auto cash offer — send to manual review",
            "pitch_holds":        False,
            "commission_language": COMMISSION_LANGUAGE,
        }

    # ── Step 1: Buyer MAO ──────────────────────────────────────────────────────
    eff_repairs    = calc_effective_repairs(repairs, arv)
    buyer_mao      = calc_buyer_mao(arv, eff_repairs)
    assignment_fee = calc_assignment_fee(
        arv,
        buyer_mao,
        listing.get("assignment_fee_override"),
    )
    closing_buffer = calc_closing_buffer(buyer_mao)

    # ── Step 2: Contract MAO by buyer math ────────────────────────────────────
    buyer_math_cap = buyer_mao - assignment_fee - closing_buffer

    # ── Step 3: Contract MAO by visible spread arbitrage ─────────────────────
    req_spread = required_visible_spread(list_price)
    if req_spread is None:
        return {
            "offer_type":         "manual_review",
            "list_price":         list_price,
            "skip_reason":        "MANUAL REVIEW — $500k+ requires manual underwriting",
            "pitch_holds":        False,
            "commission_language": COMMISSION_LANGUAGE,
        }

    spread_cap = list_price - assignment_fee - req_spread

    # ── Step 4: Final max contract price ─────────────────────────────────────
    final_contract_mao = min(buyer_math_cap, spread_cap)

    if final_contract_mao <= 0:
        return {
            "offer_type":          "skip",
            "list_price":          list_price,
            "arv":                 arv,
            "repairs":             repairs,
            "effective_repairs":   eff_repairs,
            "buyer_mao":           buyer_mao,
            "assignment_fee":      assignment_fee,
            "closing_buffer":      closing_buffer,
            "buyer_math_cap":      buyer_math_cap,
            "spread_cap":          spread_cap,
            "required_spread":     req_spread,
            "final_contract_mao":  final_contract_mao,
            "skip_reason":         "SKIP — MAO BELOW ZERO. Numbers do not pencil.",
            "pitch_holds":         False,
            "commission_language": COMMISSION_LANGUAGE,
        }

    # ── Step 5: Offer range ───────────────────────────────────────────────────
    initial_offer  = round_down_1k(final_contract_mao * INITIAL_OFFER_LOW)   # 85%
    max_counter    = round_down_1k(final_contract_mao * INITIAL_OFFER_HIGH)  # 90%
    true_walkaway  = round_down_1k(final_contract_mao * TRUE_WALKAWAY_PCT)   # 100% internal
    cash_offer     = initial_offer

    # ── Step 6: Visible spread and buyer room check ────────────────────────────
    buyer_all_in    = cash_offer + assignment_fee
    visible_spread  = list_price - buyer_all_in
    spread_ok       = visible_spread >= req_spread
    spread_status   = "PASS" if spread_ok else "NO ARBITRAGE"

    buyer_has_room  = buyer_all_in < buyer_mao
    room_delta      = buyer_mao - buyer_all_in

    # ── Step 7: Limiting factor ────────────────────────────────────────────────
    if buyer_math_cap <= spread_cap:
        limiting_factor = "Buyer math is limiting the deal."
    else:
        limiting_factor = "Visible spread is limiting the deal."

    return {
        "offer_type":          "cash_lowball",
        "list_price":          list_price,
        "arv":                 arv,
        "repairs":             repairs,
        "effective_repairs":   eff_repairs,
        # MAO chain
        "buyer_mao":           buyer_mao,
        "assignment_fee":      assignment_fee,
        "closing_buffer":      closing_buffer,
        "buyer_math_cap":      buyer_math_cap,
        # Spread chain
        "required_spread":     req_spread,
        "spread_cap":          spread_cap,
        "limiting_factor":     limiting_factor,
        # Final
        "final_contract_mao":  final_contract_mao,
        "cash_offer":          cash_offer,
        "initial_offer":       initial_offer,
        "max_counter":         max_counter,
        "true_walkaway":       true_walkaway,
        "buyer_all_in":        buyer_all_in,
        "assign_price":        buyer_all_in,
        "visible_spread":      visible_spread,
        "spread_status":       spread_status,
        "spread_ok":           spread_ok,
        "buyer_has_room":      buyer_has_room,
        "room_delta":          room_delta,
        "your_fee_estimate":   assignment_fee,
        "pitch_holds":         spread_ok and buyer_has_room,
        "commission_language": COMMISSION_LANGUAGE,
    }
