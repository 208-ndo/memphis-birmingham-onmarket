"""
PDF offer generator - 229 Holdings LLC.
PDFs are agent-facing and must not expose internal underwriting math.
"""

from datetime import datetime, timedelta
from html import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
HRFlowable,
Paragraph,
SimpleDocTemplate,
Spacer,
Table,
TableStyle,
)

PURPLE = HexColor("#6c63ff")
TEAL = HexColor("#00d4aa")
DARK = HexColor("#0a0a0f")
GRAY = HexColor("#7a7a9a")
LIGHT_BG = HexColor("#f8f7ff")
LIGHT_BORDER = HexColor("#e8e4ff")
RULE = HexColor("#e8e8f0")

CONTENT_WIDTH = 7.0 * inch

COMMISSION_LINE = (
"Seller to handle any listing broker compensation per the existing listing agreement "
"from seller proceeds at closing."
)
INVESTMENT_PURPOSE_LINE = "Buyer is purchasing for investment purposes."

def generate_offer_pdf(listing: dict, offer: dict, output_path: str) -> str:
address = _text(listing.get("address") or "Property Address")
offer_type = str(offer.get("offer_type") or "owner_finance").strip().lower()

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

story.append(
    Paragraph(
        address,
        ParagraphStyle(
            "addr",
            fontSize=18,
            fontName="Helvetica-Bold",
            textColor=DARK,
        ),
    )
)
story.append(
    Paragraph(
        "Presented to: Listing Agent",
        ParagraphStyle(
            "sub",
            fontSize=10,
            textColor=GRAY,
            fontName="Helvetica",
        ),
    )
)
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

def _header(styles, offer_type: str):
label = "PURCHASE OFFER" if offer_type == "owner_finance" else "CASH PURCHASE OFFER"
data = [
[
Paragraph(
'<font color="#6c63ff"><b>229 HOLDINGS LLC</b></font>',
styles["Normal"],
),
Paragraph(
f'<font color="#7a7a9a" size="9">{label}<br/>'
f'{datetime.now().strftime("%B %d, %Y")}</font>',
ParagraphStyle(
"header_right",
alignment=TA_RIGHT,
fontSize=9,
fontName="Helvetica",
),
),
]
]
table = Table(data, colWidths=_col_widths([0.60, 0.40]))
table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
return table

def _of_body(offer: dict, styles) -> list:
price = _num(
_first_value(
offer.get("purchase_price"),
offer.get("owner_finance_offer"),
offer.get("offer"),
default=0,
)
)
down_payment = _num(
_first_value(
offer.get("down_payment"),
default=price * 0.05,
)
)
balance = _num(
_first_value(
offer.get("financed_balance"),
default=price - down_payment,
)
)
monthly = _num(offer.get("monthly_payment"), default=0)
payments = _first_value(
offer.get("term"),
offer.get("num_payments"),
default=100,
)
earnest = _num(offer.get("earnest"), default=500)
due_diligence_days = int(_num(offer.get("due_diligence_days"), default=10))
close_days = int(_num(offer.get("close_days"), default=21))
close_date = (datetime.now() + timedelta(days=close_days)).strftime("%B %d, %Y")
rate = _num(
_first_value(
offer.get("interest_rate"),
offer.get("interest"),
offer.get("rate"),
default=0,
)
)

```
top_grid = _grid(
    [
        [_label("Purchase Price"), _label("Down Payment")],
        [_big(f"${price:,.0f}", "#6c63ff"), _big(f"${down_payment:,.0f}", "#00d4aa")],
        [_small("Purchase price"), _small("Paid at closing")],
    ],
    [0.50, 0.50],
)

middle_grid = _grid(
    [
        [_label("Financed Balance"), _label("Monthly Payment to Seller"), _label("Term")],
        [_med(f"${balance:,.0f}"), _med(f"${monthly:,.0f}/mo"), _med(f"{payments} payments")],
    ],
    [0.33, 0.33, 0.34],
)

bottom_grid = _grid(
    [
        [_label("Interest Rate"), _label("Earnest Money"), _label("Close of Escrow")],
        [_med(f"{rate:g}% Interest"), _med(f"${earnest:,.0f}"), _med(close_date)],
    ],
    [0.33, 0.33, 0.34],
)

legal = Paragraph(
    f'<font size="9" color="#7a7a9a">'
    f'<b>TERMS:</b> As-is, no repair requests, subject to standard due diligence. '
    f'Due diligence: {due_diligence_days} days. Close timeline: 21-30 days. '
    f'Seller to satisfy any existing mortgages, taxes, liens, or title-clearing items from seller proceeds unless otherwise agreed in writing. '
    f'{INVESTMENT_PURPOSE_LINE}<br/><br/>'
    f'<b>COMMISSION:</b> {COMMISSION_LINE}'
    f'</font>',
    styles["Normal"],
)

return [
    top_grid,
    Spacer(1, 8),
    middle_grid,
    Spacer(1, 8),
    bottom_grid,
    Spacer(1, 14),
    legal,
]
```

def _cl_body(offer: dict, styles) -> list:
cash_offer = _num(
_first_value(
offer.get("cash_offer"),
offer.get("initial_offer"),
offer.get("offer"),
default=0,
)
)
earnest = _num(offer.get("earnest"), default=500)
close_days = int(_num(offer.get("close_days"), default=21))
close_date = (datetime.now() + timedelta(days=close_days)).strftime("%B %d, %Y")

```
offer_grid = _grid(
    [
        [_label("Cash Offer"), _label("Earnest Money"), _label("Close of Escrow")],
        [_big(f"${cash_offer:,.0f}", "#00d4aa"), _med(f"${earnest:,.0f}"), _med(close_date)],
    ],
    [0.50, 0.25, 0.25],
)

legal = Paragraph(
    f'<font size="9" color="#7a7a9a">'
    f'<b>TERMS:</b> Cash close in 21-30 days. As-is, no repair requests. '
    f'No financing contingency. Due diligence: 10 days. '
    f'Seller to satisfy any existing mortgages, taxes, liens, or title-clearing items from seller proceeds unless otherwise agreed in writing. '
    f'{INVESTMENT_PURPOSE_LINE}<br/><br/>'
    f'<b>COMMISSION:</b> {COMMISSION_LINE}'
    f'</font>',
    styles["Normal"],
)

return [offer_grid, Spacer(1, 14), legal]
```

def _signature() -> list:
data = [
[
Paragraph("<b>229 Holdings LLC</b>", getSampleStyleSheet()["Normal"]),
Paragraph(
'<font size="9" color="#7a7a9a">'
"Date: ___________________<br/>"
"Seller Signature: ___________________"
"</font>",
ParagraphStyle(
"signature_right",
alignment=TA_RIGHT,
fontSize=9,
fontName="Helvetica",
),
),
]
]
table = Table(data, colWidths=_col_widths([0.60, 0.40]))
table.setStyle(
TableStyle(
[
("LINEABOVE", (0, 0), (-1, 0), 1, RULE),
("TOPPADDING", (0, 0), (-1, -1), 12),
]
)
)
return [table]

def _grid(data, widths):
table = Table(data, colWidths=_col_widths(widths))
table.setStyle(
TableStyle(
[
("BACKGROUND", (0, 0), (-1, -1), LIGHT_BG),
("BOX", (0, 0), (-1, -1), 0.5, LIGHT_BORDER),
("INNERGRID", (0, 0), (-1, -1), 0.5, LIGHT_BORDER),
("TOPPADDING", (0, 0), (-1, -1), 8),
("BOTTOMPADDING", (0, 0), (-1, -1), 8),
("LEFTPADDING", (0, 0), (-1, -1), 10),
("RIGHTPADDING", (0, 0), (-1, -1), 10),
("VALIGN", (0, 0), (-1, -1), "TOP"),
]
)
)
return table

def _label(text):
return Paragraph(
f'<font size="8" color="#7a7a9a">{_text(text)}</font>',
getSampleStyleSheet()["Normal"],
)

def _big(text, color="#6c63ff"):
return Paragraph(
f'<font size="20" color="{color}"><b>{_text(text)}</b></font>',
getSampleStyleSheet()["Normal"],
)

def _med(text):
return Paragraph(
f'<font size="14" color="#1a1a1a"><b>{_text(text)}</b></font>',
getSampleStyleSheet()["Normal"],
)

def _small(text):
return Paragraph(
f'<font size="9" color="#7a7a9a">{_text(text)}</font>',
getSampleStyleSheet()["Normal"],
)

def _col_widths(fractions):
return [CONTENT_WIDTH * float(fraction) for fraction in fractions]

def _first_value(*values, default=0):
for value in values:
if value is not None and value != "":
return value
return default

def _num(value, default=0):
try:
if isinstance(value, str):
value = value.replace("$", "").replace(",", "").strip()
if value.endswith("%"):
value = value[:-1].strip()
return float(value)
except (TypeError, ValueError):
return float(default)

def _text(value):
return escape(str(value))
