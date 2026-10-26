
# zoho_integration/utils.py

import requests
from django.conf import settings
from num2words import num2words
import os
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from pathlib import Path
from reportlab.platypus import Paragraph
class ZohoAuthError(Exception):
    """Auth / token errors from Zoho."""
    pass


def get_zoho_access_token() -> str:
    """
    Use REFRESH TOKEN to get a fresh ACCESS TOKEN from Zoho.
    Uses:
      settings.ZOHO_AUTH_BASE_URL
      settings.ZOHO_CLIENT_ID
      settings.ZOHO_CLIENT_SECRET
      settings.ZOHO_REFRESH_TOKEN
    """
    if not settings.ZOHO_REFRESH_TOKEN:
        raise ZohoAuthError("ZOHO_REFRESH_TOKEN is not set. Fill it in .env first.")

    token_url = f"{settings.ZOHO_AUTH_BASE_URL}/token"

    data = {
        "refresh_token": settings.ZOHO_REFRESH_TOKEN,
        "client_id": settings.ZOHO_CLIENT_ID,
        "client_secret": settings.ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }

    try:
        r = requests.post(token_url, data=data, timeout=20)
    except requests.exceptions.RequestException as e:
        raise ZohoAuthError(f"Error calling Zoho token endpoint: {e}")

    try:
        j = r.json()
    except ValueError:
        raise ZohoAuthError(f"Non-JSON response from Zoho: {r.text}")

    if "access_token" not in j:
        # Print the whole error so you see the message & code
        raise ZohoAuthError(f"Failed to get access_token from Zoho: {j}")

    return j["access_token"]

class ZohoBooksError(Exception):
    pass

def _zoho_raise_if_error(resp: requests.Response, action: str) -> dict:
    try:
        data = resp.json() if resp.content else {}
    except Exception:
        data = {"raw": (resp.text or "")[:1000]}

    if resp.status_code >= 400:
        raise ZohoBooksError(f"{action} failed (HTTP {resp.status_code}): {data}")

    if isinstance(data, dict) and data.get("code") not in (None, 0):
        raise ZohoBooksError(f"{action} failed (Zoho code {data.get('code')}): {data}")

    return data
#quatation
from decimal import Decimal, ROUND_HALF_UP

TWOPLACES = Decimal("0.01")


def q2(val):
    return Decimal(val).quantize(TWOPLACES, rounding=ROUND_HALF_UP)


def norm_state(value):
    return (value or "").strip().lower()


def detect_gst_mode(company_state, customer_state):
    """
    INTRA  -> CGST + SGST
    INTER  -> IGST
    """
    if norm_state(company_state) and norm_state(company_state) == norm_state(customer_state):
        return "INTRA"
    return "INTER"


def split_tax_by_mode(taxable_value, gst_percent, gst_mode):
    taxable_value = q2(taxable_value)
    gst_percent = q2(gst_percent)

    total_tax = q2((taxable_value * gst_percent) / Decimal("100"))

    if gst_mode == "INTRA":
        half = q2(total_tax / Decimal("2"))
        return {
            "cgst_amount": half,
            "sgst_amount": half,
            "igst_amount": Decimal("0.00"),
            "line_tax": total_tax,
        }
    else:
        return {
            "cgst_amount": Decimal("0.00"),
            "sgst_amount": Decimal("0.00"),
            "igst_amount": total_tax,
            "line_tax": total_tax,
        }


def calculate_discount(sub_total, discount_type, discount_value):
    sub_total = q2(sub_total)
    discount_value = q2(discount_value)

    if discount_type == "PERCENT":
        return q2((sub_total * discount_value) / Decimal("100"))
    return q2(discount_value)


def calculate_service_charge(base_amount, service_charge_type, service_charge_value):
    base_amount = q2(base_amount)
    service_charge_value = q2(service_charge_value)

    if service_charge_type == "PERCENT":
        return q2((base_amount * service_charge_value) / Decimal("100"))
    elif service_charge_type == "AMOUNT":
        return q2(service_charge_value)
    return Decimal("0.00")


def build_gst_breakdown(lines, gst_mode):
    """
    Returns grouped tax summary by gst percentage
    """
    breakdown = {}

    for line in lines:
        key = f"{line.gst_percent.normalize()}%"
        if key not in breakdown:
            breakdown[key] = {
                "taxable_amount": Decimal("0.00"),
                "cgst_amount": Decimal("0.00"),
                "sgst_amount": Decimal("0.00"),
                "igst_amount": Decimal("0.00"),
                "total_tax": Decimal("0.00"),
            }

        breakdown[key]["taxable_amount"] += q2(line.line_subtotal)
        breakdown[key]["cgst_amount"] += q2(line.cgst_amount)
        breakdown[key]["sgst_amount"] += q2(line.sgst_amount)
        breakdown[key]["igst_amount"] += q2(line.igst_amount)
        breakdown[key]["total_tax"] += q2(line.line_tax)

    # convert Decimal to string-friendly values if needed in serializer
    cleaned = {}
    for k, v in breakdown.items():
        cleaned[k] = {
            "taxable_amount": q2(v["taxable_amount"]),
            "cgst_amount": q2(v["cgst_amount"]),
            "sgst_amount": q2(v["sgst_amount"]),
            "igst_amount": q2(v["igst_amount"]),
            "total_tax": q2(v["total_tax"]),
            "gst_mode": gst_mode,
        }
    return cleaned

def quotation_amount_to_words(amount: Decimal) -> str:
    amount = Decimal(amount).quantize(Decimal("0.01"))
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    rupee_words = num2words(rupees, lang="en_IN").title()

    if paise > 0:
        paise_words = num2words(paise, lang="en_IN").title()
        return f"Indian Rupee {rupee_words} And {paise_words} Paise Only"

    return f"Indian Rupee {rupee_words} Only"


def quotation_money(val):
    try:
        return f"₹ {Decimal(val):.2f}"
    except Exception:
        return f"₹ {val}"


def quotation_register_unicode_font():
    font_path = os.path.join(settings.BASE_DIR, "fonts", "NotoSans-Regular.ttf")
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont("NotoSans", font_path))
        return "NotoSans"
    return "Helvetica"
#payment pdf
