"""
Offer calculator — Flip Man KISS Method

OWNER FINANCE ($30k-$80k):
  - Offer = full list price
  - Down = 5% — this IS the agent commission, nothing else
  - Balance = 100 payments at 0% interest to seller
  - Agent gets: exactly 5% of purchase price at closing from buyer's down
  - No separate 6% commission. No flat fee. Seller covers nothing.
  - Pitch check: 5% down >= 3% of list (always passes)
  - Your fee: buyer 12% down - your 5% down = 7% spread
  - Buyer terms: 12% rate / 10yr for positive cashflow

CASH LOWBALL ($80k+):
  - Offer = KISS tier % of list price
  - Agent: 6% of cash offer + $1,000 flat fee
  - Assign at +$10k
"""

from config import (
    MARKETS, OF_MAX_PRICE, OF_DOWN_PCT, OF_NUM_PAYMENTS, OF_SELLER_RATE,
    OF_BUYER_DOWN_PCT, OF_BUYER_RATE, OF_BUYER_TERM_YRS, OF_EARNEST,
    OF_CLOSE_DAYS, OF_DD_DAYS, KISS_TIERS, CL_AGENT_COMM_PCT, CL_FLAT_FEE,
    ASSIGNMENT_FEE, AT_LIST_PCT
)


def calculate_offer(listing: dict) -> dict | None:
    price = listing.get("list_price", 0)
    if not price:
        return None
    if price <= OF_MAX_PRICE:
        return _owner_finance(listing, price)
    else:
        return _cash_lowball(listing, price)


def _owner_finance(listing: dict, price: float) -> dict:
    """
    Flip Man KISS Owner Finance.
    5% down = agent commission. That is all.
    """
    dp      = price * OF_DOWN_PCT           # 5% = agent commission
    balance = price - dp
    monthly = balance / OF_NUM_PAYMENTS     # 0% interest

    # Agent gets exactly the 5% down — no more, no less
    agent_commission = dp
    at_list          = price * AT_LIST_PCT
    pitch_holds      = agent_commission >= at_list  # always true at 5%

    # Plan to sell — end buyer at 12% down, 12%/10yr
    buyer_down = price * OF_BUYER_DOWN_PCT
    buyer_bal  = price - buyer_down
    r          = OF_BUYER_RATE / 12
    n          = OF_BUYER_TERM_YRS * 12
    buyer_mo   = buyer_bal * r / (1 - (1 + r) ** -n)

    your_cashflow = buyer_mo - monthly
    your_fee      = buyer_down - dp   # 7% spread at closing

    return {
        "offer_type":           "owner_finance",
        "owner_finance_offer":  price,
        "cash_offer":           0,
        "down_payment":         dp,
        "down_pct":             OF_DOWN_PCT * 100,
        "financed_balance":     balance,
        "monthly_payment":      monthly,
        "num_payments":         OF_NUM_PAYMENTS,
        "seller_rate":          OF_SELLER_RATE,
        # Agent — 5% down IS the commission, nothing else
        "agent_commission":     agent_commission,
        "flat_fee":             0,
        "total_to_agent":       agent_commission,
        "at_list_commission":   at_list,
        "pitch_holds":          pitch_holds,
        # Plan to sell
        "buyer_down":           buyer_down,
        "buyer_balance":        buyer_bal,
        "buyer_monthly":        buyer_mo,
        "buyer_rate":           OF_BUYER_RATE * 100,
        "buyer_term_yrs":       OF_BUYER_TERM_YRS,
        "your_cashflow":        your_cashflow,
        "your_fee_estimate":    your_fee,
        # Closing
        "earnest":              OF_EARNEST,
        "due_diligence_days":   OF_DD_DAYS,
        "close_days":           OF_CLOSE_DAYS,
    }


def _cash_lowball(listing: dict, price: float) -> dict:
    """
    Flip Man KISS Cash Lowball.
    Agent: 6% of cash offer + $1,000 flat fee (separate from OF structure).
    """
    tier_pct     = _kiss_tier(price)
    offer        = price * (tier_pct / 100)
    assign_price = offer + ASSIGNMENT_FEE

    comm        = offer * CL_AGENT_COMM_PCT
    flat        = CL_FLAT_FEE
    agent_total = comm + flat
    at_list     = price * AT_LIST_PCT
    pitch_holds = agent_total >= at_list

    return {
        "offer_type":           "cash_lowball",
        "owner_finance_offer":  0,
        "cash_offer":           offer,
        "kiss_tier_pct":        tier_pct,
        "assign_fee":           ASSIGNMENT_FEE,
        "assign_price":         assign_price,
        "agent_commission":     comm,
        "flat_fee":             flat,
        "total_to_agent":       agent_total,
        "at_list_commission":   at_list,
        "pitch_holds":          pitch_holds,
        "your_fee_estimate":    ASSIGNMENT_FEE,
        "earnest":              500,
        "due_diligence_days":   10,
        "close_days":           14,
    }


def _kiss_tier(price: float) -> int:
    for max_price, pct in sorted(KISS_TIERS.items()):
        if price <= max_price:
            return pct
    return 65
