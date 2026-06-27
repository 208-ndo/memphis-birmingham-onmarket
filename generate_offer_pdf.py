"""
PDF offer generator — 229 Holdings LLC
Clean professional offer document. No strategy exposed.
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
GRAY   = HexColor("#7a7a9a")
LIGHT  = HexColor("#f8f7ff")


def generate_offer_pdf(listing: dict, offer: dict, output_path: str) -> str:
    address    = listing.get("address", "Property Address")
    offer_type = offer.get("offer_type", "owner_finance")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    story  = []

    story.append(_header(styles, offer_type))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=2, color=PURPLE))
    story.append(Spacer(1, 8))

    story.append(Paragraph(
        address,
        ParagraphStyle("addr", fontSize=18, fontName="Helvetica-Bold", textColor=DARK)
    ))
    story.append(Paragraph(
        "Presented to: Listing Agent",
        ParagraphStyle("agent", fontSize=10, textColor=GRAY, fontName="Helvetica")
    ))
    story.append(Spacer(1, 20))

    if offer_type == "owner_finance":
        story += _of_body(offer, styles)
    else:
        story += _cl_body(offer, styles)

    story.append(Spacer(1, 24))
    story += _signature()

    doc.build(story)
    return output_path


# ─── Header ────────────────────────────────────────────────────────────────────

def _header(styles, offer_type):
    label = "PURCHASE OFFER" if offer_type == "owner_finance" else "CASH PURCHASE OFFER"
    data = [[
        Paragraph(
            '<font color="#6c63ff"><b>229 HOLDINGS LLC</b></font>',
            styles["Normal"]
        ),
        Paragraph(
            f'<font color="#7a7a9a" size="9">{label}<br/>{datetime.now().strftime("%B %d, %Y")}</font>',
            ParagraphStyle("r", alignment=TA_RIGHT, fontSize=9, fontName="Helvetica")
        ),
    ]]
    t = Table(data, colWidths=["60%", "40%"])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    return t


# ─── Owner Finance Body ─────────────────────────────────────────────────────────

def _of_body(offer: dict, styles) -> list:
    price   = offer.get("owner_finance_offer", 0)
    dp      = offer.get("down_payment", 0)
    bal     = offer.get("financed_balance", 0)
    monthly = offer.get("monthly_payment", 0)
    pmts    = offer.get("num_payments", 100)
    earnest = offer.get("earnest", 500)
    dd      = offer.get("due_diligence_days", 10)
    close   = offer.get("close_days", 21)
    coe     = (datetime.now() + timedelta(days=close)).strftime("%B %d, %Y")

    agent_total = offer.get("total_to_agent", dp)
    at_list     = offer.get("at_list_commission", 0)

    # Commission banner — agent pitch only
    banner = _banner(
        f'AGENT COMMISSION FULLY PROTECTED',
        f'Agent receives <b>${agent_total:,.0f}</b> at closing, '
        f'paid from buyer\'s down payment. '
        f'That\'s ${agent_total - at_list:,.0f} more than a standard full-price sale commission.',
        styles
    )

    # Offer terms — clean, no strategy labels
    terms = Table([
        [_label("Purchase Price"),          _label("Down Payment")],
        [_big(f"${price:,.0f}", "#6c63ff"), _big(f"${dp:,.0f}", "#00d4aa")],
        [_small("Full asking price"),        _small("Paid at closing")],
    ], colWidths=["50%", "50%"])
    terms.setStyle(_box_style())

    terms2 = Table([
        [_label("Financed Balance"),  _label("Monthly Payment"),       _label("Term")],
        [_med(f"${bal:,.0f}"),        _med(f"${monthly:,.0f}/month"),  _med(f"{pmts} payments")],
    ], colWidths=["33%", "33%", "34%"])
    terms2.setStyle(_box_style())

    terms3 = Table([
        [_label("Interest Rate"),  _label("Earnest Money"),  _label("Close of Escrow")],
        [_med("0% — Interest Free"), _med(f"${earnest:,}"), _med(coe)],
    ], colWidths=["33%", "33%", "34%"])
    terms3.setStyle(_box_style())

    legal = Paragraph(
        f'<font size="9" color="#7a7a9a">'
        f'<b>TERMS:</b> As-Is subject to walk-through. Due diligence period: {dd} days. '
        f'Buyer pays all closing costs minus unpaid mortgages, taxes, or liens. '
        f'Buyer will select closing attorney / title company. '
        f'Buyer reserves right to assign contract.<br/><br/>'
        f'<b>AGENT COMMISSION:</b> ${agent_total:,.0f} paid from buyer\'s down payment at closing. '
        f'Seller carries zero commission obligation.'
        f'</font>',
        styles["Normal"]
    )

    return [banner, Spacer(1, 12), terms, Spacer(1, 8), terms2, Spacer(1, 8), terms3, Spacer(1, 14), legal]


# ─── Cash Lowball Body ──────────────────────────────────────────────────────────

def _cl_body(offer: dict, styles) -> list:
    cash_offer  = offer.get("cash_offer", 0)
    comm        = offer.get("agent_commission", 0)
    flat        = offer.get("flat_fee", 1000)
    agent_total = offer.get("total_to_agent", 0)
    at_list     = offer.get("at_list_commission", 0)
    coe         = (datetime.now() + timedelta(days=14)).strftime("%B %d, %Y")

    banner = _banner(
        'AGENT COMMISSION PROTECTED — CASH CLOSE',
        f'Agent receives <b>${agent_total:,.0f}</b> (commission + flat fee) at closing. '
        f'${agent_total - at_list:,.0f} more than a standard at-list commission.',
        styles
    )

    terms = Table([
        [_label("Cash Offer"),               _label("Earnest Money"),  _label("Close of Escrow")],
        [_big(f"${cash_offer:,.0f}", "#00d4aa"), _med("$500"),         _med(coe)],
    ], colWidths=["50%", "25%", "25%"])
    terms.setStyle(_box_style())

    legal = Paragraph(
        f'<font size="9" color="#7a7a9a">'
        f'<b>TERMS:</b> As-Is. No repairs. No financing contingency. Cash close. '
        f'Buyer pays all closing costs minus unpaid mortgages, taxes, or liens. '
        f'Buyer reserves right to assign contract without seller consent.<br/><br/>'
        f'<b>COMMISSION:</b> ${agent_total:,.0f} total (${comm:,.0f} commission + ${flat:,} flat fee) paid at closing.'
        f'</font>',
        styles["Normal"]
    )

    return [banner, Spacer(1, 12), terms, Spacer(1, 14), legal]


# ─── Shared helpers ─────────────────────────────────────────────────────────────

def _banner(title: str, body: str, styles) -> Table:
    data = [[
        Paragraph(
            f'<font color="#00d4aa"><b>✓ {title}</b></font>'
            f'<br/><font size="9" color="#a0a0c0">{body}</font>',
            styles["Normal"]
        )
    ]]
    t = Table(data, colWidths=["100%"])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), HexColor("#1a1a26")),
        ("LEFTPADDING",   (0, 0), (-1, -1), 12),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 12),
        ("TOPPADDING",    (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))
    return t


def _signature() -> list:
    data = [[
        Paragraph(
            '<b>229 Holdings LLC</b>',
            getSampleStyleSheet()["Normal"]
        ),
        Paragraph(
            '<font size="9" color="#7a7a9a">'
            'Date: ___________________<br/>'
            'Seller Signature: ___________________'
            '</font>',
            ParagraphStyle("sr", alignment=TA_RIGHT, fontSize=9, fontName="Helvetica")
        ),
    ]]
    t = Table(data, colWidths=["60%", "40%"])
    t.setStyle(TableStyle([
        ("LINEABOVE",   (0, 0), (-1, 0), 1, HexColor("#e8e8f0")),
        ("TOPPADDING",  (0, 0), (-1, -1), 12),
    ]))
    return [t]


def _label(text):
    return Paragraph(
        f'<font size="8" color="#7a7a9a">{text}</font>',
        getSampleStyleSheet()["Normal"]
    )

def _big(text, color="#6c63ff"):
    return Paragraph(
        f'<font size="20" color="{color}"><b>{text}</b></font>',
        getSampleStyleSheet()["Normal"]
    )

def _med(text, color="#1a1a1a"):
    return Paragraph(
        f'<font size="14" color="{color}"><b>{text}</b></font>',
        getSampleStyleSheet()["Normal"]
    )

def _small(text):
    return Paragraph(
        f'<font size="9" color="#7a7a9a">{text}</font>',
        getSampleStyleSheet()["Normal"]
    )

def _box_style():
    return TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), HexColor("#f8f7ff")),
        ("BOX",           (0, 0), (-1, -1), 0.5, HexColor("#e8e4ff")),
        ("INNERGRID",     (0, 0), (-1, -1), 0.5, HexColor("#e8e4ff")),
        ("TOPPADDING",    (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 10),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ])
