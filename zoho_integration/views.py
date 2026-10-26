# zoho_integration/views.py
from rest_framework.response import Response
from rest_framework import viewsets, status
from rest_framework.parsers import MultiPartParser, FormParser,JSONParser
from rest_framework import generics
from .models import LocalItem,LocalInvoice, LocalInvoiceLine,LocalInvoicePayment,Quotation
from .serializers import ( LocalItemSerializer,LocalInvoiceReadSerializer , LocalInvoiceWriteSerializer,
                          LocalInvoicePaymentReadSerializer,LocalInvoicePaymentWriteSerializer)

import sys
from .zoho_books import (
    build_zoho_item_payload_from_local,
    create_zoho_item,
    update_zoho_item,
    ZohoBooksError,
    upload_item_image_to_zoho,
    delete_zoho_item,
    create_zoho_invoice, update_zoho_invoice, build_zoho_invoice_payload_from_local
    
)
from zoho_integration.utils import (
    quotation_amount_to_words,
    quotation_register_unicode_font,
    quotation_money,
    build_gst_breakdown,

)
import traceback
from reportlab.lib.pagesizes import A4
from core.models import Shop,Growtags
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.enums import TA_RIGHT,TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
from num2words import num2words
from django.http import JsonResponse
from django.conf import settings
from core.mixins import BulkDeleteMixin
from rest_framework.permissions import IsAdminUser
import requests
from django.utils import timezone
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from rest_framework.exceptions import PermissionDenied, ValidationError
from core.stock_service import deduct_stock  # import your service
from core.models import StockLedger  # where your StockLedger exists
from core.stock_service import validate_stock_before_create
from core.authentication import (
   UnifiedTokenAuthentication
)
from core.permissions import CrudByRole
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication
from core.audit import get_actor
from .serializers import (
    QuotationReadSerializer,
    QuotationWriteSerializer,
    QuotationCustomerMiniSerializer,
    QuotationItemMiniSerializer,
    QuotationMetaSerializer,
)
from rest_framework.decorators import action
from core.models import Customer
def q2(x):
    return (x or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def build_gst_view(invoice):
    rows = []
    breakdown = invoice.gst_breakdown or {}

    for code, v in breakdown.items():
        if code == "NO_TAX":
            continue

        rate = Decimal(str(v.get("rate", "0") or "0"))
        tax = q2(Decimal(str(v.get("tax", "0") or "0")))
        taxable = q2(Decimal(str(v.get("taxable", v.get("amount", invoice.taxable_amount or "0")) or "0")))

        if code.startswith("IGST_"):
            rows.append({
                "mode": "IGST",
                "rate": f"{rate}",
                "tax_total": f"{tax}",
                "taxable": f"{taxable}",
                "igst_rate": f"{rate}",
                "igst_tax": f"{tax}",
                "cgst_rate": None,
                "sgst_rate": None,
                "cgst_tax": None,
                "sgst_tax": None,
            })
        else:
            half_rate = q2(rate / Decimal("2"))
            half_tax = q2(tax / Decimal("2"))

            rows.append({
                "mode": "CGST_SGST",
                "rate": f"{rate}",
                "tax_total": f"{tax}",
                "taxable": f"{taxable}",
                "cgst_rate": f"{half_rate}",
                "sgst_rate": f"{half_rate}",
                "cgst_tax": f"{half_tax}",
                "sgst_tax": f"{half_tax}",
                "igst_rate": None,
                "igst_tax": None,
            })

    return rows

def _norm_state(s: str) -> str:
    return (s or "").strip().lower()


def _is_inter_state(invoice, company_state="Kerala") -> bool:
    customer_state = _norm_state(getattr(invoice.customer, "state", ""))
    comp_state = _norm_state(company_state)

    # ✅ If customer state missing → SAME state (GST)
    if not customer_state:
        return False

    return customer_state != comp_state
def _to_igst(code: str) -> str:
    if not code or code == "NO_TAX": return "NO_TAX"
    if code.startswith("IGST_"): return code
    if code.startswith("GST_"): return "IGST_" + code.split("_", 1)[1]
    return code

def _to_gst(code: str) -> str:
    if not code or code == "NO_TAX": return "NO_TAX"
    if code.startswith("GST_"): return code
    if code.startswith("IGST_"): return "GST_" + code.split("_", 1)[1]
    return code

    

# Common audit helpers
class CreatedAuditMixin:
    def perform_create(self, serializer):
        role, actor = get_actor(self.request)
        data = {"created_on": timezone.now().date()}

        if role == "admin":
            data["created_by"] = actor
            data["created_by_role"] = "admin"

        elif role in ("franchise", "othershop", "shop"):
            data["created_by_role"] = "shop"
            data["created_by_shop"] = actor

        elif role == "growtag":
            data["created_by_role"] = "growtag"
            data["created_by_growtag"] = actor

        elif role == "customer":
            data["created_by_role"] = "customer"
            data["created_by_customer"] = actor

        serializer.save(**data)
def zoho_callback(request):
    code = request.GET.get("code")

    if not code:
        return JsonResponse({"error": "Missing code"}, status=400)

    token_url = "https://accounts.zoho.in/oauth/v2/token"

    data = {
        "grant_type": "authorization_code",
        "client_id": settings.ZOHO_CLIENT_ID,
        "client_secret": settings.ZOHO_CLIENT_SECRET,
        "redirect_uri": settings.ZOHO_REDIRECT_URI,
        "code": code,
    }

    r = requests.post(token_url, data=data)
    token_data = r.json()

    # 🔥 THIS IS WHERE YOU SEE TOKENS
    #return JsonResponse(token_data)
    print("ZOHO TOKEN RESPONSE >>>", token_data)
    return JsonResponse({"detail": "Token received. Check server logs."})

LOCAL_ONLY_FIELDS = {"opening_stock", "current_stock", "is_active", "item_image"}


# zoho_integration/views.py

class LocalItemListCreateView(BulkDeleteMixin, CreatedAuditMixin, generics.ListCreateAPIView):
    serializer_class = LocalItemSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    authentication_classes = [JWTAuthentication, SessionAuthentication, UnifiedTokenAuthentication]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"GET", "POST", "PATCH", "PUT", "DELETE"},
        "franchise": {"GET", "POST", "PATCH", "PUT", "DELETE"},
        "othershop": {"GET", "POST", "PATCH", "PUT", "DELETE"},
        "growtag": {"GET", "POST", "PATCH", "PUT", "DELETE"},
        "customer": {"GET"}, 
    }
    
    def get_queryset(self):
        qs = LocalItem.objects.filter(is_active=True).order_by("-id")

        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        if getattr(self.request, "shop", None):
            return qs.filter(created_by_shop=self.request.shop)

        if getattr(self.request, "growtag", None):
            return qs.filter(created_by_growtag=self.request.growtag)

        return qs.none()
    
    def perform_create(self, serializer):
        """Set audit fields and handle Zoho sync"""
        role, actor = get_actor(self.request)
        
        
        extra_data = {
            "sync_status": "PENDING",
            "created_on": timezone.now().date(),
        }
        
        # Set audit fields based on role
        if role == "admin":
            extra_data["created_by"] = actor
            extra_data["created_by_role"] = "admin"
        elif role in ("franchise", "othershop", "shop"):
            extra_data["created_by_role"] = role
            extra_data["created_by_shop"] = actor
        elif role == "growtag":
            extra_data["created_by_role"] = "growtag"
            extra_data["created_by_growtag"] = actor
        elif role == "customer":
            extra_data["created_by_role"] = "customer"
            extra_data["created_by_customer"] = actor
        
        # Save the item
        item = serializer.save(**extra_data)
         # local only
        item.sync_status = "SYNCED"
        item.save(update_fields=["sync_status"])
        # Handle Zoho sync
        #try:
            #request = self.request
            #payload = build_zoho_item_payload_from_local(item)
            #zoho_res = create_zoho_item(payload)

            #item.zoho_item_id = (zoho_res.get("item") or {}).get("item_id")
            #item.sync_status = "SYNCED"
            #item.save(update_fields=["zoho_item_id", "sync_status"])

            #if "item_image" in request.FILES and item.zoho_item_id:
                #upload_item_image_to_zoho(
                    #zoho_item_id=item.zoho_item_id,
                    #file_obj=request.FILES["item_image"],
                #)
            
            #self.zoho_response = zoho_res
            #self.sync_success = True
            
        #except ZohoBooksError as e:
            #item.sync_status = "FAILED"
            #item.save(update_fields=["sync_status"])
            #self.zoho_error = str(e)
            #self.sync_success = False
            
        #except Exception as e:
            #traceback.print_exc()
            #item.sync_status = "FAILED"
            #item.save(update_fields=["sync_status"])
            #self.zoho_error = str(e)
            #self.sync_success = False
    
    def create(self, request, *args, **kwargs):
        """Handle create with custom response"""
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            
            self.perform_create(serializer)
            item = serializer.instance
            
            response_data = {
                "detail": "Item created successfully",
                "data": self.get_serializer(item).data
            }
            
            # Add Zoho sync info if available
            #if hasattr(self, 'sync_success'):
                #if self.sync_success:
                    #response_data["zoho_sync"] = {
                       # "status": "success",
                        #"response": getattr(self, 'zoho_response', None)
                    #}
                #else:
                    #response_data["zoho_sync"] = {
                        #"status": "failed",
                        #"error": getattr(self, 'zoho_error', None)
                    #}
            
            status_code = status.HTTP_201_CREATED
            #if hasattr(self, 'sync_success') and not self.sync_success:
                #status_code = status.HTTP_502_BAD_GATEWAY
            
            return Response(response_data, status=status_code)
                
        except Exception as e:
            traceback.print_exc(file=sys.stdout)
            return Response(
                {
                    "detail": "Create failed",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        
       
class LocalItemDetailSyncView(BulkDeleteMixin, generics.RetrieveUpdateDestroyAPIView):
    queryset = LocalItem.objects.all()
    serializer_class = LocalItemSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    authentication_classes = [JWTAuthentication, SessionAuthentication, UnifiedTokenAuthentication]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"GET", "PUT", "PATCH", "DELETE"},
        "franchise": {"GET", "POST","PATCH","PUT","DELETE"},
        "othershop": {"GET", "POST","PATCH","PUT","DELETE"},
        "growtag": {"GET", "POST","PATCH","PUT","DELETE"},
        "customer": set(),
    }
    def get_queryset(self):
        qs = LocalItem.objects.filter(is_active=True).order_by("-id")

        # admin sees all
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # franchise / othershop sees only own items
        if getattr(self.request, "shop", None):
            return qs.filter(created_by_shop=self.request.shop)

        # growtag sees only own items
        if getattr(self.request, "growtag", None):
            return qs.filter(created_by_growtag=self.request.growtag)

        return qs.none()
    def get_object(self):
        # You can keep default or block retrieving inactive items if you want:
        # return get_object_or_404(LocalItem, pk=self.kwargs["pk"], is_active=True)
        return super().get_object()

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    #def update(self, request, *args, **kwargs):
        #partial = kwargs.pop("partial", False)
        #item = self.get_object()

        #serializer = self.get_serializer(item, data=request.data, partial=partial)
        #serializer.is_valid(raise_exception=True)

        # ✅ Save locally first
        #item = serializer.save(sync_status="SYNCED")
        #item = serializer.save(sync_status="PENDING")

        # ✅ Decide if Zoho sync is really needed
        #request_fields = set(request.data.keys())

        # local-only changes: no need Zoho update
        # If request includes any non-local-only field => sync Zoho
        #should_sync_zoho = len(request_fields - LOCAL_ONLY_FIELDS) > 0

        # If only image uploaded, we still may need zoho upload (but not update payload)
        #image_sent = "item_image" in request.FILES

        #try:
            #zoho_res = None

            #if should_sync_zoho:
                #payload = build_zoho_item_payload_from_local(item)

                # If already synced → update
                #if item.zoho_item_id:
                    #zoho_res = update_zoho_item(item.zoho_item_id, payload)
                #else:
                    #zoho_res = create_zoho_item(payload)
                    #new_id = (zoho_res.get("item") or {}).get("item_id")
                    #if new_id:
                        #item.zoho_item_id = new_id
                        #item.save(update_fields=["zoho_item_id"])

            # ✅ Upload image if sent and Zoho ID exists
            #if image_sent and item.zoho_item_id:
                #upload_item_image_to_zoho(
                    #zoho_item_id=item.zoho_item_id,
                    #file_obj=request.FILES["item_image"],
                #)

                #item.sync_status = "SYNCED"
                #item.save(update_fields=["sync_status"])

                #return Response(
                #{
                #"detail": "Updated locally only",
                #"local_item": self.get_serializer(item).data,
                #"zoho_response": zoho_res,
                #},
                #status=status.HTTP_200_OK,
                #)

        #except ZohoBooksError as e:
                #item.sync_status = "FAILED"
                #item.save(update_fields=["sync_status"])

            #return Response(
            #{
                #"detail": "Updated locally but Zoho sync failed",
                #"local_item": self.get_serializer(item).data,
                #"error": str(e),
            #},
            #status=status.HTTP_502_BAD_GATEWAY,
            #)
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        item = self.get_object()

        serializer = self.get_serializer(item, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)

        item = serializer.save(sync_status="SYNCED")

        return Response(
        {
            "detail": "Updated locally only",
            "local_item": self.get_serializer(item).data,
        },
        status=status.HTTP_200_OK,
        )
    def destroy(self, request, *args, **kwargs):
        """
        ✅ Soft delete locally (is_active=False)
        ✅ Optionally delete from Zoho
        """
        item = self.get_object()

        # Optional: delete from Zoho
        #if item.zoho_item_id:
            #try:
                #delete_zoho_item(item.zoho_item_id)
            #except ZohoBooksError as e:
                #return Response(
                    #{"detail": "Zoho delete failed. Local not deactivated.", "error": str(e)},
                    #status=status.HTTP_502_BAD_GATEWAY,
                #)

        # ✅ Soft delete
        item.is_active = False
        item.save(update_fields=["is_active"])

        return Response({"detail": "Item deactivated (soft deleted)"}, status=status.HTTP_200_OK)


    
    #invoice
# ===============================
# HELPERS (TOP OF FILE)
# ===============================

def _q2(x: Decimal) -> Decimal:
    return (x or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def recompute_invoice_totals(invoice: LocalInvoice) -> None:
    """
    Recompute invoice totals based on stored line fields.
    NOTE: This implementation treats discount as AFTER tax (simple + consistent).
    If you want discount BEFORE tax, tell me and I’ll give the proportional-tax version.
    """
    lines = invoice.lines.all()

    sub_total = _q2(sum((l.line_amount for l in lines), Decimal("0")))
    service_total = _q2(sum((l.service_charge_amount for l in lines), Decimal("0")))
    taxable_amount = _q2(sum((l.taxable_amount for l in lines), Decimal("0")))
    grand_before_discount = _q2(sum((l.line_total for l in lines), Decimal("0")))

    # discount
    discount_amount = Decimal("0")
    if invoice.discount_type == "PERCENT":
        pct = Decimal(invoice.discount_value or 0)
        if pct < 0:
            pct = Decimal("0")
        if pct > 100:
            pct = Decimal("100")
        discount_amount = _q2((grand_before_discount * pct) / Decimal("100"))
    else:
        discount_amount = _q2(Decimal(invoice.discount_value or 0))

    if discount_amount > grand_before_discount:
        discount_amount = grand_before_discount
    shipping_charge = _q2(Decimal(invoice.shipping_charge or 0))
    adjustment = _q2(Decimal(invoice.adjustment or 0))

    grand_total = _q2(grand_before_discount - discount_amount)
    inter = _is_inter_state(invoice, company_state="Kerala")
    # GST breakup aggregate by gst_treatment
    gst_breakdown = {}
    for l in lines:
        key = l.gst_treatment or "NO_TAX"
        key = _to_igst(key) if inter else _to_gst(key) 
        if key not in gst_breakdown:
            gst_breakdown[key] = {"rate": str(l._gst_rate_percent()), "tax": "0.00", "taxable": "0.00"}
        gst_breakdown[key]["tax"] = str(_q2(Decimal(gst_breakdown[key]["tax"]) + Decimal(l.line_tax)))
        gst_breakdown[key]["taxable"] = str(_q2(Decimal(gst_breakdown[key]["taxable"]) + Decimal(l.taxable_amount)))

    invoice.sub_total = sub_total
    invoice.service_charge_total = service_total
    invoice.taxable_amount = taxable_amount
    invoice.discount_amount = discount_amount
    invoice.gst_breakdown = gst_breakdown
    invoice.grand_total = grand_total

FINAL_PAYMENT_STATUSES = {"PAID", "PARTIALLY_PAID", "OVERDUE"}

def get_invoice_owner(invoice: LocalInvoice):
    """
    Decide invoice owner using existing fields:
    assigned_shop OR assigned_growtag
    """
    if invoice.assigned_shop_id and invoice.assigned_growtag_id:
        raise ValidationError("Invoice cannot have both assigned_shop and assigned_growtag.")

    if invoice.assigned_shop_id:
        return ("shop", invoice.assigned_shop, None)

    if invoice.assigned_growtag_id:
        return ("growtag", None, invoice.assigned_growtag)

    raise ValidationError("Invoice must have assigned_shop OR assigned_growtag.")


def has_invoice_stock_deducted(invoice: LocalInvoice) -> bool:
    owner_type, shop, growtag = get_invoice_owner(invoice)
    return StockLedger.objects.filter(
        owner_type=owner_type,
        shop=shop if owner_type == "shop" else None,
        growtag=growtag if owner_type == "growtag" else None,
        ref_type="INVOICE",
        ref_id=invoice.id,
    ).exists()
def apply_invoice_stock_deduction_if_final(invoice: LocalInvoice):
    """
    Deduct stock only for PAID/PARTIALLY_PAID and only once.
    Shared helper for invoice create/update/payment flows.
    """
    if invoice.status != "SENT":
        return
    if invoice.payment_status not in FINAL_PAYMENT_STATUSES:
        return

    if has_invoice_stock_deducted(invoice):
        return  # already deducted

    owner_type, shop, growtag = get_invoice_owner(invoice)

    for ln in invoice.lines.select_related("item").all():
        deduct_stock(
            owner_type=owner_type,
            shop=shop,
            growtag=growtag,
            item=ln.item,
            qty=ln.qty,
            ref_type="INVOICE",
            ref_id=invoice.id,
            note=f"Stock deducted from Invoice {invoice.invoice_number}",
        )
class LocalInvoiceViewSet(BulkDeleteMixin,CreatedAuditMixin,viewsets.ModelViewSet):
    queryset = LocalInvoice.objects.all().order_by("-id")
    authentication_classes = [
        JWTAuthentication,SessionAuthentication,
        UnifiedTokenAuthentication,
    ]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE","PUT"},
        "franchise": {"GET", "POST", "PATCH","PUT"},
        "othershop": {"GET", "POST", "PATCH","PUT"},
        "growtag": {"GET","POST","PATCH","PUT"},
        "customer": {"GET"},   
    }
    def get_serializer_class(self):
        if self.action in {"list", "retrieve"}:
            return LocalInvoiceReadSerializer
        return LocalInvoiceWriteSerializer
    def get_queryset(self):
        qs = super().get_queryset()

       # ✅ Admin sees all
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # ✅ Shop sees only its invoices
        if getattr(self.request, "shop", None):
            return qs.filter(assigned_shop=self.request.shop)

        # ✅ Growtag sees only its invoices
        if getattr(self.request, "growtag", None):
            return qs.filter(assigned_growtag=self.request.growtag)

       # ✅ Customer sees only own invoices (optional)
        if getattr(self.request, "customer", None):
            return qs.filter(customer_id=self.request.customer.id)

        return qs.none()

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload_lines = serializer.validated_data.pop("lines_payload", [])

        # get owner from request data (because invoice not created yet)
        # ✅ ADMIN: can use payload owner
        if request.user and request.user.is_authenticated and request.user.is_staff:
           assigned_shop = serializer.validated_data.get("assigned_shop")
           assigned_growtag = serializer.validated_data.get("assigned_growtag")

        # ✅ SHOP: force assigned_shop from token
        elif getattr(request, "shop", None):
            serializer.validated_data["assigned_shop"] = request.shop
            serializer.validated_data["assigned_growtag"] = None
            assigned_shop = request.shop
            assigned_growtag = None

        # ✅ GROWTAG: force assigned_growtag from token (or block create)
        elif getattr(request, "growtag", None):
            serializer.validated_data["assigned_growtag"] = request.growtag
            serializer.validated_data["assigned_shop"] = None
            assigned_shop = None
            assigned_growtag = request.growtag

# ✅ CUSTOMER: block create
        elif getattr(request, "customer", None):
          raise PermissionDenied("Customer cannot create invoice.")

        else:
           raise PermissionDenied("Not allowed.")


        if assigned_shop and assigned_growtag:
          raise ValidationError("Invoice cannot be assigned to both shop and growtag.")
        if not assigned_shop and not assigned_growtag:
          raise ValidationError("Invoice must be assigned to either shop or growtag.")

        owner_type = "shop" if assigned_shop else "growtag"
        shop = assigned_shop if owner_type == "shop" else None
        growtag = assigned_growtag if owner_type == "growtag" else None

        # ✅ Validate stock BEFORE invoice create
        if serializer.validated_data.get("status") in FINAL_PAYMENT_STATUSES:
           validate_stock_before_create(
                                       owner_type=owner_type,
                                       shop=shop,
                                       growtag=growtag,
                                       payload_lines=payload_lines
                                       )


        with transaction.atomic():
            #invoice = LocalInvoice.objects.create(**serializer.validated_data)
            #invoice = LocalInvoice.objects.create(
                                                 #**serializer.validated_data,
                                                 #created_by=request.user if request.user.is_authenticated else None,
                                                 #created_on=timezone.now().date(),
                                             #)
             # ✅ role-based created_by / created_by_role
            role, actor = get_actor(request)

            create_kwargs = dict(serializer.validated_data)
            create_kwargs["created_on"] = timezone.now().date()
            create_kwargs["status"] = serializer.validated_data.get("status", "DRAFT")
            create_kwargs["payment_status"] = "UNPAID"
            if role == "admin":
              create_kwargs["created_by"] = actor
              create_kwargs["created_by_role"] = "admin"

            elif role in ("franchise", "othershop", "shop"):
              # your system treats shop tokens as franchise/othershop
              create_kwargs["created_by_role"] = role
              create_kwargs["created_by_shop"] = actor

            elif role == "growtag":
               create_kwargs["created_by_role"] = "growtag"
               create_kwargs["created_by_growtag"] = actor

            elif role == "customer":
               create_kwargs["created_by_role"] = "customer"
               create_kwargs["created_by_customer"] = actor

            invoice = LocalInvoice.objects.create(**create_kwargs)

            # create lines
            bad_items = []
            for i, line in enumerate(payload_lines):
                local_item_id = line["item_id"]
                try:
                    item = LocalItem.objects.get(id=local_item_id)
                except LocalItem.DoesNotExist:
                    bad_items.append(local_item_id)
                    continue

                LocalInvoiceLine.objects.create(
                    invoice=invoice,
                    item=item,
                    qty=line["qty"],
                    rate=line["rate"],
                    description=line.get("description", ""),
                    service_charge_type=line.get("service_charge_type", "AMOUNT"),
                    service_charge_value=line.get("service_charge_value", Decimal("0")),
                    gst_treatment=line.get("gst_treatment") or item.gst_treatment or "NO_TAX",
                )

            if bad_items:
                raise ValidationError({"lines_payload": f"Invalid item_id(s): {bad_items}"})

            # totals
            recompute_invoice_totals(invoice)
            invoice.save(update_fields=[
                "sub_total", "service_charge_total", "taxable_amount",
                "discount_amount", "gst_breakdown", "grand_total"
            ])
            invoice.update_payment_status(save=True)
            # ✅ stock deduction (only if PAID/PARTIALLY_PAID)
            self._apply_stock_deduction_if_final(invoice)
        # ✅ If no lines, skip Zoho sync (Zoho requires at least 1 item)
        if not invoice.lines.exists():
          invoice.sync_status = "PENDING"   # or "NOT_READY"
          invoice.last_error = ""
          invoice.save(update_fields=["sync_status", "last_error", "updated_at"])
          return Response(LocalInvoiceReadSerializer(invoice).data, status=status.HTTP_201_CREATED)

        # Sync to Zoho (outside atomic ok, but we update invoice after)
        try:
            zoho_payload = build_zoho_invoice_payload_from_local(invoice)
            zoho_res = create_zoho_invoice(zoho_payload)

            inv_obj = zoho_res.get("invoice") or {}
            invoice.zoho_invoice_id = str(inv_obj.get("invoice_id") or "")
            invoice.sync_status = "SYNCED"
            invoice.last_error = ""
            invoice.save(update_fields=["zoho_invoice_id", "sync_status", "last_error"])
        except ZohoBooksError as e:
            invoice.sync_status = "FAILED"
            invoice.last_error = str(e)
            invoice.save(update_fields=["sync_status", "last_error"])
        

        except Exception as e:
            invoice.sync_status = "FAILED"
            invoice.last_error = str(e)
            invoice.save(update_fields=["sync_status", "last_error"])
        if request.query_params.get("pdf") == "1":
           return invoice_pdf_view(request, pk=invoice.pk)
        #return Response(LocalInvoiceReadSerializer(invoice).data, status=status.HTTP_201_CREATED)
        return Response(
               LocalInvoiceReadSerializer(invoice, context={"request": request}).data,
              status=status.HTTP_200_OK
            )

    def update(self, request, *args, **kwargs):
        """
        Full update (PUT) – supports replacing lines if lines_payload is provided.
        """
        invoice = self.get_object()
         

        # ✅ Shop: cannot edit invoices after FINAL or stock deducted

        if getattr(request, "shop", None):
          if invoice.assigned_shop_id != request.shop.id:
              raise PermissionDenied("You cannot edit this invoice.")
          if invoice.status == "CANCELLED":
              raise PermissionDenied("Cannot edit cancelled invoice.")
          if has_invoice_stock_deducted(invoice):
              raise PermissionDenied("Cannot edit after stock deducted.")

        # ✅ Growtag: usually block, or allow limited fields
        if getattr(request, "growtag", None):
            if invoice.assigned_growtag_id != request.growtag.id:
               raise PermissionDenied("You cannot edit this invoice.")
            if invoice.status == "CANCELLED":
               raise PermissionDenied("Cannot edit cancelled invoice.")
            if has_invoice_stock_deducted(invoice):
               raise PermissionDenied("Cannot edit after stock deducted.")
        old_status = invoice.status
        serializer = self.get_serializer(invoice, data=request.data)
        serializer.is_valid(raise_exception=True)
        payload_lines = serializer.validated_data.pop("lines_payload", None)
        if payload_lines is not None and has_invoice_stock_deducted(invoice):
           raise ValidationError("Cannot edit invoice lines after stock is deducted.")
        with transaction.atomic():
            for k, v in serializer.validated_data.items():
                setattr(invoice, k, v)
            invoice.save()

            # replace lines only if provided
            if payload_lines is not None:
                invoice.lines.all().delete()

                bad_items = []
                for line in payload_lines:
                    local_item_id = line["item_id"]
                    try:
                        item = LocalItem.objects.get(id=local_item_id)
                    except LocalItem.DoesNotExist:
                        bad_items.append(local_item_id)
                        continue

                    LocalInvoiceLine.objects.create(
                        invoice=invoice,
                        item=item,
                        qty=line["qty"],
                        rate=line["rate"],
                        description=line.get("description", ""),
                        service_charge_type=line.get("service_charge_type", "AMOUNT"),
                        service_charge_value=line.get("service_charge_value", Decimal("0")),
                        gst_treatment=line.get("gst_treatment") or item.gst_treatment or "NO_TAX",
                    )

                if bad_items:
                    raise ValueError(f"Invalid item_id(s): {bad_items}")

            recompute_invoice_totals(invoice)
            invoice.save(update_fields=[
                "sub_total", "service_charge_total", "taxable_amount",
                "discount_amount", "gst_breakdown", "grand_total"
            ])
            invoice.update_payment_status(save=True)
            if old_status not in FINAL_PAYMENT_STATUSES and invoice.status in FINAL_PAYMENT_STATUSES:
                self._apply_stock_deduction_if_final(invoice)
        if not invoice.lines.exists():
          invoice.sync_status = "PENDING"
          invoice.last_error = ""
          invoice.save(update_fields=["sync_status", "last_error", "updated_at"])
          return Response(LocalInvoiceReadSerializer(invoice).data, status=status.HTTP_200_OK)

        # Zoho sync: if zoho_invoice_id exists => update, else create
        try:
            zoho_payload = build_zoho_invoice_payload_from_local(invoice)
            if invoice.zoho_invoice_id:
                zoho_res = update_zoho_invoice(invoice.zoho_invoice_id, zoho_payload)
            else:
                zoho_res = create_zoho_invoice(zoho_payload)
                inv_obj = zoho_res.get("invoice") or {}
                invoice.zoho_invoice_id = str(inv_obj.get("invoice_id") or "")

            invoice.sync_status = "SYNCED"
            invoice.last_error = ""
            invoice.save(update_fields=["zoho_invoice_id", "sync_status", "last_error"])
        except ZohoBooksError as e:
            invoice.sync_status = "FAILED"
            invoice.last_error = str(e)
            invoice.save(update_fields=["sync_status", "last_error"])    

        except Exception as e:
            invoice.sync_status = "FAILED"
            invoice.last_error = str(e)
            invoice.save(update_fields=["sync_status", "last_error"])
        if request.query_params.get("pdf") == "1":
           return invoice_pdf_view(request, pk=invoice.pk)
        #return Response(LocalInvoiceReadSerializer(invoice).data, status=status.HTTP_200_OK)
        return Response(
             LocalInvoiceReadSerializer(invoice, context={"request": request}).data,
                 status=status.HTTP_200_OK
            )

    def partial_update(self, request, *args, **kwargs):
        """
        PATCH – same behavior as update, but partial fields.
        """
        invoice = self.get_object()
        # ✅ Shop: cannot edit invoices after FINAL or stock deducted
        if getattr(request, "shop", None):
          if invoice.assigned_shop_id != request.shop.id:
              raise PermissionDenied("You cannot edit this invoice.")
          if invoice.status == "CANCELLED":
              raise PermissionDenied("Cannot edit cancelled invoice.")
          if has_invoice_stock_deducted(invoice):
              raise PermissionDenied("Cannot edit after stock deducted.")

        # ✅ Growtag: usually block, or allow limited fields
        if getattr(request, "growtag", None):
          if invoice.assigned_growtag_id != request.growtag.id:
            raise PermissionDenied("You cannot edit this invoice.")
        # safest:
          raise PermissionDenied("Growtag cannot edit invoice.")

        old_status = invoice.status

        serializer = self.get_serializer(invoice, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        payload_lines = serializer.validated_data.pop("lines_payload", None)

        if payload_lines is not None and has_invoice_stock_deducted(invoice):
          raise ValidationError("Cannot edit invoice lines after stock is deducted.")
        with transaction.atomic():
            for k, v in serializer.validated_data.items():
                setattr(invoice, k, v)
            invoice.save()

            if payload_lines is not None:
                invoice.lines.all().delete()

                bad_items = []
                for line in payload_lines:
                    local_item_id = line["item_id"]
                    try:
                        item = LocalItem.objects.get(id=local_item_id)
                    except LocalItem.DoesNotExist:
                        bad_items.append(local_item_id)
                        continue

                    LocalInvoiceLine.objects.create(
                        invoice=invoice,
                        item=item,
                        qty=line["qty"],
                        rate=line["rate"],
                        description=line.get("description", ""),
                        service_charge_type=line.get("service_charge_type", "AMOUNT"),
                        service_charge_value=line.get("service_charge_value", Decimal("0")),
                        gst_treatment=line.get("gst_treatment") or item.gst_treatment or "NO_TAX",
                    )

                if bad_items:
                    
                    raise ValidationError({"lines_payload": f"Invalid item_id(s): {bad_items}"})

            recompute_invoice_totals(invoice)
            invoice.save(update_fields=[
                "sub_total", "service_charge_total", "taxable_amount",
                "discount_amount", "gst_breakdown", "grand_total"
            ])
            invoice.update_payment_status(save=True)
            if old_status not in FINAL_PAYMENT_STATUSES and invoice.status in FINAL_PAYMENT_STATUSES:
              try:
                self._apply_stock_deduction_if_final(invoice)
              except ValidationError as e:
                   return Response({"detail": e.messages}, status=status.HTTP_400_BAD_REQUEST)

        if not invoice.lines.exists():
            invoice.sync_status = "PENDING"
            invoice.last_error = ""
            invoice.save(update_fields=["sync_status", "last_error", "updated_at"])
            return Response(LocalInvoiceReadSerializer(invoice).data, status=status.HTTP_200_OK)

        # optional: sync patch too (same logic)
        try:
            zoho_payload = build_zoho_invoice_payload_from_local(invoice)
            if invoice.zoho_invoice_id:
                update_zoho_invoice(invoice.zoho_invoice_id, zoho_payload)
            else:
                zoho_res = create_zoho_invoice(zoho_payload)
                inv_obj = zoho_res.get("invoice") or {}
                invoice.zoho_invoice_id = str(inv_obj.get("invoice_id") or "")
        
            invoice.sync_status = "SYNCED"
            invoice.last_error = ""
            invoice.save(update_fields=["zoho_invoice_id", "sync_status", "last_error"])
        except ZohoBooksError as e:
            invoice.sync_status = "FAILED"
            invoice.last_error = str(e)
            invoice.save(update_fields=["sync_status", "last_error"])
    

        except Exception as e:
            invoice.sync_status = "FAILED"
            invoice.last_error = str(e)
            invoice.save(update_fields=["sync_status", "last_error"])
        if request.query_params.get("pdf") == "1":
           return invoice_pdf_view(request, pk=invoice.pk)
        #return Response(LocalInvoiceReadSerializer(invoice).data, status=status.HTTP_200_OK)
        return Response(
             LocalInvoiceReadSerializer(invoice, context={"request": request}).data,
             status=status.HTTP_200_OK
            )
    
    def _apply_stock_deduction_if_final(self, invoice: LocalInvoice):
        apply_invoice_stock_deduction_if_final(invoice)
    
    #invoice pdf
from django.shortcuts import get_object_or_404
from django.http import HttpResponse
from django.template.loader import render_to_string
from decimal import Decimal
from num2words import num2words
from rest_framework.decorators import api_view, authentication_classes, permission_classes

def amount_to_words(amount: Decimal) -> str:
    amount = Decimal(amount).quantize(Decimal("0.01"))
    rupees = int(amount)
    paise = int((amount - rupees) * 100)

    rupee_words = num2words(rupees, lang="en_IN").title()

    if paise > 0:
        paise_words = num2words(paise, lang="en_IN").title()
        return f"Indian Rupee {rupee_words} And {paise_words} Paise Only"

    return f"Indian Rupee {rupee_words} Only"


#invoice pdf view
from decimal import Decimal
import os

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import PermissionDenied

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.enums import TA_RIGHT  
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image
from reportlab.lib.enums import TA_CENTER
import os
from pathlib import Path
from django.core.exceptions import ValidationError as DjangoValidationError
def _register_unicode_font():
    font_path = os.path.join(settings.BASE_DIR, "fonts", "NotoSans-Regular.ttf")
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont("NotoSans", font_path))
        return "NotoSans"
    return "Helvetica"


def money(val):
    try:
        return f"₹ {Decimal(val):.2f}"
    except Exception:
        return f"₹ {val}"


@api_view(["GET"])
@authentication_classes([JWTAuthentication, SessionAuthentication, UnifiedTokenAuthentication])
@permission_classes([CrudByRole])
def invoice_pdf_view(request, pk):
    invoice = get_object_or_404(LocalInvoice, pk=pk)

    # ✅ permissions
    u = getattr(request, "user", None)
    if u and u.is_authenticated and u.is_staff:
        pass
    elif getattr(request, "shop", None):
        if invoice.assigned_shop_id != request.shop.id:
            raise PermissionDenied
    elif getattr(request, "growtag", None):
        if invoice.assigned_growtag_id != request.growtag.id:
            raise PermissionDenied
    elif getattr(request, "customer", None):
        if invoice.customer_id != request.customer.id:
            raise PermissionDenied
    else:
        raise PermissionDenied

    lines = invoice.lines.select_related("item").all()
    gst_rows = build_gst_view(invoice)

    total_tax = Decimal("0.00")
    for _, v in (invoice.gst_breakdown or {}).items():
        try:
            total_tax += Decimal(v.get("tax", "0.00"))
        except Exception:
            pass

    total_in_words = amount_to_words(invoice.grand_total)

    base_font = _register_unicode_font()
    print("Using font:", base_font)

    # ✅ IMPORTANT: styles defined here (this fixes your NameError)
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="InvTitle",
        parent=styles["Title"],
        fontName=base_font,
        fontSize=24,
        leading=28,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    ))

    styles.add(ParagraphStyle(
        name="InvSmall",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#475569"),
    ))

    styles.add(ParagraphStyle(
        name="InvBody",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
    ))

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="invoice_{invoice.id}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Invoice {invoice.invoice_number}",
    )

    elements = []

    # Header
    logo_path = Path(settings.BASE_DIR) / "static" / "img" / "logo.jpg"  # adjust path
    
    if os.path.exists(logo_path):
        logo = Image(logo_path)
        logo.drawHeight = 25 * mm   # adjust size
        logo.drawWidth = 60 * mm    # adjust size
        logo.hAlign = "LEFT"      # center logo

        elements.append(logo)
        elements.append(Spacer(1, 8))  # space below logo
    elements.append(Paragraph("INVOICE", styles["InvTitle"]))

    right_style = ParagraphStyle(
        "OrgRight",
        parent=styles["InvSmall"],
        alignment=TA_RIGHT
        )

    left_block = Paragraph(
        f'Invoice Number: <b>{invoice.invoice_number}</b><br/>'
        f'Date: <b>{invoice.invoice_date}</b>',
        styles["InvSmall"]
        )

    right_block = Paragraph(
        "<b>Nabeel org</b><br/>Kerala, India<br/>nabeekm18@gmail.com",
        right_style
        )

    #header_tbl = Table([[left_block, right_block]], colWidths=[110*mm, 60*mm])
    header_tbl = Table([[left_block, right_block]], colWidths=[112*mm, 60*mm], hAlign="LEFT")  # 172mm
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("LEFTPADDING", (0,0), (-1,-1), 0),
        ("RIGHTPADDING", (0,0), (-1,-1), 0),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
         ]))
    elements.append(header_tbl)
    elements.append(Spacer(1, 10))

    # Items table
    data = [["#", "Item", "Qty", "Rate", "Service", "GST", "Amount"]]
    for i, ln in enumerate(lines, start=1):
        gst_text = "0%"
        if getattr(ln, "gst_treatment", None) and ln.gst_treatment != "NO_TAX":
            gst_text = f"{ln.gst_treatment}%"
        data.append([
            str(i),
            (ln.item.name if ln.item else ""),
            str(ln.qty),
            money(ln.rate),
            money(ln.service_charge_amount),
            gst_text,
            money(ln.line_total),
        ])

    tbl = Table(
    data,
    colWidths=[10*mm, 58*mm, 12*mm, 22*mm, 24*mm, 20*mm, 26*mm],  # ✅ GST wider
    repeatRows=1,hAlign="LEFT"
    )

    tbl.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), base_font),  # ✅ applies to whole table (fixes ₹)
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#1e4d86")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("FONTSIZE", (0,0), (-1,0), 10),
        ("FONTSIZE", (0,1), (-1,-1), 10),

        ("GRID", (0,0), (-1,-1), 0.8, colors.HexColor("#cfd8e3")),

        ("ALIGN", (2,1), (2,-1), "RIGHT"),   # Qty
        ("ALIGN", (3,1), (4,-1), "RIGHT"),   # Rate + Service
        ("ALIGN", (6,1), (6,-1), "RIGHT"),   # Amount
        ("ALIGN", (5,1), (5,-1), "CENTER"),  # ✅ GST center
        ("ALIGN", (5,0), (5,0), "CENTER"),   # GST header center

        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    elements.append(tbl)
    elements.append(Spacer(1, 10))

    # Totals
    totals = [
        ["Sub Total", money(invoice.sub_total)],
        ["Discount (-)", money(invoice.discount_amount)],
        ["Service Charge", money(invoice.service_charge_total)],
        ["Total Tax", money(total_tax)],
        ["TOTAL", money(invoice.grand_total)],
        ["Balance Due", money(invoice.grand_total)],
    ]
    #t = Table(totals, colWidths=[60*mm, 35*mm])
    t = Table(totals, colWidths=[35*mm, 25*mm],hAlign="LEFT")  # total 60mm
    t.setStyle(TableStyle([
        ("GRID", (0,0), (-1,-1), 0.8, colors.HexColor("#cfd8e3")),
        ("FONTNAME", (0,0), (-1,-1), base_font),
        ("ALIGN", (1,0), (1,-1), "RIGHT"),
        ("BACKGROUND", (0,4), (-1,4), colors.HexColor("#1e4d86")),
        ("TEXTCOLOR", (0,4), (-1,4), colors.white),
        ("BACKGROUND", (0,5), (-1,5), colors.HexColor("#f1f5f9")),
    ]))
        # Left side: Terms + Total in Words
    terms_content = invoice.terms_conditions or "-"

    left_section = [
        Paragraph("<b>Total In Words</b>", styles["InvBody"]),
        Spacer(1, 4),
        Paragraph(f"<i>{total_in_words}</i>", styles["InvBody"]),
        Spacer(1, 10),
        Paragraph("<b>Terms and Conditions</b>", styles["InvBody"]),
        Spacer(1, 4),
        Paragraph(terms_content, styles["InvSmall"]),
    ]

    # Wrap left section inside a box
    #left_box = Table([[left_section]], colWidths=[95*mm])
    left_box = Table([[left_section]], colWidths=[112*mm])
    left_box.setStyle(TableStyle([
        ("BOX", (0,0), (-1,-1), 0.8, colors.HexColor("#cfd8e3")),
        ("LEFTPADDING", (0,0), (-1,-1), 10),
        
        ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ("TOPPADDING", (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
    ]))

    # Right side: Totals table (already created as variable t)
    bottom_section = Table([[left_box, t]], colWidths=[112*mm,60*mm ], hAlign="LEFT")
    #bottom_section = Table([[left_box, t]], colWidths=[95*mm, 60*mm])
    bottom_section.setStyle(TableStyle([
       ("VALIGN", (0,0), (-1,-1), "TOP"),
       ("LEFTPADDING", (0,0), (-1,-1), -1),
    ]))

    elements.append(bottom_section)
    elements.append(Spacer(1, 10))

    doc.build(elements)
    return response


# role perms
invoice_pdf_view.cls.role_perms = {
    "admin": {"GET"},
    "franchise": {"GET"},
    "othershop": {"GET"},
    "growtag": {"GET"},
    "customer": set(),
}
#payments
class LocalInvoicePaymentViewSet(CreatedAuditMixin, viewsets.ModelViewSet):
    queryset = LocalInvoicePayment.objects.select_related("invoice").all().order_by("-id")
    authentication_classes = [
        JWTAuthentication,
        SessionAuthentication,
        UnifiedTokenAuthentication,
    ]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE", "PUT"},
        "franchise": {"GET", "POST", "PATCH", "PUT", "DELETE"},
        "othershop": {"GET", "POST", "PATCH", "PUT", "DELETE"},
        "growtag": {"GET"},
        "customer": {"GET"},
    }

    def get_serializer_class(self):
        if self.action in {"list", "retrieve"}:
            return LocalInvoicePaymentReadSerializer
        return LocalInvoicePaymentWriteSerializer

    def create(self, request, *args, **kwargs):
        """
        Return read serializer payload after successful create,
        so client receives id/invoice_number/created_by_info/pdf_url.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)

        instance = serializer.instance
        read_data = LocalInvoicePaymentReadSerializer(
            instance,
            context={"request": request},
        ).data
        headers = self.get_success_headers(read_data)
        return Response(read_data, status=status.HTTP_201_CREATED, headers=headers)

    def get_queryset(self):
        qs = super().get_queryset()

        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        if getattr(self.request, "shop", None):
            return qs.filter(invoice__assigned_shop=self.request.shop)

        if getattr(self.request, "growtag", None):
            return qs.filter(invoice__assigned_growtag=self.request.growtag)

        if getattr(self.request, "customer", None):
            return qs.filter(invoice__customer=self.request.customer)

        return qs.none()

    def perform_create(self, serializer):
        invoice = serializer.validated_data["invoice"]

        if getattr(self.request, "shop", None):
           if invoice.assigned_shop_id != self.request.shop.id:
               raise PermissionDenied("You cannot add payment to this invoice.")

        if getattr(self.request, "growtag", None):
            raise PermissionDenied("Growtag cannot add payment.")

        if getattr(self.request, "customer", None):
            raise PermissionDenied("Customer cannot add payment.")

        if invoice.status == "CANCELLED":
            raise PermissionDenied("Cannot add payment to cancelled invoice.")

        if invoice.status != "SENT":
            raise PermissionDenied("Payment allowed only when invoice status is SENT.")

        role, actor = get_actor(self.request)
        save_kwargs = {"created_on": timezone.now().date()}

        if role == "admin":
           save_kwargs["created_by"] = actor
           save_kwargs["created_by_role"] = "admin"
        elif role in ("franchise", "othershop", "shop"):
           save_kwargs["created_by_role"] = role
           save_kwargs["created_by_shop"] = actor
        elif role == "growtag":
           save_kwargs["created_by_role"] = "growtag"
           save_kwargs["created_by_growtag"] = actor
        elif role == "customer":
           save_kwargs["created_by_role"] = "customer"
           save_kwargs["created_by_customer"] = actor

        payment = serializer.save(**save_kwargs)
        try:
            invoice.update_payment_status(save=True)
            apply_invoice_stock_deduction_if_final(invoice)
        except DjangoValidationError as e:
            payment.delete()
            raise ValidationError({"stock": e.messages})

    def perform_update(self, serializer):
        payment = self.get_object()
        invoice = payment.invoice

        if getattr(self.request, "shop", None):
            if invoice.assigned_shop_id != self.request.shop.id:
                raise PermissionDenied("You cannot edit payment for this invoice.")

        if getattr(self.request, "growtag", None):
            raise PermissionDenied("Growtag cannot edit payment.")

        if getattr(self.request, "customer", None):
            raise PermissionDenied("Customer cannot edit payment.")
        if invoice.status == "CANCELLED":
            raise PermissionDenied("Cannot edit payment of cancelled invoice.")

        if invoice.status != "SENT":
            raise PermissionDenied("Payment allowed only when invoice status is SENT.")

        serializer.save()
        invoice.update_payment_status(save=True)
        apply_invoice_stock_deduction_if_final(invoice)

    def perform_destroy(self, instance):
        invoice = instance.invoice

        if getattr(self.request, "shop", None):
            if invoice.assigned_shop_id != self.request.shop.id:
                raise PermissionDenied("You cannot delete payment for this invoice.")

        if getattr(self.request, "growtag", None):
            raise PermissionDenied("Growtag cannot delete payment.")

        if getattr(self.request, "customer", None):
            raise PermissionDenied("Customer cannot delete payment.")
        if invoice.status == "CANCELLED":
            raise PermissionDenied("Cannot delete payment from cancelled invoice.")
        super().perform_destroy(instance)
        invoice.update_payment_status(save=True)
   
#payment pdf
def payment_register_unicode_font():
    font_path = os.path.join(settings.BASE_DIR, "fonts", "NotoSans-Regular.ttf")
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont("NotoSans", font_path))
            return "NotoSans"
        except Exception:
            pass
    return "Helvetica"


def payment_money(value):
    value = Decimal(value or 0)
    return f"₹ {value:,.2f}"


def payment_para(text, style):
    return Paragraph(str(text or "").replace("\n", "<br/>"), style)
@api_view(["GET"])
@authentication_classes([JWTAuthentication, SessionAuthentication, UnifiedTokenAuthentication])
@permission_classes([CrudByRole])
def payment_receipt_pdf_view(request, pk):
    payment = get_object_or_404(
        LocalInvoicePayment.objects.select_related(
            "invoice",
            "invoice__customer",
            "invoice__assigned_shop",
            "invoice__assigned_growtag",
        ),
        pk=pk
    )

    invoice = payment.invoice

    # permissions
    u = getattr(request, "user", None)
    if u and u.is_authenticated and u.is_staff:
        pass
    elif getattr(request, "shop", None):
        if invoice.assigned_shop_id != request.shop.id:
            raise PermissionDenied("You cannot access this payment receipt.")
    elif getattr(request, "growtag", None):
        if invoice.assigned_growtag_id != request.growtag.id:
            raise PermissionDenied("You cannot access this payment receipt.")
    elif getattr(request, "customer", None):
        if invoice.customer_id != request.customer.id:
            raise PermissionDenied("You cannot access this payment receipt.")
    else:
        raise PermissionDenied("Not allowed.")

    base_font = payment_register_unicode_font()
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="PayTitle",
        parent=styles["Title"],
        fontName=base_font,
        fontSize=24,
        leading=28,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    ))

    styles.add(ParagraphStyle(
        name="PaySmall",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#475569"),
    ))

    styles.add(ParagraphStyle(
        name="PayBody",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
    ))

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="payment_receipt_{payment.id}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Payment Receipt {payment.id}",
    )

    elements = []

    PAGE_WIDTH = 182 * mm
    LEFT_BOX_W = 112 * mm
    RIGHT_BOX_W = PAGE_WIDTH - LEFT_BOX_W   # 70 mm

    # logo
    logo_path = Path(settings.BASE_DIR) / "static" / "img" / "logo.jpg"
    if os.path.exists(logo_path):
        logo = Image(str(logo_path))
        logo.drawHeight = 25 * mm
        logo.drawWidth = 60 * mm
        logo.hAlign = "LEFT"
        elements.append(logo)
        elements.append(Spacer(1, 8))

    elements.append(Paragraph("PAYMENT RECEIPT", styles["PayTitle"]))

    right_style = ParagraphStyle(
        "PayOrgRight",
        parent=styles["PaySmall"],
        alignment=TA_RIGHT,
        wordWrap="CJK",
    )

    # organization details
    org_name = "Nabeel org"
    org_address = "Kerala, India"
    org_email = "nabeekm18@gmail.com"

    if getattr(invoice, "assigned_shop", None):
        shop = invoice.assigned_shop
        org_name = getattr(shop, "shop_name", "") or getattr(shop, "name", "") or org_name
        org_address = (
            getattr(shop, "address", "")
            or getattr(shop, "shop_address", "")
            or getattr(shop, "full_address", "")
            or org_address
        )
        org_email = getattr(shop, "email", "") or org_email

    elif getattr(invoice, "assigned_growtag", None):
        growtag = invoice.assigned_growtag
        org_name = getattr(growtag, "name", "") or org_name
        org_address = (
            getattr(growtag, "address", "")
            or getattr(growtag, "full_address", "")
            or org_address
        )
        org_email = getattr(growtag, "email", "") or org_email

    receipt_no = f"PR-{payment.id:05d}"

    left_block = Paragraph(
        f'Receipt Number: <b>{receipt_no}</b><br/>'
        f'Payment Date: <b>{payment.payment_date}</b><br/>'
        f'Invoice Number: <b>{invoice.invoice_number}</b>',
        styles["PaySmall"]
    )

    right_block = Paragraph(
        f"<b>{org_name}</b><br/>{org_address}<br/>{org_email}",
        right_style
    )

    header_tbl = Table(
        [[left_block, right_block]],
        colWidths=[122 * mm, 60 * mm],
        hAlign="LEFT"
    )
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(header_tbl)
    elements.append(Spacer(1, 10))

    # customer info
    customer_name = "-"
    customer_phone = "-"
    customer_email = "-"

    if getattr(invoice, "customer", None):
        customer = invoice.customer
        customer_name = getattr(customer, "name", "") or getattr(customer, "customer_name", "") or "-"
        customer_phone = getattr(customer, "phone", "") or getattr(customer, "phone_number", "") or "-"
        customer_email = getattr(customer, "email", "") or "-"

    info_data = [
        ["Customer Name", customer_name],
        ["Phone", customer_phone],
        ["Email", customer_email],
        ["Payment Mode", payment.get_payment_mode_display() if hasattr(payment, "get_payment_mode_display") else (payment.payment_mode or "-")],
        ["Reference No", payment.reference_no or "-"],
        ["Invoice Number", invoice.invoice_number or "-"],
    ]

    info_tbl = Table(info_data, colWidths=[42 * mm, 140 * mm], hAlign="LEFT")
    info_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cfd8e3")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_tbl)
    elements.append(Spacer(1, 10))

    # payment table
    data = [[
        "#", "Description", "Mode", "Reference", "Invoice", "Date", "Amount"
    ]]

    data.append([
        "1",
        f"Payment received from {customer_name}",
        payment.get_payment_mode_display() if hasattr(payment, "get_payment_mode_display") else (payment.payment_mode or "-"),
        payment.reference_no or "-",
        invoice.invoice_number or "-",
        str(payment.payment_date or "-"),
        payment_money(payment.amount),
    ])

    items_tbl = Table(
        data,
        colWidths=[8 * mm, 52 * mm, 24 * mm, 28 * mm, 24 * mm, 20 * mm, 26 * mm],
        repeatRows=1,
        hAlign="LEFT"
    )
    items_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e4d86")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8e3")),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (5, -1), "CENTER"),
        ("ALIGN", (6, 1), (6, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(items_tbl)
    elements.append(Spacer(1, 10))

    total_paid = Decimal(invoice.get_total_paid() or 0) if hasattr(invoice, "get_total_paid") else Decimal(payment.amount or 0)
    balance_due = Decimal(invoice.get_balance_due() or 0) if hasattr(invoice, "get_balance_due") else Decimal("0.00")

    totals = [
        ["Invoice Total", payment_money(invoice.grand_total)],
        ["Amount Received", payment_money(payment.amount)],
        ["Total Paid", payment_money(total_paid)],
        ["Balance Due", payment_money(balance_due)],
    ]

    totals_tbl = Table(
        totals,
        colWidths=[42 * mm, 28 * mm],
        hAlign="LEFT"
    )
    totals_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8e3")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 3), (-1, 3), colors.HexColor("#1e4d86")),
        ("TEXTCOLOR", (0, 3), (-1, 3), colors.white),
    ]))

    notes_left = [
        [Paragraph("<b>Received From</b>", styles["PayBody"])],
        [Paragraph(customer_name or "-", styles["PaySmall"])],
        [Paragraph("<b>Phone</b>", styles["PayBody"])],
        [Paragraph(customer_phone or "-", styles["PaySmall"])],
        [Paragraph("<b>Email</b>", styles["PayBody"])],
        [Paragraph(customer_email or "-", styles["PaySmall"])],
        [Paragraph("<b>Notes</b>", styles["PayBody"])],
        [Paragraph(payment.notes or "-", styles["PaySmall"])],
    ]

    notes_tbl = Table(
        notes_left,
        colWidths=[LEFT_BOX_W],
        hAlign="LEFT"
    )
    notes_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8e3")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    bottom_tbl = Table(
        [[notes_tbl, totals_tbl]],
        colWidths=[LEFT_BOX_W, RIGHT_BOX_W],
        hAlign="LEFT"
    )
    bottom_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (0, 0), "TOP"),
        ("VALIGN", (1, 0), (1, 0), "BOTTOM"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    elements.append(bottom_tbl)
    doc.build(elements)
    return response
payment_receipt_pdf_view.cls.role_perms = {
    "admin": {"GET"},
    "franchise": {"GET"},
    "othershop": {"GET"},
    "growtag": {"GET"},
    "customer": {"GET"},
}

#Quatation
# zoho_integration/views.py

class QuotationViewSet(BulkDeleteMixin, CreatedAuditMixin, viewsets.ModelViewSet):
    authentication_classes = [
        UnifiedTokenAuthentication,
        JWTAuthentication,
        SessionAuthentication,
    ]
    permission_classes = [CrudByRole]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    queryset = Quotation.objects.all().order_by("-id")

    role_perms = {
        "admin": {"GET", "POST", "PUT", "PATCH", "DELETE"},
        "franchise": {"GET", "POST", "PUT", "PATCH"},
        "othershop": {"GET", "POST", "PUT", "PATCH"},
        "growtag": {"GET", "POST", "PUT", "PATCH"},
        "customer": {"GET"},
    }

    def get_queryset(self):
        # auto-expire old quotations before returning queryset
        today = timezone.localdate()
        Quotation.objects.filter(
             expiry_date__lt=today,
             status="SENT"
            ).update(status="EXPIRED", updated_at=timezone.now())

        qs = super().get_queryset()

        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        if getattr(self.request, "shop", None):
            return qs.filter(shop=self.request.shop)
        if getattr(self.request, "growtag", None):
            return qs.filter(growtag=self.request.growtag)
        if getattr(self.request, "customer", None):
            return qs.filter(customer=self.request.customer)

        return qs.none()

    def get_serializer_class(self):
        if self.action in ["list", "retrieve"]:
            return QuotationReadSerializer
        return QuotationWriteSerializer

    def perform_create(self, serializer):
        """Set audit fields based on the creator"""
        role, actor = get_actor(self.request)
        
        # Prepare audit data
        audit_data = {
            "created_on": timezone.now().date(),
        }
        
        # Set fields based on role (matching your CreatedAuditMixin pattern)
        if role == "admin":
            audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
        
        # Get shop/growtag assignment based on request
        request_shop = getattr(self.request, "shop", None)
        request_growtag = getattr(self.request, "growtag", None)
        
        # Set shop/growtag for the quotation
        if request_shop:
            serializer.save(shop=request_shop, **audit_data)
        elif request_growtag:
            serializer.save(growtag=request_growtag, **audit_data)
        elif role == "admin":
            shop_id = self.request.data.get("shop")
            growtag_id = self.request.data.get("growtag")
            selected_shop = None
            selected_growtag = None
            if shop_id:
                selected_shop = Shop.objects.filter(id=shop_id).first()
            if growtag_id:
                selected_growtag = Growtags.objects.filter(id=growtag_id).first()
            serializer.save(shop=selected_shop, growtag=selected_growtag, **audit_data)
        else:
            serializer.save(**audit_data)

    def create(self, request, *args, **kwargs):
        write_serializer = QuotationWriteSerializer(
            data=request.data,
            context={"request": request}
        )
        write_serializer.is_valid(raise_exception=True)
        
        # This will call perform_create which handles audit fields
        self.perform_create(write_serializer)

        instance = write_serializer.instance

        # make sure newly created quotation also checks expiry
        instance.mark_expired(save=True)
        instance.refresh_from_db()
        
        read_serializer = QuotationReadSerializer(instance, context={"request": request})
        headers = self.get_success_headers(read_serializer.data)

        return Response({
            "detail": "Quotation created successfully",
            "data": read_serializer.data
        }, status=status.HTTP_201_CREATED, headers=headers)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()

        # before update, refresh expiry logic
        instance.mark_expired(save=True)
        instance.refresh_from_db()

        if instance.status == "EXPIRED":
            return Response(
                {"detail": "Expired quotation cannot be edited."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if instance.status in ["CONVERTED", "CANCELLED"]:
            return Response(
                {"detail": f"{instance.get_status_display()} quotation cannot be edited."},
                status=status.HTTP_400_BAD_REQUEST
            )

        write_serializer = QuotationWriteSerializer(
            instance,
            data=request.data,
            partial=partial,
            context={"request": request},
        )
        write_serializer.is_valid(raise_exception=True)
        self.perform_update(write_serializer)

        instance.refresh_from_db()

        # after update also recheck
        instance.mark_expired(save=True)
        instance.refresh_from_db()

        read_serializer = QuotationReadSerializer(instance, context={"request": request})
        return Response({
            "detail": "Quotation updated successfully",
            "data": read_serializer.data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=["get"], url_path="meta")
    def meta(self, request):
        data = {
            "choices": QuotationMetaSerializer({}).data,
            "company_state": getattr(getattr(request, "shop", None), "state", None),
        }
        return Response({
            "detail": "Meta data retrieved successfully",
            "data": data
        })

    @action(detail=False, methods=["get"], url_path="customers")
    def customers(self, request):
        qs = Customer.objects.all().order_by("customer_name")
        return Response({
            "detail": "Customers retrieved successfully",
            "data": QuotationCustomerMiniSerializer(qs, many=True).data
        })

    @action(detail=False, methods=["get"], url_path="items")
    def items(self, request):
        qs = LocalItem.objects.filter(is_active=True).order_by("name")
        return Response({
            "detail": "Items retrieved successfully",
            "data": QuotationItemMiniSerializer(qs, many=True).data
        })
    
    @action(detail=True, methods=["post"], url_path="accept")
    def accept_quotation(self, request, pk=None):
        quotation = self.get_object()

        # always re-check expiry first
        quotation.mark_expired(save=True)
        quotation.refresh_from_db()

        # if already expired, cannot accept
        if quotation.status == "EXPIRED":
            return Response(
                {"detail": "Quotation expired and cannot be accepted."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # only SENT quotation can be accepted
        if quotation.status != "SENT":
            return Response(
                {"detail": "Only sent quotation can be accepted."},
                status=status.HTTP_400_BAD_REQUEST
            )

        quotation.status = "ACCEPTED"
        quotation.save(update_fields=["status", "updated_at"])

        read_serializer = QuotationReadSerializer(quotation, context={"request": request})
        return Response({
            "detail": "Quotation accepted successfully",
            "data": read_serializer.data
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=["post"], url_path="convert")
    def convert_quotation(self, request, pk=None):
        quotation = self.get_object()

        if quotation.status != "ACCEPTED":
            return Response(
                {"detail": "Only accepted quotation can be converted."},
                status=status.HTTP_400_BAD_REQUEST
            )

        quotation.status = "CONVERTED"
        quotation.save(update_fields=["status", "updated_at"])

        read_serializer = QuotationReadSerializer(quotation, context={"request": request})
        return Response({
            "detail": "Quotation converted successfully",
            "data": read_serializer.data
        }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=["post"], url_path="send")
    def send_quotation(self, request, pk=None):
        quotation = self.get_object()

        if quotation.status != "DRAFT":
            return Response(
                {"detail": "Only draft quotation can be sent."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # if already past expiry date, do not send
        if quotation.expiry_date < timezone.localdate():
            quotation.status = "EXPIRED"
            quotation.save(update_fields=["status", "updated_at"])
            return Response(
                {"detail": "Quotation already expired and cannot be sent."},
                status=status.HTTP_400_BAD_REQUEST
            )

        quotation.status = "SENT"
        quotation.save(update_fields=["status", "updated_at"])

        read_serializer = QuotationReadSerializer(quotation, context={"request": request})
        return Response({
            "detail": "Quotation sent successfully",
            "data": read_serializer.data
        }, status=status.HTTP_200_OK)

#quatation pdf view
    
@api_view(["GET"])
@authentication_classes([JWTAuthentication, SessionAuthentication, UnifiedTokenAuthentication])
@permission_classes([CrudByRole])
def quotation_pdf_view(request, pk):
    quotation = get_object_or_404(Quotation, pk=pk)
    quotation.mark_expired(save=True)
    quotation.refresh_from_db()

    # permissions
    u = getattr(request, "user", None)
    if u and u.is_authenticated and u.is_staff:
        pass
    elif getattr(request, "shop", None):
        if quotation.shop_id != request.shop.id:
            raise PermissionDenied("You cannot access this quotation.")
    elif getattr(request, "growtag", None):
        if quotation.growtag_id != request.growtag.id:
            raise PermissionDenied("You cannot access this quotation.")

    elif getattr(request, "customer", None):
        if quotation.customer_id != request.customer.id:
            raise PermissionDenied("You cannot access this quotation.")
    else:
        raise PermissionDenied("Not allowed.")

    lines = quotation.lines.select_related("item").all()
    total_in_words = quotation_amount_to_words(quotation.grand_total)
    base_font = quotation_register_unicode_font()

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="QTitle",
        parent=styles["Title"],
        fontName=base_font,
        fontSize=24,
        leading=28,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    ))

    styles.add(ParagraphStyle(
        name="QSmall",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#475569"),
    ))

    styles.add(ParagraphStyle(
        name="QBody",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
    ))

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="quotation_{quotation.id}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Quotation {quotation.quotation_number}",
    )

    elements = []
    

    PAGE_WIDTH = 182 * mm   # usable width inside A4 after margins
    LEFT_BOX_W = 112 * mm
    RIGHT_BOX_W = PAGE_WIDTH - LEFT_BOX_W   # 70 mm

    # Header logo
    logo_path = Path(settings.BASE_DIR) / "static" / "img" / "logo.jpg"
    if os.path.exists(logo_path):
        logo = Image(str(logo_path))
        logo.drawHeight = 25 * mm
        logo.drawWidth = 60 * mm
        logo.hAlign = "LEFT"
        elements.append(logo)
        elements.append(Spacer(1, 8))

    elements.append(Paragraph("QUOTATION", styles["QTitle"]))

    right_style = ParagraphStyle(
        "QOrgRight",
        parent=styles["QSmall"],
        alignment=TA_RIGHT
    )

    left_block = Paragraph(
        f'Quotation Number: <b>{quotation.quotation_number}</b><br/>'
        f'Date: <b>{quotation.quotation_date}</b><br/>'
        f'Expiry Date: <b>{quotation.expiry_date}</b><br/>'
        f'Status: <b>{quotation.get_status_display()}</b>',
        styles["QSmall"]
    )

    right_block = Paragraph(
        "<b>Nabeel org</b><br/>Kerala, India<br/>nabeekm18@gmail.com",
        right_style
    )

    header_tbl = Table([[left_block, right_block]], colWidths=[122 * mm, 60 * mm], hAlign="LEFT")
    header_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(header_tbl)
    elements.append(Spacer(1, 10))

    # Customer section
    customer_data = [
        ["Customer Name", quotation.customer.customer_name if quotation.customer else "-"],
        ["Phone", getattr(quotation.customer, "customer_phone", "-") or "-"],
        ["Email", getattr(quotation.customer, "email", "-") or "-"],
        ["Customer State", quotation.customer_state or "-"],
        ["Company State", quotation.company_state or "-"],
        ["GST Mode", quotation.get_gst_mode_display() if quotation.gst_mode else "-"],
        ["Supply Type", quotation.get_supply_type_display() if quotation.supply_type else "-"],
    ]

    customer_tbl = Table(customer_data, colWidths=[42 * mm, 140 * mm], hAlign="LEFT")
    customer_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cfd8e3")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(customer_tbl)
    elements.append(Spacer(1, 10))

    # Items table
    data = [["#", "Item", "Description", "Qty", "Rate", "GST %", "Tax", "Amount"]]
    for i, ln in enumerate(lines, start=1):
        data.append([
            str(i),
            ln.item.name if ln.item else "",
            ln.description or "",
            str(ln.qty),
            quotation_money(ln.rate),
            f"{Decimal(ln.gst_percent):.2f}%",
            quotation_money(ln.line_tax),
            quotation_money(ln.line_total),
        ])

    items_tbl = Table(
        data,
        colWidths=[8 * mm, 38 * mm, 46 * mm, 14 * mm, 20 * mm, 16 * mm, 18 * mm, 22 * mm],
        repeatRows=1,
        hAlign="LEFT"
    )
    items_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e4d86")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8e3")),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (3, 1), (7, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(items_tbl)
    elements.append(Spacer(1, 10))

    # GST breakdown table
    gst_breakdown = build_gst_breakdown(lines, quotation.gst_mode)
    gst_data = [["GST Slab", "Taxable", "CGST", "SGST", "IGST", "Total Tax"]]

    for key, val in gst_breakdown.items():
        gst_data.append([
            str(key),
            quotation_money(val["taxable_amount"]),
            quotation_money(val["cgst_amount"]),
            quotation_money(val["sgst_amount"]),
            quotation_money(val["igst_amount"]),
            quotation_money(val["total_tax"]),
        ])

    gst_tbl = Table(
        gst_data,
        colWidths=[26 * mm, 30 * mm, 28 * mm, 28 * mm, 28 * mm, 42 * mm],
        repeatRows=1,
        hAlign="LEFT"
    )
    gst_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8e3")),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(gst_tbl)
    elements.append(Spacer(1, 10))

    # Totals section
      
    totals = [
        ["Sub Total", quotation_money(quotation.sub_total)],
        ["Discount (-)", quotation_money(quotation.discount_amount)],
        ["Shipping Charge", quotation_money(quotation.shipping_charge)],
        ["Service Charge", quotation_money(quotation.service_charge_amount)],
        ["Adjustment", quotation_money(quotation.adjustment)],
        ["Taxable Amount", quotation_money(quotation.taxable_amount)],
        ["Total Tax", quotation_money(quotation.total_tax)],
        ["GRAND TOTAL", quotation_money(quotation.grand_total)],
    ]

    totals_tbl = Table(
        totals,
        colWidths=[42 * mm, 28 * mm],
        hAlign="LEFT"
    )
    totals_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8e3")),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("BACKGROUND", (0, 7), (-1, 7), colors.HexColor("#1e4d86")),
        ("TEXTCOLOR", (0, 7), (-1, 7), colors.white),
    ]))

    notes_box = [
        Paragraph("<b>Total In Words</b>", styles["QBody"]),
        Spacer(1, 4),
        Paragraph(f"<i>{total_in_words}</i>", styles["QSmall"]),
        Spacer(1, 10),

        Paragraph("<b>Notes</b>", styles["QBody"]),
        Spacer(1, 4),
        Paragraph(quotation.notes or "-", styles["QSmall"]),
        Spacer(1, 10),

        Paragraph("<b>Terms and Conditions</b>", styles["QBody"]),
        Spacer(1, 4),
        Paragraph(quotation.terms_and_conditions or "-", styles["QSmall"]),
    ]

    bottom_tbl = Table(
        [[notes_box, totals_tbl]],
        colWidths=[LEFT_BOX_W, RIGHT_BOX_W],
        hAlign="LEFT"
    )

    bottom_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),

        # left side box border
        ("BOX", (0, 0), (0, 0), 0.8, colors.HexColor("#cfd8e3")),

        # remove outer spacing
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),

        # inner padding only for left box
        ("LEFTPADDING", (0, 0), (0, 0), 10),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, 0), (0, 0), 10),
    ]))

    elements.append(bottom_tbl)
    doc.build(elements)
    return response
quotation_pdf_view.cls.role_perms = {
    "admin": {"GET"},
    "franchise": {"GET"},
    "othershop": {"GET"},
    "growtag": {"GET"},
    "customer": {"GET"},
}
