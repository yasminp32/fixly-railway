# core/utils.py

from decimal import Decimal, ROUND_HALF_UP
from num2words import num2words
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from django.conf import settings
from pathlib import Path
import os
def generate_po_number():
    import uuid
    return f"PO-{uuid.uuid4().hex[:8].upper()}"

def q2(x: Decimal) -> Decimal:
    return (x or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def recompute_purchase_order_totals(purchase_order):
    subtotal = Decimal("0.00")
    total_discount = Decimal("0.00")
    total_tax = Decimal("0.00")

    for item in purchase_order.items.all():
        qty = Decimal(item.qty or 0)
        unit_price = Decimal(item.unit_price or 0)
        discount_percent = Decimal(item.discount_percent or 0)
        tax_percent = Decimal(item.tax_percent or 0)

        line_subtotal = q2(qty * unit_price)
        discount_amount = q2((line_subtotal * discount_percent) / Decimal("100"))
        taxable_amount = q2(line_subtotal - discount_amount)
        tax_amount = q2((taxable_amount * tax_percent) / Decimal("100"))
        line_total = q2(taxable_amount + tax_amount)

        item.line_subtotal = line_subtotal
        item.discount_amount = discount_amount
        item.tax_amount = tax_amount
        item.line_total = line_total
        item.save(update_fields=["line_subtotal", "discount_amount", "tax_amount", "line_total"])

        subtotal += line_subtotal
        total_discount += discount_amount
        total_tax += tax_amount

    subtotal = q2(subtotal)
    total_discount = q2(total_discount)
    total_tax = q2(total_tax)

    shipping = Decimal(purchase_order.shipping_charges or 0)
    adjustment = Decimal(purchase_order.adjustment or 0)

    grand_total = q2(subtotal - total_discount + total_tax + q2(shipping) + q2(adjustment))

    purchase_order.subtotal = subtotal
    purchase_order.total_discount = total_discount
    purchase_order.total_tax = total_tax
    purchase_order.grand_total = grand_total

    purchase_order.save(update_fields=["subtotal", "total_discount", "total_tax", "grand_total"])
#quatation
from decimal import Decimal, ROUND_HALF_UP

Q = Decimal("0.01")

def money(x) -> Decimal:
    return (Decimal(str(x or "0"))).quantize(Q, rounding=ROUND_HALF_UP)

def normalize_state(s: str) -> str:
    return (s or "").strip().lower()

def gst_treatment_from_states(customer_state: str, shop_state: str):
    """
    customer_state == shop_state => INTRA => CGST+SGST
    else => INTER => IGST
    """
    cs = normalize_state(customer_state)
    ss = normalize_state(shop_state)

    if cs and ss and cs == ss:
        return {"treatment": "INTRA_STATE", "tax_type": "CGST_SGST"}
    return {"treatment": "INTER_STATE", "tax_type": "IGST"}

def calc_line(qty, rate, gst_rate, treatment: str):
    """
    treatment: 'INTRA_STATE' or 'INTER_STATE'
    """
    qty = Decimal(str(qty))
    rate = Decimal(str(rate))
    gst_rate = Decimal(str(gst_rate))

    taxable = money(qty * rate)
    tax_total = money(taxable * gst_rate / Decimal("100"))

    if treatment == "INTRA_STATE":
        cgst = money(tax_total / Decimal("2"))
        sgst = money(tax_total - cgst)
        igst = Decimal("0.00")
    else:
        cgst = Decimal("0.00")
        sgst = Decimal("0.00")
        igst = tax_total

    total = money(taxable + cgst + sgst + igst)
    return taxable, cgst, sgst, igst, total

def po_register_unicode_font():
    font_path = os.path.join(settings.BASE_DIR, "fonts", "NotoSans-Regular.ttf")

    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont("NotoSans", font_path))
        return "NotoSans"

    return "Helvetica"


def po_money(value):
    value = Decimal(value or 0)
    return f"₹ {value:,.2f}"


def purchase_order_amount_to_words(amount):
    amount = Decimal(amount or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    words = num2words(rupees, lang="en_IN").title()

    if paise:
        paise_words = num2words(paise, lang="en_IN").title()
        return f"Indian Rupee {words} And {paise_words} Paise Only"
    return f"Indian Rupee {words} Only"
def pb_register_unicode_font():
    """
    Reuse same font-loading approach like quotation/purchase order.
    """
    possible_paths = [
        os.path.join(settings.BASE_DIR, "fonts", "NotoSans-Regular.ttf"),
        os.path.join(settings.BASE_DIR, "static", "fonts", "NotoSans-Regular.ttf"),
        os.path.join(settings.BASE_DIR, "fonts", "DejaVuSans.ttf"),
        os.path.join(settings.BASE_DIR, "static", "fonts", "DejaVuSans.ttf"),
    ]

    for font_path in possible_paths:
        if os.path.exists(font_path):
            try:
                pdfmetrics.registerFont(TTFont("PBFont", font_path))
                return "PBFont"
            except Exception:
                pass

    return "Helvetica"


def pb_money(value):
    value = Decimal(value or 0)
    return f"₹ {value:,.2f}"


def pb_text(value):
    return str(value or "").strip()

from django.db import transaction
from django.utils import timezone

PREFIX_MAP = {
    "invoice": "INV",
    "quotation": "QUO",
    "purchase_order": "PO",
    "purchase_bill": "BILL",
}

def generate_document_number(doc_type: str) -> str:
    from core.models import DocumentSequence

    year = timezone.now().year

    with transaction.atomic():
        seq, created = DocumentSequence.objects.select_for_update().get_or_create(
            doc_type=doc_type,
            year=year,
            defaults={"last_number": 0},
        )

        seq.last_number += 1
        seq.save(update_fields=["last_number"])

        prefix = PREFIX_MAP[doc_type]
        return f"{prefix}-{year}-{seq.last_number:04d}"