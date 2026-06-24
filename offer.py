from config import OFFER

def calculate_offer(listing: dict) -> dict:
    """
    Calculate offer amounts using KISS formula from Zompz skill.
    Owner Finance: 90% of list price (seller gets full price on terms)
    Cash: 65% of list price (ARV estimate)
    """
    list_price = listing.get("list_price", 0)
    sqft = listing.get("sqft", 0) or 0

    # Owner Finance Offer (primary strategy - seller gets near full price)
    owner_finance_offer = round(list_price * OFFER["owner_finance_arv_pct"])

    # Cash Offer (secondary - deep discount)
    cash_offer = round(list_price * OFFER["cash_arv_pct"])

    # Rough repair estimate
    repair_estimate = sqft * OFFER["repair_estimate_per_sqft"] if sqft else None

    # Assignment fee target
    assignment_fee = OFFER["assignment_fee"]

    # Net to seller on cash deal
    net_to_seller_cash = cash_offer - assignment_fee

    # Monthly payment estimate for owner finance (30yr @ 8%)
    monthly_payment = None
    if owner_finance_offer > 0:
        rate = 0.08 / 12
        n = 360
        monthly_payment = round(owner_finance_offer * (rate * (1 + rate)**n) / ((1 + rate)**n - 1))

    return {
        "list_price": list_price,
        "owner_finance_offer": owner_finance_offer,
        "cash_offer": cash_offer,
        "repair_estimate": repair_estimate,
        "assignment_fee": assignment_fee,
        "net_to_seller_cash": net_to_seller_cash,
        "monthly_payment_estimate": monthly_payment,
        "offer_type": "owner_finance" if list_price <= 200000 else "cash",
    }
