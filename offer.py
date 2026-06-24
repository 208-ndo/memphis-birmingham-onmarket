from config import OFFER
import logging

log = logging.getLogger(__name__)

def get_cash_offer_pct(list_price: float) -> float:
    """Get correct cash offer % based on KISS tier."""
    tiers = sorted(OFFER["cash_offer_pcts"].items())
    for ceiling, pct in tiers:
        if list_price <= ceiling:
            return pct
    return 0.65

def get_agent_flat_fee(list_price: float) -> int:
    """
    Flat fee on top of 6% commission.
    Ensures total to agent >= 3% at-list (pitch must hold).
    Sub-$50k = $1,000. $50k-$150k = $1,500.
    """
    if list_price < 50000:
        return OFFER["agent_flat_fee_sub50k"]
    return OFFER["agent_flat_fee_50_150k"]

def verify_pitch(total_to_agent: float, at_list_commission: float) -> bool:
    """
    Flip Man pitch check: agent must net MORE from our offer than a full-price sale.
    At-list = 3% buyer-side commission.
    If False, do NOT send the offer.
    """
    return total_to_agent >= at_list_commission

def calculate_offer(listing: dict) -> dict:
    """
    Calculate offer using Flip Man KISS method.

    $30k-$80k: Owner Finance
      - Offer = FULL list price (seller gets full ask)
      - Down = 5% (covers agent commission at close)
      - Balance / 100 payments @ 0% interest
      - Your fee = 12% buyer down minus 5% your down

    $80k+: Cash Lowball
      - $80k-$150k  = 40% of value
      - $150k-$300k = 50% of value
      - $300k-$750k = 60% of value
      - $750k-$1.5M = 65% of value
      - Assign at contract + $10k+
    """
    list_price = listing.get("list_price", 0)

    if list_price <= 0:
        log.warning(f"No list price for {listing.get('address')} -- skipping")
        return {}

    agent_flat_fee     = get_agent_flat_fee(list_price)
    at_list_commission = round(list_price * 0.03)  # 3% buyer-side baseline

    # ── OWNER FINANCE ($30k-$80k) ─────────────────────────────────────────
    if list_price <= OFFER["owner_finance_band_max"]:

        purchase_price  = list_price  # FULL list price — seller gets full ask
        down_payment    = round(purchase_price * OFFER["owner_finance_down_pct"])
        financed_amount = purchase_price - down_payment
        n_payments      = OFFER["owner_finance_payments"]
        monthly_payment = round(financed_amount / n_payments)

        # 6% commission + flat fee
        agent_commission = round(purchase_price * 0.06)
        total_to_agent   = agent_commission + agent_flat_fee
        pitch_holds      = verify_pitch(total_to_agent, at_list_commission)

        if not pitch_holds:
            log.warning(
                f"Pitch FAILS: {listing.get('address')} | "
                f"To agent: ${total_to_agent:,} < at-list: ${at_list_commission:,}"
            )

        # Your fee: charge end buyer 12% down, you put 5% down
        buyer_down          = round(purchase_price * OFFER["buyer_down_pct"])
        your_fee_estimate   = buyer_down - down_payment

        # End buyer monthly at 8%, 30yr
        buyer_financed = purchase_price - buyer_down
        buyer_rate     = 0.08 / 12
        buyer_n        = 360
        buyer_monthly  = round(
            buyer_financed * (buyer_rate * (1 + buyer_rate)**buyer_n)
            / ((1 + buyer_rate)**buyer_n - 1)
        ) if buyer_financed > 0 else 0

        buyer_cashflow_estimate = buyer_monthly - monthly_payment

        log.info(
            f"OF OFFER: {listing.get('address')} | "
            f"List: ${list_price:,} | Down: ${down_payment:,} | "
            f"Monthly: ${monthly_payment:,} | Fee: ~${your_fee_estimate:,} | "
            f"Pitch: {pitch_holds}"
        )

        return {
            "offer_type":             "owner_finance",
            "list_price":             list_price,
            "purchase_price":         purchase_price,
            "down_payment":           down_payment,
            "financed_amount":        financed_amount,
            "monthly_payment":        monthly_payment,
            "n_payments":             n_payments,
            "interest_rate":          0.0,
            "agent_commission":       agent_commission,
            "agent_flat_fee":         agent_flat_fee,
            "total_to_agent":         total_to_agent,
            "at_list_commission":     at_list_commission,
            "pitch_holds":            pitch_holds,
            "buyer_down_pct":         OFFER["buyer_down_pct"],
            "buyer_down":             buyer_down,
            "buyer_monthly":          buyer_monthly,
            "your_fee_estimate":      your_fee_estimate,
            "buyer_cashflow_estimate": buyer_cashflow_estimate,
            "earnest_money":          OFFER["earnest_money"],
            "due_diligence_days":     OFFER["due_diligence_days"],
            "close_days":             OFFER["close_days"],
            # Legacy fields for email_gen + pdf compatibility
            "owner_finance_offer":      purchase_price,
            "cash_offer":               0,          # FIX: was list_price*0.20 — caused Claude to
                                                    # reference a fake cash number in OF emails
            "monthly_payment_estimate": monthly_payment,
        }

    # ── CASH LOWBALL ($80k+) ──────────────────────────────────────────────
    else:
        cash_pct         = get_cash_offer_pct(list_price)
        cash_offer       = round(list_price * cash_pct)
        agent_commission = round(cash_offer * 0.06)
        total_to_agent   = agent_commission + agent_flat_fee
        pitch_holds      = verify_pitch(total_to_agent, at_list_commission)

        if not pitch_holds:
            log.warning(
                f"Cash pitch FAILS: {listing.get('address')} | "
                f"To agent: ${total_to_agent:,} < at-list: ${at_list_commission:,}"
            )

        assign_price    = cash_offer + OFFER["assignment_fee_target"]
        assignment_fee  = OFFER["assignment_fee_target"]

        log.info(
            f"CASH OFFER: {listing.get('address')} | "
            f"List: ${list_price:,} | Offer: ${cash_offer:,} ({int(cash_pct*100)}%) | "
            f"Assign: ${assign_price:,} | Fee: ${assignment_fee:,} | "
            f"Pitch: {pitch_holds}"
        )

        return {
            "offer_type":         "cash",
            "list_price":         list_price,
            "purchase_price":     cash_offer,
            "cash_offer":         cash_offer,
            "cash_offer_pct":     cash_pct,
            "assign_price":       assign_price,
            "assignment_fee":     assignment_fee,
            "agent_commission":   agent_commission,
            "agent_flat_fee":     agent_flat_fee,
            "total_to_agent":     total_to_agent,
            "at_list_commission": at_list_commission,
            "pitch_holds":        pitch_holds,
            "earnest_money":      OFFER["earnest_money"],
            "due_diligence_days": OFFER["due_diligence_days"],
            "close_days":         OFFER["close_days"],
            # Legacy fields
            "owner_finance_offer":      cash_offer,
            "monthly_payment_estimate": 0,
            "your_fee_estimate":        assignment_fee,
        }
