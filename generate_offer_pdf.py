"""
PDF offer generator — 229 Holdings LLC.
PDFs are agent-facing and must not expose internal underwriting math.
"""

from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor
from reportlab.lib.units import inch
from reportlab.platypus import (
SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
from reportlab.lib.enums import TA_RIGHT

PURPLE = HexColor("#6c63ff")
TEAL = HexColor("#00d4aa")
DARK = HexColor("#0a0a0f")
GRAY = HexColor("#7a7a9a")

COMMISSION_LINE = (
"Seller to handle any listing broker compensation per the existing listing agreement "
"from seller proceeds at closing."
)

def generate_offer_pdf(listing: dict, offer: dict, output_path: str) -> str:
address = listing.get("address", "Property Address")
offer_type = offer.get("offer_type", "owner_finance")

```
doc = SimpleDocTemplate(
    output_path,
    pagesize=letter,
    rightMargin=0.75 * inch,
    leftMargin=0.75 * inch,
    topMargin=0.75 * inch,
    bottomMargin=0.75 * inch,
)

styles = getSampleStyleSheet()
story = []

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
    ParagraphStyle("sub", fontSize=10, textColor=GRAY, fontName="Helvetica")
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
```

def _header(styles, offer_type):
label = "PURCHASE OFFER" if offer_type == "owner_finance" else "CASH PURCHASE OFFER"
data = [[
Paragraph('<font color="#6c63ff"><b>229 HOLDINGS LLC</b></font>', styles["Normal"]),
Paragraph(
f'<font color="#7a7a9a" size="9">{label}<br/>{datetime.now().strftime("%B %d, %Y")}</font>',
ParagraphStyle("r", alignment=TA_RIGHT, fontSize=9, fontName="Helvetica")
),
]]
t = Table(data, colWidths=["60%", "40%"])
t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
return t

def _of_body(offer: dict, styles) -> list:
price = _num(
offer.get("purchase_price")
or offer.get("owner_finance_offer")
or offer.get("offer")
or 0
)
dp = _num(offer.get("down_payment") or price * 0.05)
bal = _num(offer.get("financed_balance") or price - dp)
monthly = _num(offer.get("monthly_payment") or 0)
pmts = offer.get("term") or offer.get("num_payments") or 100
earnest = _num(offer.get("earnest") or 500)
dd = offer.get("due_diligence_days") or 10
close = offer.get("close_days") or 21
coe = (datetime.now() + timedelta(days=int(close))).strftime("%B %d, %Y")

```
rate = _num(
    offer.get("interest_rate")
    if offer.get("interest_rate") is not None
    else offer.get("interest")
    if offer.get("interest") is not None
    else offer.get("rate")
    if offer.get("rate") is not None
    else 0
)
rate_label = f"{rate:g}% Interest"

t1 = _grid([
    [_label("Purchase Price"), _label("Down Payment (5%)")],
    [_big(f"${price:,.0f}", "#6c63ff"), _big(f"${dp:,.0f}", "#00d4aa")],
    [_small("Purchase price"), _small("Paid at closing")],
], ["50%", "50%"])

t2 = _grid([
    [_label("Financed Balance"), _label("Monthly Payment to Seller"), _label("Term")],
    [_med(f"${bal:,.0f}"), _med(f"${monthly:,.0f}/mo"), _med(f"{pmts} payments")],
], ["33%", "33%", "34%"])

t3 = _grid([
    [_label("Interest Rate"), _label("Earnest Money"), _label("Close of Escrow")],
    [_med(rate_label), _med(f"${earnest:,.0f}"), _med(coe)],
], ["33%", "33%", "34%"])

legal = Paragraph(
    f'<font size="9" color="#7a7a9a">'
    f'<b>TERMS:</b> As-is, no repair requests, subject to standard due diligence. '
    f'Due diligence: {dd} days. Close timeline: 21-30 days. '
    f'Seller to satisfy any existing mortgages, taxes, liens, or title-clearing items from seller proceeds unless otherwise agreed in writing. '
    f'Buyer is purchasing for investment purposes.<br/><br/>'
    f'<b>COMMISSION:</b> {COMMISSION_LINE}'
    f'</font>',
    styles["Normal"]
)

return [t1, Spacer(1, 8), t2, Spacer(1, 8), t3, Spacer(1, 14), legal]
```

def _cl_body(offer: dict, styles) -> list:
cash_offer = _num(
offer.get("cash_offer")
or offer.get("initial_offer")
or offer.get("offer")
or 0
)
coe = (datetime.now() + timedelta(days=21)).strftime("%B %d, %Y")

```
t1 = _grid([
    [_label("Cash Offer"), _label("Earnest Money"), _label("Close of Escrow")],
    [_big(f"${cash_offer:,.0f}", "#00d4aa"), _med("$500"), _med(coe)],
], ["50%", "25%", "25%"])

legal = Paragraph(
    f'<font size="9" color="#7a7a9a">'
    f'<b>TERMS:</b> Cash close in 21-30 days. As-is, no repair requests. No financing contingency. Due diligence: 10 days. '
    f'Seller to satisfy any existing mortgages, taxes, liens, or title-clearing items from seller proceeds unless otherwise agreed in writing. '
    f'Buyer is purchasing for investment purposes.<br/><br/>'
    f'<b>COMMISSION:</b> {COMMISSION_LINE}'
    f'</font>',
    styles["Normal"]
)

return [t1, Spacer(1, 14), legal]
```

def _signature() -> list:
data = [[
Paragraph('<b>229 Holdings LLC</b>', getSampleStyleSheet()["Normal"]),
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
("LINEABOVE", (0, 0), (-1, 0), 1, HexColor("#e8e8f0")),
("TOPPADDING", (0, 0), (-1, -1), 12),
]))
return [t]

def _grid(data, widths):
t = Table(data, colWidths=widths)
t.setStyle(TableStyle([
("BACKGROUND", (0, 0), (-1, -1), HexColor("#f8f7ff")),
("BOX", (0, 0), (-1, -1), 0.5, HexColor("#e8e4ff")),
("INNERGRID", (0, 0), (-1, -1), 0.5, HexColor("#e8e4ff")),
("TOPPADDING", (0, 0), (-1, -1), 8),
("BOTTOMPADDING", (0, 0), (-1, -1), 8),
("LEFTPADDING", (0, 0), (-1, -1), 10),
("RIGHTPADDING", (0, 0), (-1, -1), 10),
("VALIGN", (0, 0), (-1, -1), "TOP"),
]))
return t

def _label(text):
return Paragraph(f'<font size="8" color="#7a7a9a">{text}</font>', getSampleStyleSheet()["Normal"])

def _big(text, color="#6c63ff"):
return Paragraph(f'<font size="20" color="{color}"><b>{text}</b></font>', getSampleStyleSheet()["Normal"])

def _med(text):
return Paragraph(f'<font size="14" color="#1a1a1a"><b>{text}</b></font>', getSampleStyleSheet()["Normal"])

def _small(text):
return Paragraph(f'<font size="9" color="#7a7a9a">{text}</font>', getSampleStyleSheet()["Normal"])

def _num(value, default=0):
try:
return float(value)
except (TypeError, ValueError):
return default
