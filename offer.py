from config import OFFER
import logging

log = logging.getLogger(__name__)


def get_cash_offer_pct(list_price: float) -> float:
    """
    Get correct KISS cash offer % based on price tier.
    Torian hard rule: 20% on target inventory (sub-$75k).
    Do NOT move off 20% on these houses.
    """
    tiers = sorted(OFFER["cash_offer_pcts"].items())
    for ceiling, pct in tiers:
        if list_price <= ceiling:
            return pct
    return 0.65


def get_agent_flat_fee(list_price: float) -> int:
    """
    Flat fee added on top of 6% commission.
    Ensures total to agent >= 3% at-list (pitch must hold).
    Sub-$50k = $1,000. $50k-$150k = $1,500.
    Break-even at $1k flat = list ~$55,556.
    Above that the pitch collapses without the bump to $1,500.
    """
    if list_price < 50000:
        return OFFER["agent_flat_fee_sub50k"]
    return OFFER["agent_flat_fee_50_150k"]


def verify_pitch(total_to_agent: float, at_list_commission: float) -> bool:
    """
    Flip Man core pitch check.
    Agent must net MORE from our offer than a full-price retail sale.
    At-list = 3% of list price (buyer-side commission baseline).
    If False = do NOT send this offer.
    """
    return total_to_agent >= at_list_commission


def calc_buyer_mao(arv: float, repair_estimate: float = 0,
                   profit_margin: float = 0.20) -> float:
    """
    Maximum Allowable Offer for a cash buyer/flipper.
    MAO = ARV x (1 - profit margin) - repairs
    Standard: 20% profit margin.
    Used to verify our assign price leaves room for buyer profit.
    """
    return round(arv * (1 - profit_margin) - repair_estimate)


def calculate_offer(listing: dict) -> dict:
    """
    Calculate offer using Flip Man KISS method.

    $30k-$75k -> Owner Finance at FULL list price
      Seller gets full asking price.
      5% down covers agent commission at close.
      Balance / 100 monthly payments at 0% interest.
      You wrap to end buyer at 12% down + 8% interest.
      Your fee = buyer 12% down minus your 5% down = spread.
      Your monthly cashflow = buyer monthly minus seller monthly.

    $75k+ -> Cash Lowball (KISS tiers)
      <= $75k  = 20% of value  (Torian: do NOT move off this)
      $75k-$150k = 40%
      $150k-$300k = 50%
      $300k-$750k = 60%
      $750k-$1.5M = 65%
      Assign at contract price + $10k fee.
      Buyer MAO check confirms room for buyer profit.
    """
    list_price = listing.get("list_price", 0)
    if list_price <= 0:
        log.warning(f"No list price for {listing.get('address')} -- skipping")
        return {}

    agent_flat_fee     = get_agent_flat_fee(list_price)
    at_list_commission = round(list_price * 0.03)

    # ── OWNER FINANCE ($30k-$75k) ─────────────────────────────────────────
    if list_price <= OFFER["owner_finance_band_max"]:

        purchase_price  = list_price
        down_payment    = round(purchase_price * OFFER["owner_finance_down_pct"])
        financed_amount = purchase_price - down_payment
        n_payments      = OFFER["owner_finance_payments"]
        monthly_payment = round(financed_amount / n_payments)

        # Agent gets 6% of full purchase price + flat fee
        agent_commission = round(purchase_price * 0.06)
        total_to_agent   = agent_commission + agent_flat_fee
        pitch_holds      = verify_pitch(total_to_agent, at_list_commission)

        if not pitch_holds:
            log.warning(
                f"Pitch FAILS | {listing.get('address')} | "
                f"To agent: ${total_to_agent:,} < at-list: ${at_list_commission:,} | "
                f"Bump flat fee or skip"
            )

        # Your fee: you put 5% down, charge end buyer 12% down
        buyer_down        = round(purchase_price * OFFER["buyer_down_pct"])
        your_fee_estimate = buyer_down - down_payment

        # What you plan to sell at = same purchase price
        plan_to_sell = purchase_price

        # End buyer monthly at 8% over 30 years
        buyer_financed = purchase_price - buyer_down
        buyer_rate     = OFFER["buyer_interest_rate"] / 12
        buyer_n        = OFFER["buyer_loan_months"]
        buyer_monthly  = round(
            buyer_financed * (buyer_rate * (1 + buyer_rate) ** buyer_n)
            / ((1 + buyer_rate) ** buyer_n - 1)
        ) if buyer_financed > 0 else 0

        # Your monthly cashflow = buyer monthly minus what you owe seller
        your_monthly_cashflow = buyer_monthly - monthly_payment

        log.info(
            f"OF OFFER | {listing.get('address')} | "
            f"List: ${list_price:,} | "
            f"Down: ${down_payment:,} | "
            f"Seller monthly: ${monthly_payment:,}/mo | "
            f"Buyer down: ${buyer_down:,} | "
            f"Buyer monthly: ${buyer_monthly:,}/mo | "
            f"Your fee: ~${your_fee_estimate:,} | "
            f"Your cashflow: ${your_monthly_cashflow:,}/mo | "
            f"Agent gets: ${total_to_agent:,} vs at-list: ${at_list_commission:,} | "
            f"Pitch: {pitch_holds}"
        )

        return {
            # Core offer
            "offer_type":              "owner_finance",
            "list_price":              list_price,
            "purchase_price":          purchase_price,
            "plan_to_sell":            plan_to_sell,
            "down_payment":            down_payment,
            "financed_amount":         financed_amount,
            "monthly_payment":         monthly_payment,
            "n_payments":              n_payments,
            "interest_rate":           0.0,
            # Agent numbers
            "agent_commission":        agent_commission,
            "agent_flat_fee":          agent_flat_fee,
            "total_to_agent":          total_to_agent,
            "at_list_commission":      at_list_commission,
            "pitch_holds":             pitch_holds,
            # Your numbers
            "buyer_down_pct":          OFFER["buyer_down_pct"],
            "buyer_down":              buyer_down,
            "buyer_monthly":           buyer_monthly,
            "your_fee_estimate":       your_fee_estimate,
            "your_monthly_cashflow":   your_monthly_cashflow,
            "buyer_cashflow_estimate": your_monthly_cashflow,
            # Closing terms
            "earnest_money":           OFFER["earnest_money"],
            "due_diligence_days":      OFFER["due_diligence_days"],
            "close_days":              OFFER["close_days"],
            # Legacy fields for email_gen + pdf compatibility
            "owner_finance_offer":      purchase_price,
            "cash_offer":               0,
            "monthly_payment_estimate": monthly_payment,
        }

    # ── CASH LOWBALL ($75k+) ──────────────────────────────────────────────
    else:

        cash_pct         = get_cash_offer_pct(list_price)
        cash_offer       = round(list_price * cash_pct)
        agent_commission = round(cash_offer * 0.06)
        total_to_agent   = agent_commission + agent_flat_fee
        pitch_holds      = verify_pitch(total_to_agent, at_list_commission)

        if not pitch_holds:
            log.warning(
                f"Cash pitch FAILS | {listing.get('address')} | "
                f"To agent: ${total_to_agent:,} < at-list: ${at_list_commission:,} | "
                f"Bump flat fee or skip"
            )

        # Plan to sell = assign price
        assignment_fee = OFFER["assignment_fee_target"]
        assign_price   = cash_offer + assignment_fee
        plan_to_sell   = assign_price

        # Buyer MAO check — confirm assign price leaves room for buyer profit
        # Using list price as ARV proxy (distressed listing, no rehab estimate)
        buyer_mao_price = calc_buyer_mao(
            arv=list_price,
            repair_estimate=0,
            profit_margin=0.20
        )
        buyer_has_room = assign_price <= buyer_mao_price

        # Buyer profit if they pay our assign price
        buyer_gross_profit = buyer_mao_price - assign_price

        log.info(
            f"CASH OFFER | {listing.get('address')} | "
            f"List: ${list_price:,} | "
            f"Offer: ${cash_offer:,} ({int(cash_pct * 100)}%) | "
            f"Assign at: ${assign_price:,} | "
            f"Fee: ${assignment_fee:,} | "
            f"Buyer MAO: ${buyer_mao_price:,} | "
            f"Buyer room: {buyer_has_room} | "
            f"Agent gets: ${total_to_agent:,} vs at-list: ${at_list_commission:,} | "
            f"Pitch: {pitch_holds}"
        )

        return {
            # Core offer
            "offer_type":         "cash",
            "list_price":         list_price,
            "purchase_price":     cash_offer,
            "cash_offer":         cash_offer,
            "cash_offer_pct":     cash_pct,
            "plan_to_sell":       plan_to_sell,
            "assign_price":       assign_price,
            "assignment_fee":     assignment_fee,
            # Buyer numbers
            "buyer_mao":          buyer_mao_price,
            "buyer_has_room":     buyer_has_room,
            "buyer_gross_profit": buyer_gross_profit,
            # Agent numbers
            "agent_commission":   agent_commission,
            "agent_flat_fee":     agent_flat_fee,
            "total_to_agent":     total_to_agent,
            "at_list_commission": at_list_commission,
            "pitch_holds":        pitch_holds,
            # Closing terms
            "earnest_money":      OFFER["earnest_money"],
            "due_diligence_days": OFFER["due_diligence_days"],
            "close_days":         OFFER["close_days"],
            # Legacy fields
            "owner_finance_offer":      cash_offer,
            "monthly_payment_estimate": 0,
            "your_fee_estimate":        assignment_fee,
        }
