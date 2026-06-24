import os
import logging
from datetime import datetime, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

log = logging.getLogger(__name__)

# 229 Holdings Brand Colors
COLOR_DARK      = HexColor('#0a0a0f')
COLOR_PURPLE    = HexColor('#6c63ff')
COLOR_TEAL      = HexColor('#00d4aa')
COLOR_SURFACE   = HexColor('#1a1a24')
COLOR_LIGHT_TEXT = HexColor('#6b6b8a')
COLOR_WHITE     = HexColor('#ffffff')
COLOR_HOT       = HexColor('#ff4757')


def format_currency(amount):
    if not amount:
        return '$0'
    return f'${int(amount):,}'


def format_date(days_from_now=21):
    close_date = datetime.now() + timedelta(days=days_from_now)
    return close_date.strftime('%B %d, %Y')


def generate_offer_pdf(listing: dict, offer: dict, output_dir: str = 'data') -> str:
    """
    Generate a professional one-page offer PDF for a property.
    Returns the file path of the generated PDF.

    BUG FIX: agent_commission now correctly uses 6% (was 5%).
    """
    os.makedirs(output_dir, exist_ok=True)

    address             = listing.get('address', 'Property')
    city                = listing.get('city', '')
    state               = listing.get('state', '')
    agent_name          = listing.get('listing_agent', 'Listing Agent')
    list_price          = offer.get('list_price', 0)
    owner_finance_offer = offer.get('owner_finance_offer', 0)
    cash_offer          = offer.get('cash_offer', 0)
    monthly_payment     = offer.get('monthly_payment_estimate', 0)
    offer_type          = offer.get('offer_type', 'owner_finance')

    # ── 6% commission — corrected from 5% ──
    agent_commission  = round(list_price * 0.06)
    agent_flat_fee    = offer.get('agent_flat_fee', 1000)
    total_to_agent    = offer.get('total_to_agent', agent_commission + agent_flat_fee)
    at_list_comm      = round(list_price * 0.03)

    down_payment      = round(owner_finance_offer * 0.05)
    financed_amount   = owner_finance_offer - down_payment

    # Safe filename
    safe_addr = address.replace(' ', '_').replace(',', '').replace('/', '_')[:40]
    filename  = f"{output_dir}/offer_{safe_addr}_{datetime.now().strftime('%Y%m%d')}.pdf"

    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        rightMargin=0.6*inch,
        leftMargin=0.6*inch,
        topMargin=0.5*inch,
        bottomMargin=0.5*inch
    )

    styles   = getSampleStyleSheet()
    elements = []

    # ── HEADER ──────────────────────────────────────────────────────────────
    header_data = [[
        Paragraph(
            '<font color="#6c63ff"><b>229</b></font>'
            '<font color="#ffffff"> HOLDINGS LLC</font>',
            ParagraphStyle('logo', fontSize=20, textColor=white,
                           fontName='Helvetica-Bold', leading=24)
        ),
        Paragraph(
            '<font color="#6b6b8a">PURCHASE OFFER</font>',
            ParagraphStyle('offerLabel', fontSize=11, textColor=COLOR_LIGHT_TEXT,
                           fontName='Helvetica', alignment=TA_RIGHT)
        )
    ]]
    header_table = Table(header_data, colWidths=[4*inch, 3.3*inch])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), COLOR_DARK),
        ('PADDING',    (0, 0), (-1, -1), 14),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
        ('ROUNDEDCORNERS', [8, 8, 8, 8]),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.2*inch))

    # ── PROPERTY ADDRESS BLOCK ───────────────────────────────────────────────
    addr_style = ParagraphStyle('addr', fontSize=16, fontName='Helvetica-Bold',
                                textColor=COLOR_DARK, leading=20)
    sub_style  = ParagraphStyle('sub', fontSize=10, fontName='Helvetica',
                                textColor=COLOR_LIGHT_TEXT, leading=14)
    date_style = ParagraphStyle('date', fontSize=10, fontName='Helvetica',
                                textColor=COLOR_LIGHT_TEXT, alignment=TA_RIGHT)

    addr_data = [[
        [Paragraph(address, addr_style),
         Paragraph(
             f'{city}, {state} | Listed: {format_currency(list_price)} '
             f'| DOM: {listing.get("days_on_market", 0)} days',
             sub_style
         )],
        Paragraph(f'Date: {datetime.now().strftime("%B %d, %Y")}', date_style)
    ]]
    addr_table = Table(addr_data, colWidths=[4.5*inch, 2.8*inch])
    addr_table.setStyle(TableStyle([
        ('VALIGN',   (0, 0), (-1, -1), 'TOP'),
        ('PADDING',  (0, 0), (-1, -1), 0),
    ]))
    elements.append(addr_table)
    elements.append(Spacer(1, 0.15*inch))
    elements.append(HRFlowable(width='100%', thickness=1, color=HexColor('#2a2a3a')))
    elements.append(Spacer(1, 0.15*inch))

    # ── AGENT COMMISSION CALLOUT ─────────────────────────────────────────────
    # Shows agent their total payout vs. what they'd net from a full-price sale
    commission_data = [[
        Paragraph(
            '<b><font color="#ffffff">AGENT COMMISSION FULLY PROTECTED</font></b>'
            f'<br/><font color="#6b6b8a" size="8">You net {format_currency(total_to_agent)} — '
            f'more than the {format_currency(at_list_comm)} from a traditional full-price sale.</font>',
            ParagraphStyle('comm', fontSize=11, fontName='Helvetica-Bold',
                           textColor=white, leading=16)
        ),
        Paragraph(
            f'<b><font color="#00d4aa">{format_currency(total_to_agent)}</font></b>'
            f'<br/><font color="#6b6b8a" size="8">paid at closing</font>',
            ParagraphStyle('commAmt', fontSize=14, fontName='Helvetica-Bold',
                           textColor=white, alignment=TA_RIGHT, leading=18)
        )
    ]]
    comm_table = Table(commission_data, colWidths=[4*inch, 3.3*inch])
    comm_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#1a1a24')),
        ('LINEBELOW',  (0, 0), (-1, -1), 2, COLOR_TEAL),
        ('PADDING',    (0, 0), (-1, -1), 12),
        ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    elements.append(comm_table)
    elements.append(Spacer(1, 0.2*inch))

    # ── TWO OFFER COLUMNS ────────────────────────────────────────────────────
    section_label = ParagraphStyle('sectionLabel', fontSize=8, fontName='Helvetica-Bold',
                                   textColor=COLOR_LIGHT_TEXT, spaceAfter=4, leading=10)
    offer_price_style = ParagraphStyle('offerPrice', fontSize=24, fontName='Helvetica-Bold',
                                       textColor=COLOR_PURPLE, leading=28)
    cash_price_style  = ParagraphStyle('cashPrice', fontSize=24, fontName='Helvetica-Bold',
                                       textColor=COLOR_TEAL, leading=28)
    detail_label = ParagraphStyle('detailLabel', fontSize=8, fontName='Helvetica',
                                  textColor=COLOR_LIGHT_TEXT, leading=12)
    detail_value = ParagraphStyle('detailValue', fontSize=10, fontName='Helvetica-Bold',
                                  textColor=COLOR_DARK, leading=14)

    # Owner Finance Column
    of_content = [
        Paragraph('OPTION 1 — OWNER FINANCE', section_label),
        Paragraph(format_currency(owner_finance_offer), offer_price_style),
        Spacer(1, 6),
        Paragraph('Down Payment', detail_label),
        Paragraph(format_currency(down_payment), detail_value),
        Paragraph('Financed Amount', detail_label),
        Paragraph(format_currency(financed_amount), detail_value),
        Paragraph('Monthly Payment', detail_label),
        Paragraph(f'{format_currency(monthly_payment)}/mo', detail_value),
        Paragraph('Term', detail_label),
        Paragraph('100 months (8 yrs 4 mo)', detail_value),
        Paragraph('Interest Rate', detail_label),
        Paragraph('0% — Interest Free', detail_value),
        Spacer(1, 6),
        Paragraph(
            '<font color="#6c63ff">Seller receives full asking price</font>',
            ParagraphStyle('star', fontSize=9, fontName='Helvetica-Bold',
                           textColor=COLOR_PURPLE, leading=12)
        ),
    ]

    # Cash Column
    cash_content = [
        Paragraph('OPTION 2 — CASH AS-IS', section_label),
        Paragraph(format_currency(cash_offer), cash_price_style),
        Spacer(1, 6),
        Paragraph('Close Timeline', detail_label),
        Paragraph('7–14 Days', detail_value),
        Paragraph('Repairs Required', detail_label),
        Paragraph('NONE — Purchased As-Is', detail_value),
        Paragraph('Financing Contingency', detail_label),
        Paragraph('NONE — Cash Offer', detail_value),
        Paragraph('Inspection Period', detail_label),
        Paragraph('10 Days', detail_value),
        Paragraph('Earnest Money', detail_label),
        Paragraph('$500 (refundable)', detail_value),
        Spacer(1, 6),
        Paragraph(
            '<font color="#00d4aa">Fastest path to closing</font>',
            ParagraphStyle('star2', fontSize=9, fontName='Helvetica-Bold',
                           textColor=COLOR_TEAL, leading=12)
        ),
    ]

    offers_table = Table(
        [[of_content, cash_content]],
        colWidths=[3.55*inch, 3.55*inch]
    )
    offers_table.setStyle(TableStyle([
        ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
        ('BACKGROUND', (0, 0), (0, 0),   HexColor('#f8f7ff')),
        ('BACKGROUND', (1, 0), (1, 0),   HexColor('#f0fefb')),
        ('BOX',        (0, 0), (0, 0),   1.5, COLOR_PURPLE),
        ('BOX',        (1, 0), (1, 0),   1.5, COLOR_TEAL),
        ('PADDING',    (0, 0), (-1, -1), 14),
        ('LEFTPADDING',(1, 0), (1, 0),   18),
    ]))
    elements.append(offers_table)
    elements.append(Spacer(1, 0.2*inch))

    # ── CLOSING TERMS BAR ────────────────────────────────────────────────────
    terms_data = [[
        [Paragraph('CLOSE OF ESCROW', detail_label),
         Paragraph(format_date(14), detail_value)],
        [Paragraph('EARNEST MONEY', detail_label),
         Paragraph('$500', detail_value)],
        [Paragraph('INSPECTION PERIOD', detail_label),
         Paragraph('10 Days', detail_value)],
        [Paragraph('CONDITION', detail_label),
         Paragraph('As-Is', detail_value)],
    ]]
    terms_table = Table(terms_data, colWidths=[1.8*inch, 1.8*inch, 1.8*inch, 1.9*inch])
    terms_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f5f5f8')),
        ('BOX',        (0, 0), (-1, -1), 1, HexColor('#2a2a3a')),
        ('LINEAFTER',  (0, 0), (2, 0),   0.5, HexColor('#2a2a3a')),
        ('PADDING',    (0, 0), (-1, -1), 10),
        ('VALIGN',     (0, 0), (-1, -1), 'TOP'),
    ]))
    elements.append(terms_table)
    elements.append(Spacer(1, 0.2*inch))

    # ── CLOSING COSTS NOTE ───────────────────────────────────────────────────
    elements.append(Paragraph(
        '<font color="#6b6b8a">Closing Costs: Buyer will pay all closing costs minus any unpaid mortgages, '
        'taxes, or liens. Buyer reserves right to assign contract. '
        'Closing location selected by Buyer.</font>',
        ParagraphStyle('note', fontSize=8, fontName='Helvetica',
                       textColor=COLOR_LIGHT_TEXT, leading=12)
    ))
    elements.append(Spacer(1, 0.15*inch))
    elements.append(HRFlowable(width='100%', thickness=1, color=HexColor('#2a2a3a')))
    elements.append(Spacer(1, 0.15*inch))

    # ── FOOTER / SIGNATURE BLOCK ─────────────────────────────────────────────
    footer_data = [[
        [
            Paragraph('<b>Michael</b>',
                      ParagraphStyle('sig', fontSize=11, fontName='Helvetica-Bold',
                                     textColor=COLOR_DARK, leading=14)),
            Paragraph('229 Holdings LLC',
                      ParagraphStyle('sigco', fontSize=9, fontName='Helvetica',
                                     textColor=COLOR_LIGHT_TEXT, leading=12)),
            Paragraph('michael@229holdings.com | 229homebuyers.com',
                      ParagraphStyle('sigco2', fontSize=9, fontName='Helvetica',
                                     textColor=COLOR_LIGHT_TEXT, leading=12)),
        ],
        Paragraph(
            f'<font color="#6b6b8a">Presented to: {agent_name}</font><br/>'
            f'<font color="#6b6b8a">{address}, {city} {state}</font>',
            ParagraphStyle('recipient', fontSize=9, fontName='Helvetica',
                           textColor=COLOR_LIGHT_TEXT, alignment=TA_RIGHT, leading=13)
        )
    ]]
    footer_table = Table(footer_data, colWidths=[4*inch, 3.3*inch])
    footer_table.setStyle(TableStyle([
        ('VALIGN',  (0, 0), (-1, -1), 'MIDDLE'),
        ('PADDING', (0, 0), (-1, -1), 0),
    ]))
    elements.append(footer_table)

    # Build PDF
    try:
        doc.build(elements)
        log.info(f"PDF generated: {filename}")
        return filename
    except Exception as e:
        log.error(f"PDF generation failed: {e}")
        return None
