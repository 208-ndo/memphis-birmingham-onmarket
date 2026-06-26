"""
PDF offer generator — Flip Man KISS Method
Owner Finance: 5% down = agent commission (no 6% + flat fee)
Cash Lowball: 6% of offer + $1,000 flat fee
"""

import os
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

PURPLE = HexColor("#6c63ff")
TEAL   = HexColor("#00d4aa")
DARK   = HexColor("#0a0a0f")
LIGHT  = HexColor("#f8f7ff")
GRAY   = HexColor("#7a7a9a")


def generate_offer_pdf(listing: dict, offer: dict, output_path: str) -> str:
    address    = listing.get("address", "Property Address")
    agent_name = listing.get("listing_agent", "Listing Agent")
    offer_type = offer.get("offer_type", "owner_finance")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch,
    )

    styles = getSampleStyleSheet()
    story  = []

    # Header
    story.append(_header(styles, offer_type))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=2, color=PURPLE))
    story.append(Spacer(1, 8))

    # Address + Agent
    story.append(Paragraph(address, ParagraphStyle("addr", fontSize=18, fontName="Helvetica-Bold", textColor=DARK)))
    story.append(Paragraph(f"Presented to: {agent_name}", ParagraphStyle("agent", fontSize=10, textColor=GRAY, fontName="Helvetica")))
    story.append(Spacer(1, 16))

    if offer_type == "owner_finance":
        story += _of_body(offer, styles)
    else:
        story += _cl_body(offer, styles)

    story.append(Spacer(1, 20))
    story += _signature()

    doc.build(story)
    return output_path


def _header(styles, offer_type):
    label = "SELLER FINANCED OFFER" if offer_type == "owner_finance" else "CASH AS-IS OFFER"
    data  = [[
        Paragraph('<font color="#6c63ff"><b>229 HOLDINGS LLC</b></font><br/><font size="8" color="#7a7a9a">229homebuyers.com</font>', styles["Normal"]),
        Paragraph(f'<font color="#7a7a9a" size="9">{label}<br/>{datetime.now().strftime("%B %d, %Y")}</font>', ParagraphStyle("r", alignment=TA_RIGHT, fontSize=9, fontName="Helvetica")),
    ]]
    t = Table(data, colWidths=["60%", "40%"])
    t.setStyle(TableStyle([("VALIGN", (0,0), (-1,-1), "TOP")]))
    return t


def _of_body(offer: dict, styles) -> list:
    """Owner Finance — 5% down = agent commission"""
    price   = offer.get("owner_finance_offer", 0)
    dp      = offer.get("down_payment", 0)
    dp_pct  = offer.get("down_pct", 5)
    bal     = offer.get("financed_balance", 0)
    monthly = offer.get("monthly_payment", 0)
    pmts    = offer.get("num_payments", 100)
    rate    = offer.get("seller_rate", 0)
    earnest = offer.get("earnest", 500)
    dd      = offer.get("due_diligence_days", 10)
    close   = offer.get("close_days", 21)
    coe     = (datetime.now() + timedelta(days=close)).strftime("%B %d, %Y")

    # Agent = 5% down only
    agent_comm = offer.get("total_to_agent", dp)
    at_list    = offer.get("at_list_commission", 0)

    # Commission banner
    banner_data = [[
        Paragraph(
            f'<font color="#00d4aa"><b>✓ AGENT COMMISSION FULLY PROTECTED</b></font><br/>'
            f'<font size="9" color="#a0a0c0">Agent commission: <b>${agent_comm:,.0f}</b> — paid from buyer\'s down payment at closing.<br/>'
            f'Agent nets ${agent_comm:,.0f} vs ${at_list:,.0f} from a traditional full-price sale.</font>',
            styles["Normal"]
        )
    ]]
    banner = Table(banner_data, colWidths=["100%"])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), HexColor("#1a1a26")),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("ROUNDEDCORNERS", (0,0), (-1,-1), 4),
    ]))

    # Main terms table
    terms = Table([
        [_label("Purchase Price"), _label("Down Payment (5% = Agent Commission)")],
        [_big(f"${price:,.0f}", "#6c63ff"), _big(f"${dp:,.0f}", "#00d4aa")],
        [_small("Seller receives full asking price"), _small(f"{dp_pct:.0f}% — goes to agent at closing")],
    ], colWidths=["50%", "50%"])
    terms.setStyle(_box_style())

    terms2 = Table([
        [_label("Financed Amount"), _label("Monthly Payment to Seller"), _label("Term")],
        [_med(f"${bal:,.0f}"), _med(f"${monthly:,.0f}/mo"), _med(f"{pmts} months")],
    ], colWidths=["33%", "33%", "34%"])
    terms2.setStyle(_box_style())

    terms3 = Table([
        [_label("Interest Rate"), _label("Earnest Money"), _label("Close of Escrow")],
        [_med("0% Interest Free" if rate == 0 else f"{rate}%"), _med(f"${earnest:,}"), _med(coe)],
    ], colWidths=["33%", "33%", "34%"])
    terms3.setStyle(_box_style())

    legal = Paragraph(
        f'<font size="9" color="#7a7a9a">'
        f'<b>AGENT COMMISSION:</b> The agent commission of ${agent_comm:,.0f} shall be paid '
        f'from the buyer\'s down payment at closing. The seller carries zero commission obligation. '
        f'In the event of dual agency, the buyer consents to the agent representing both parties, '
        f'subject to state regulations.<br/><br/>'
        f'<b>TERMS:</b> Due Diligence {dd} Days. As-Is subject to walk-through. '
        f'Buyer pays all closing costs minus unpaid mortgages, taxes, or liens. '
        f'Buyer will select closing attorney / title company / escrow company. '
        f'Buyer reserves right to assign contract.</font>',
        styles["Normal"]
    )

    return [banner, Spacer(1,12), terms, Spacer(1,8), terms2, Spacer(1,8), terms3, Spacer(1,12), legal]


def _cl_body(offer: dict, styles) -> list:
    """Cash Lowball — 6% of offer + $1,000 flat fee"""
    list_price   = offer.get("cash_offer", 0) / (offer.get("kiss_tier_pct", 40) / 100)
    cash_offer   = offer.get("cash_offer", 0)
    tier_pct     = offer.get("kiss_tier_pct", 40)
    assign_fee   = offer.get("assign_fee", 10000)
    assign_price = offer.get("assign_price", 0)
    comm         = offer.get("agent_commission", 0)
    flat         = offer.get("flat_fee", 1000)
    agent_total  = offer.get("total_to_agent", 0)
    at_list      = offer.get("at_list_commission", 0)
    coe          = (datetime.now() + timedelta(days=14)).strftime("%B %d, %Y")

    banner_data = [[
        Paragraph(
            f'<font color="#00d4aa"><b>✓ AGENT COMMISSION PROTECTED — CASH CLOSE</b></font><br/>'
            f'<font size="9" color="#a0a0c0">Agent commission: <b>${agent_total:,.0f}</b> (${comm:,.0f} + ${flat:,} flat fee) paid at closing.<br/>'
            f'Agent nets ${agent_total:,.0f} vs ${at_list:,.0f} at-list baseline.</font>',
            styles["Normal"]
        )
    ]]
    banner = Table(banner_data, colWidths=["100%"])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), HexColor("#1a1a26")),
        ("LEFTPADDING", (0,0), (-1,-1), 12),
        ("RIGHTPADDING", (0,0), (-1,-1), 12),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
    ]))

    terms = Table([
        [_label(f"Cash Offer (KISS {tier_pct}% of List)"), _label("Plan to Sell (Assign Price)")],
        [_big(f"${cash_offer:,.0f}", "#00d4aa"), _big(f"${assign_price:,.0f}", "#6c63ff")],
        [_small(f"List price x {tier_pct}%"), _small(f"Offer + ${assign_fee:,} assignment fee")],
    ], colWidths=["50%", "50%"])
    terms.setStyle(_box_style())

    terms2 = Table([
        [_label("Your Assignment Fee"), _label("Earnest Money"), _label("Close of Escrow")],
        [_med(f"${assign_fee:,}", "#00e676"), _med("$500"), _med(coe)],
    ], colWidths=["33%", "33%", "34%"])
    terms2.setStyle(_box_style())

    legal = Paragraph(
        f'<font size="9" color="#7a7a9a">'
        f'<b>TERMS:</b> As-Is. No repairs. No financing contingency. Cash close. '
        f'Buyer pays all closing costs minus unpaid mortgages, taxes, or liens. '
        f'Buyer reserves right to assign contract without seller consent.<br/><br/>'
        f'<b>COMMISSION:</b> ${agent_total:,.0f} total (${comm:,.0f} + ${flat:,} flat fee) paid at closing.</font>',
        styles["Normal"]
    )

    return [banner, Spacer(1,12), terms, Spacer(1,8), terms2, Spacer(1,12), legal]


def _signature() -> list:
    data = [[
        Paragraph('<b>Torian Wallace</b><br/><font size="9" color="#7a7a9a">229 Holdings LLC | 229homebuyers.com | 901-290-8408</font>', getSampleStyleSheet()["Normal"]),
        Paragraph('<font size="9" color="#7a7a9a">Date: ___________________<br/>Seller Signature: ___________________</font>',
                  ParagraphStyle("sr", alignment=TA_RIGHT, fontSize=9, fontName="Helvetica")),
    ]]
    t = Table(data, colWidths=["60%", "40%"])
    t.setStyle(TableStyle([("LINEABOVE", (0,0), (-1,0), 1, HexColor("#e8e8f0")), ("TOPPADDING", (0,0), (-1,-1), 12)]))
    return [t]


def _label(text):
    return Paragraph(f'<font size="8" color="#7a7a9a">{text}</font>', getSampleStyleSheet()["Normal"])

def _big(text, color="#6c63ff"):
    return Paragraph(f'<font size="20" color="{color}"><b>{text}</b></font>', getSampleStyleSheet()["Normal"])

def _med(text, color="#1a1a1a"):
    return Paragraph(f'<font size="14" color="{color}"><b>{text}</b></font>', getSampleStyleSheet()["Normal"])

def _small(text):
    return Paragraph(f'<font size="9" color="#7a7a9a">{text}</font>', getSampleStyleSheet()["Normal"])

def _box_style():
    return TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), HexColor("#f8f7ff")),
        ("BOX", (0,0), (-1,-1), 0.5, HexColor("#e8e4ff")),
        ("INNERGRID", (0,0), (-1,-1), 0.5, HexColor("#e8e4ff")),
        ("TOPPADDING", (0,0), (-1,-1), 8),
        ("BOTTOMPADDING", (0,0), (-1,-1), 8),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
    ])
