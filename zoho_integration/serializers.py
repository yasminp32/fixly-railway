from rest_framework import serializers
from decimal import Decimal
from .models import LocalInvoice, LocalInvoiceLine,LocalItem,LocalInvoicePayment,Quotation, QuotationLine, AuditFields
from django.urls import reverse
from django.conf import settings
from django.db import transaction
from core.models import Customer, Shop
from django.utils import timezone
from django.db.models import Sum
from core.models import Vendor
from .utils import (
    q2,
    detect_gst_mode,
    split_tax_by_mode,
    calculate_discount,
    calculate_service_charge,
    build_gst_breakdown,
)

# zoho_integration/serializers.py

class LocalItemSerializer(serializers.ModelSerializer):
    status = serializers.BooleanField(source="is_active", read_only=True)
    preferred_vendor = serializers.PrimaryKeyRelatedField(
        queryset=Vendor.objects.all(),
        required=False,
        allow_null=True
    )
    
    # Audit fields - structured for clean response
    created_by_info = serializers.SerializerMethodField()
    
    class Meta:
        model = LocalItem
        fields = [
            "id",
            "status",
            "product_type",
            "name",
            "sku",
            "unit",
            "tax_preference",
            "gst_treatment",
            "hsn_or_sac",
            "item_image",
            "is_sellable",
            "selling_price",
            "service_charge",
            "sales_account",
            "sales_description",
            "is_purchasable",
            "cost_price",
            "purchase_account",
            "preferred_vendor",
            "purchase_description",
            "is_active",
            "zoho_item_id",
            "sync_status",
            "created_by_info",  # Single field with all creator info
            "created_at",
            "updated_at",
            "created_on",
        ]
        read_only_fields = [
            "id", "zoho_item_id", "sync_status", "created_at", 
            "updated_at", "created_on", "created_by_info",
        ]
    
    def get_created_by_info(self, obj):
        """
        Returns structured creator information
        {
            "role": "admin|franchise|othershop|growtag|customer",
            "id": 1,
            "name": "User/Shop/Growtag Name"
        }
        """
        if obj.created_by_role == "admin" and obj.created_by:
            
            return {
                "role": "admin",
                "id": obj.created_by.id,
                "name": obj.created_by.get_full_name() or obj.created_by.username,
                "email": obj.created_by.email or None
            }
        
        elif obj.created_by_role in ["franchise", "othershop", "shop"] and obj.created_by_shop:
            shop_email = None
            if hasattr(obj.created_by_shop, 'email'):
                shop_email = obj.created_by_shop.email
            elif hasattr(obj.created_by_shop, 'shop_email'):
                shop_email = obj.created_by_shop.shop_email
            elif hasattr(obj.created_by_shop, 'contact_email'):
                shop_email = obj.created_by_shop.contact_email
            return {
                "role": obj.created_by_role,
                "id": obj.created_by_shop.id,
                "name": obj.created_by_shop.shopname,
                "email": shop_email
            }
        
        elif obj.created_by_role == "growtag" and obj.created_by_growtag:
            # Try to get growtag name - adjust field name as needed
            growtag_name = None
            if hasattr(obj.created_by_growtag, 'name'):
                growtag_name = obj.created_by_growtag.name
            elif hasattr(obj.created_by_growtag, 'growtag_name'):
                growtag_name = obj.created_by_growtag.growtag_name
            else:
                growtag_name = str(obj.created_by_growtag)
                
            growtag_email = None
            if hasattr(obj.created_by_growtag, 'email'):
                growtag_email = obj.created_by_growtag.email
            elif hasattr(obj.created_by_growtag, 'growtag_email'):
                growtag_email = obj.created_by_growtag.growtag_email
            elif hasattr(obj.created_by_growtag, 'contact_email'):
                growtag_email = obj.created_by_growtag.contact_email
            
            return {
                "role": "growtag",
                "id": obj.created_by_growtag.id,
                "name": growtag_name,
                "email": growtag_email

            }

        
        return {
            "role": None,
            "id": None,
            "name": None
        }
        
        
class LocalInvoiceLineReadSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    class Meta:
        model = LocalInvoiceLine
        fields = [
            "id",
            "item",
            "item_name",
            "qty",
            "rate",
            "description",
            "service_charge_type",
            "service_charge_value",
            "gst_treatment",
            "line_amount",
            "service_charge_amount",
            "taxable_amount",
            "line_tax",
            "line_total",
            "created_at",
            "updated_at",
            
        ]
class LocalInvoiceLineWriteSerializer(serializers.Serializer):
    item_id = serializers.IntegerField()
    qty = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default="1.00")
    rate = serializers.DecimalField(max_digits=12, decimal_places=2, required=False, default="0.00")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    service_charge_type = serializers.ChoiceField(
        choices=LocalInvoiceLine.SERVICE_CHARGE_TYPE_CHOICES, required=False
    )
    service_charge_value = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False, default="0.00"
    )

    gst_treatment = serializers.ChoiceField(
        choices=LocalInvoiceLine.GST_CHOICES, required=False
    )

def _norm_state(s):
    return (s or "").strip().lower()

def _display_state(s):
    return (s or "").strip() or "-"

class LocalInvoiceReadSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.customer_name", read_only=True)
    customer_phone = serializers.CharField(source="customer.customer_phone", read_only=True)
    customer_email = serializers.CharField(source="customer.email", read_only=True)
    lines = LocalInvoiceLineReadSerializer(many=True, read_only=True)
    assigned_growtag = serializers.IntegerField(source="assigned_growtag_id", read_only=True)
    assigned_shop = serializers.IntegerField(source="assigned_shop_id", read_only=True)
    assigned_shop_type = serializers.CharField(source="assigned_shop.shop_type", read_only=True)
    assigned_shop_name = serializers.CharField(source="assigned_shop.shopname", read_only=True)
    growtag_name = serializers.CharField(source="assigned_growtag.name", read_only=True)
    payment_status = serializers.CharField(read_only=True)
    notes = serializers.CharField(read_only=True)
    adjustment = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    shipping_charge = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    company_state = serializers.SerializerMethodField()
    customer_state = serializers.SerializerMethodField()
    supply_type = serializers.SerializerMethodField()
    gst_mode = serializers.SerializerMethodField()
    payments = serializers.SerializerMethodField()
    total_paid = serializers.SerializerMethodField()
    balance_due = serializers.SerializerMethodField()
    pdf_url = serializers.SerializerMethodField()
    
    # NEW: Structured creator info
    created_by_info = serializers.SerializerMethodField()
    
    def get_company_state(self, obj):
        return getattr(settings, "COMPANY_STATE", "Kerala")

    def get_customer_state(self, obj):
        return _display_state(getattr(obj.customer, "state", ""))

    def get_supply_type(self, obj):
        company_state = _norm_state(getattr(settings, "COMPANY_STATE", "Kerala"))
        customer_state = _norm_state(getattr(obj.customer, "state", ""))

        if not customer_state:
            return "INTRASTATE"

        return "INTERSTATE" if customer_state != company_state else "INTRASTATE"
    
    def get_gst_mode(self, obj):
        gst_breakdown = obj.gst_breakdown or {}
        total_tax = sum(float(v.get("tax", 0) or 0) for v in gst_breakdown.values())
        if total_tax == 0:
            return "NO_TAX"

        supply = self.get_supply_type(obj)
        return "IGST" if supply == "INTERSTATE" else "CGST+SGST"
    
    def get_created_by_info(self, obj):
        """
        Returns structured creator information with role, id, name, and email
        """
        # Admin user (created_by)
        if obj.created_by_role == "admin" and obj.created_by:
            return {
                "role": "admin",
                "id": obj.created_by.id,
                "name": obj.created_by.get_full_name() or obj.created_by.username,
                "email": obj.created_by.email or None
            }
        
        # Shop (franchise, othershop, shop)
        elif obj.created_by_role in ["franchise", "othershop", "shop"] and obj.created_by_shop:
            shop = obj.created_by_shop
            # Get shop email
            shop_email = None
            if hasattr(shop, 'email'):
                shop_email = shop.email
            elif hasattr(shop, 'shop_email'):
                shop_email = shop.shop_email
            
            return {
                "role": obj.created_by_role,
                "id": shop.id,
                "name": shop.shopname,
                "email": shop_email
            }
        
        # Growtag
        elif obj.created_by_role == "growtag" and obj.created_by_growtag:
            growtag = obj.created_by_growtag
            # Get growtag name
            growtag_name = None
            if hasattr(growtag, 'name'):
                growtag_name = growtag.name
            elif hasattr(growtag, 'growtag_name'):
                growtag_name = growtag.growtag_name
            else:
                growtag_name = str(growtag)
            
            # Get growtag email
            growtag_email = None
            if hasattr(growtag, 'email'):
                growtag_email = growtag.email
            elif hasattr(growtag, 'growtag_email'):
                growtag_email = growtag.growtag_email
            
            return {
                "role": "growtag",
                "id": growtag.id,
                "name": growtag_name,
                "email": growtag_email
            }
        
        # Customer
        elif obj.created_by_role == "customer" and obj.created_by_customer:
            customer = obj.created_by_customer
            return {
                "role": "customer",
                "id": customer.id,
                "name": customer.customer_name,
                "email": customer.email or None
            }
        
        # Default fallback
        return {
            "role": None,
            "id": None,
            "name": None,
            "email": None
        }
    
    def get_pdf_url(self, obj):
        request = self.context.get("request")
        url = reverse("invoice-pdf", kwargs={"pk": obj.pk})
        return request.build_absolute_uri(url) if request else url
    
    def get_payments(self, obj):
        qs = obj.payments.all().order_by("-id")
        return LocalInvoicePaymentReadSerializer(qs, many=True, context=self.context).data

    def get_total_paid(self, obj):
        total = obj.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return str(total)

    def get_balance_due(self, obj):
        total = obj.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        balance = Decimal(obj.grand_total or 0) - Decimal(total)
        if balance < 0:
            balance = Decimal("0.00")
        return str(balance)
    
    class Meta:
        model = LocalInvoice
        fields = [
            "id",
            "customer",
            "customer_name",
            "customer_phone",
            "customer_email",
            "invoice_number",
            "status",
            "payment_status",
            "invoice_date",
            "due_date",
            "sub_total",
            "service_charge_total",
            "discount_type",
            "discount_value",
            "discount_amount",
            "taxable_amount",
            "gst_breakdown",
            "shipping_charge",
            "adjustment",
            "notes",
            "grand_total",
            "terms_conditions",
            "assigned_growtag",
            "growtag_name",
            "assigned_shop",
            "assigned_shop_name",
            "assigned_shop_type",
            "company_state",
            "customer_state",
            "supply_type",
            "gst_mode",
            "zoho_invoice_id",
            "total_paid",
            "balance_due",
            "payments",
            "sync_status",
            "last_error",
            "created_at",    
            "updated_at",
            "lines",
            "created_by_info",  
            "pdf_url",           
        ]
    
class LocalInvoiceWriteSerializer(serializers.ModelSerializer):
    customer = serializers.PrimaryKeyRelatedField(queryset=Customer.objects.all())

    # 👇 list of line items (POST/PUT/PATCH in JSON "Raw data")
    lines_payload = LocalInvoiceLineWriteSerializer(many=True, write_only=True, required=False)

    class Meta:
        model = LocalInvoice
        fields = [
            "customer",
            "complaint",
            "assigned_growtag", 
            "status",  
            "assigned_shop",      
            "invoice_date",
            "due_date",
            "terms_conditions",
            "notes",
            "shipping_charge",
            "adjustment", 
            "discount_type",
            "discount_value",
            "lines_payload",
            
        ]
    
    def validate(self, attrs):
        request = self.context.get("request")
        request_shop = getattr(request, "shop", None) if request else None
        request_growtag = getattr(request, "growtag", None) if request else None
        # If discount_value is sent but discount_type missing
        if "discount_value" in attrs and "discount_type" not in attrs:
           attrs["discount_type"] = "AMOUNT"

        dt = attrs.get("discount_type")
        dv = Decimal(attrs.get("discount_value") or 0)

        if dt == "PERCENT" and (dv < 0 or dv > 100):
           raise serializers.ValidationError({"discount_value": "Percent must be 0..100"})
        if dt == "AMOUNT" and dv < 0:
           raise serializers.ValidationError({"discount_value": "Amount cannot be negative"})
        shipping_charge = Decimal(attrs.get("shipping_charge", getattr(self.instance, "shipping_charge", 0)) or 0)
        adjustment = Decimal(attrs.get("adjustment", getattr(self.instance, "adjustment", 0)) or 0)

        if shipping_charge < 0:
            raise serializers.ValidationError({"shipping_charge": "Shipping charge cannot be negative"})
        # ✅ Only enforce owner validation for admin/unknown
        if not (getattr(request, "shop", None) or getattr(request, "growtag", None)):
            shop = attrs.get("assigned_shop") if "assigned_shop" in attrs else getattr(self.instance, "assigned_shop", None)
            growtag = attrs.get("assigned_growtag") if "assigned_growtag" in attrs else getattr(self.instance, "assigned_growtag", None)

            if shop and growtag:
               raise serializers.ValidationError("Invoice cannot be assigned to both shop and growtag.")
            if not shop and not growtag:
               raise serializers.ValidationError("Invoice must be assigned to either shop or growtag.")
        status_value = attrs.get("status")
        if status_value and status_value not in ["DRAFT", "SENT", "CANCELLED"]:
            raise serializers.ValidationError({"status": "Invalid invoice status."})

        return attrs
    def validate_lines_payload(self, lines):
        if not lines:
            return lines

        item_ids = [x["item_id"] for x in lines]
        existing = set(LocalItem.objects.filter(id__in=item_ids).values_list("id", flat=True))
        missing = [i for i in item_ids if i not in existing]
        if missing:
            raise serializers.ValidationError(f"Invalid item_id(s): {missing}")
        return lines
    

    def _upsert_lines(self, invoice, lines_payload):
        """
        Creates invoice lines from payload.
        (Simple version: always create new lines)
        """
        if not lines_payload:
            return

        for row in lines_payload:
            LocalInvoiceLine.objects.create(
                invoice=invoice,
                item_id=row["item_id"],
                qty=row.get("qty", Decimal("1.00")),
                rate=row.get("rate", Decimal("0.00")),
                description=row.get("description", ""),
                service_charge_type=row.get("service_charge_type", "AMOUNT"),
                service_charge_value=row.get("service_charge_value", Decimal("0.00")),
                gst_treatment=row.get("gst_treatment", "NO_TAX"),
            )
#payments
class LocalInvoicePaymentReadSerializer(serializers.ModelSerializer):
    invoice_number = serializers.CharField(source="invoice.invoice_number", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    created_by_info = serializers.SerializerMethodField()
    class Meta:
        model = LocalInvoicePayment
        fields = [
            "id",
            "invoice",
            "invoice_number",
            "amount",
            "payment_date",
            "payment_mode",
            "reference_no",
            "notes",
            "pdf_url",
            "created_at",
            "updated_at",
            "created_by_info",
        ]
    def get_pdf_url(self, obj):
        request = self.context.get("request")
        url = f"/invoice-payments/{obj.id}/pdf/"
        return request.build_absolute_uri(url) if request else url
    def get_created_by_info(self, obj):
        """
        Returns structured creator information with role, id, name, and email
        """
        # Admin user (created_by)
        if obj.created_by_role == "admin" and obj.created_by:
            return {
                "role": "admin",
                "id": obj.created_by.id,
                "name": obj.created_by.get_full_name() or obj.created_by.username,
                "email": obj.created_by.email or None
            }
        
        # Shop (franchise, othershop, shop)
        elif obj.created_by_role in ["franchise", "othershop", "shop"] and obj.created_by_shop:
            shop = obj.created_by_shop
            # Get shop email
            shop_email = None
            if hasattr(shop, 'email'):
                shop_email = shop.email
            elif hasattr(shop, 'shop_email'):
                shop_email = shop.shop_email
            
            return {
                "role": obj.created_by_role,
                "id": shop.id,
                "name": shop.shopname,
                "email": shop_email
            }
        
        # Growtag
        elif obj.created_by_role == "growtag" and obj.created_by_growtag:
            growtag = obj.created_by_growtag
            # Get growtag name
            growtag_name = None
            if hasattr(growtag, 'name'):
                growtag_name = growtag.name
            elif hasattr(growtag, 'growtag_name'):
                growtag_name = growtag.growtag_name
            else:
                growtag_name = str(growtag)
            
            # Get growtag email
            growtag_email = None
            if hasattr(growtag, 'email'):
                growtag_email = growtag.email
            elif hasattr(growtag, 'growtag_email'):
                growtag_email = growtag.growtag_email
            
            return {
                "role": "growtag",
                "id": growtag.id,
                "name": growtag_name,
                "email": growtag_email
            }
        
        # Customer
        elif obj.created_by_role == "customer" and obj.created_by_customer:
            customer = obj.created_by_customer
            return {
                "role": "customer",
                "id": customer.id,
                "name": customer.customer_name,
                "email": customer.email or None
            }
        
        # Default fallback
        return {
            "role": None,
            "id": None,
            "name": None,
            "email": None
        }

class LocalInvoicePaymentWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocalInvoicePayment
        fields = [
            "invoice",
            "amount",
            "payment_date",
            "payment_mode",
            "reference_no",
            "notes",
        ]
    def validate(self, attrs):
        invoice = attrs.get("invoice") or getattr(self.instance, "invoice", None)
        amount = Decimal(attrs.get("amount") or getattr(self.instance, "amount", 0) or 0)

        if not invoice:
            raise serializers.ValidationError({"invoice": "Invoice is required."})
        if invoice.status != "SENT":
           raise serializers.ValidationError({"invoice": "Payment can be added only when invoice status is SENT."})

        if invoice.status == "CANCELLED":
           raise serializers.ValidationError({"invoice": "Cannot add payment for cancelled invoice."})

        if amount <= Decimal("0.00"):
            raise serializers.ValidationError({"amount": "Payment amount must be greater than 0."})

        old_amount = Decimal("0.00")
        if self.instance:
            old_amount = Decimal(self.instance.amount or 0)

        total_paid_except_current = Decimal(invoice.get_total_paid() or 0) - old_amount
        new_total = total_paid_except_current + amount

        if new_total > Decimal(invoice.grand_total or 0):
            raise serializers.ValidationError({
                "amount": f"Payment exceeds balance due. Current balance is {invoice.get_balance_due()}."
            })

        return attrs
#quatation
# ----------------------------
# dropdown / read helpers
# ----------------------------
# zoho_integration/serializers.py (or wherever your quotation serializers are)

class QuotationCustomerMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["id", "customer_name", "customer_phone", "email", "state", "address", "pincode"]


class QuotationItemMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocalItem
        fields = ["id", "name"]


# ----------------------------
# line serializers
# ----------------------------

class QuotationLineWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuotationLine
        fields = [
            "id",
            "item",
            "description",
            "qty",
            "rate",
            "gst_percent",
        ]


class QuotationLineReadSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)

    class Meta:
        model = QuotationLine
        fields = [
            "id",
            "item",
            "item_name",
            "description",
            "qty",
            "rate",
            "gst_percent",
            "line_subtotal",
            "cgst_amount",
            "sgst_amount",
            "igst_amount",
            "line_tax",
            "line_total",
        ]


# ----------------------------
# main read serializer with audit info
# ----------------------------

class QuotationReadSerializer(serializers.ModelSerializer):
    customer_name = serializers.CharField(source="customer.customer_name", read_only=True)
    lines = QuotationLineReadSerializer(many=True, read_only=True)
    gst_breakdown = serializers.SerializerMethodField()
    gst_mode_display = serializers.CharField(source="get_gst_mode_display", read_only=True)
    supply_type_display = serializers.CharField(source="get_supply_type_display", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    
    # Audit fields - structured creator info
    created_by_info = serializers.SerializerMethodField()
    
    class Meta:
        model = Quotation
        fields = [
            "id",
            "customer",
            "customer_name",
            "quotation_number",
            "reference_number",
            "quotation_date",
            "expiry_date",
            "status",
            "company_state",
            "customer_state",
            "gst_mode",
            "gst_mode_display",
            "supply_type",
            "supply_type_display",
            "sub_total",
            "discount_type",
            "discount_value",
            "discount_amount",
            "shipping_charge",
            "service_charge_type",
            "service_charge_value",
            "service_charge_amount",
            "adjustment",
            "taxable_amount",
            "total_tax",
            "grand_total",
            "notes",
            "terms_and_conditions",
            "attachment",
            "gst_breakdown",
            "pdf_url",
            "lines",
            "created_by_info",  # Added audit field
            "created_at",
            "updated_at",
        ]
    
    def get_pdf_url(self, obj):
        request = self.context.get("request")
        url = reverse("quotation-pdf", kwargs={"pk": obj.pk})
        return request.build_absolute_uri(url) if request else url
    
    def get_gst_breakdown(self, obj):
        breakdown = build_gst_breakdown(obj.lines.all(), obj.gst_mode)
        # convert Decimal to string for JSON response
        final = {}
        for k, v in breakdown.items():
            final[k] = {
                "taxable_amount": str(v["taxable_amount"]),
                "cgst_amount": str(v["cgst_amount"]),
                "sgst_amount": str(v["sgst_amount"]),
                "igst_amount": str(v["igst_amount"]),
                "total_tax": str(v["total_tax"]),
                "gst_mode": v["gst_mode"],
            }
        return final
    
    def get_created_by_info(self, obj):
        """
        Returns structured creator information with role, id, name, and email
        {
            "role": "admin|franchise|othershop|growtag|customer",
            "id": 1,
            "name": "User/Shop/Growtag Name",
            "email": "user@example.com"
        }
        """
        # Check created_by_user (admin)
        if obj.created_by_user:
            return {
                "role": "admin",
                "id": obj.created_by_user.id,
                "name": obj.created_by_user.get_full_name() or obj.created_by_user.username,
                "email": obj.created_by_user.email or None
            }
        
        # Check created_by_shop (franchise, othershop, shop)
        elif obj.created_by_shop:
            shop = obj.created_by_shop
            # Determine role from shop_type
            role = shop.shop_type if shop.shop_type in ["franchise", "othershop"] else "shop"
            
            # Get shop email
            shop_email = None
            if hasattr(shop, 'email'):
                shop_email = shop.email
            elif hasattr(shop, 'shop_email'):
                shop_email = shop.shop_email
            
            return {
                "role": role,
                "id": shop.id,
                "name": shop.shopname,
                "email": shop_email
            }
        
        # Check created_by_growtag
        elif obj.created_by_growtag:
            growtag = obj.created_by_growtag
            
            # Get growtag name
            growtag_name = None
            if hasattr(growtag, 'name'):
                growtag_name = growtag.name
            elif hasattr(growtag, 'growtag_name'):
                growtag_name = growtag.growtag_name
            else:
                growtag_name = str(growtag)
            
            # Get growtag email
            growtag_email = None
            if hasattr(growtag, 'email'):
                growtag_email = growtag.email
            elif hasattr(growtag, 'growtag_email'):
                growtag_email = growtag.growtag_email
            
            return {
                "role": "growtag",
                "id": growtag.id,
                "name": growtag_name,
                "email": growtag_email
            }
        
        # Check created_by_customer
        elif obj.created_by_customer:
            customer = obj.created_by_customer
            
            # Get customer email
            customer_email = None
            if hasattr(customer, 'email'):
                customer_email = customer.email
            elif hasattr(customer, 'customer_email'):
                customer_email = customer.customer_email
            
            return {
                "role": "customer",
                "id": customer.id,
                "name": customer.customer_name,
                "email": customer_email
            }
        
        # Default fallback
        return {
            "role": None,
            "id": None,
            "name": None,
            "email": None
        }


# ----------------------------
# main write serializer
# ----------------------------

class QuotationWriteSerializer(serializers.ModelSerializer):
    lines = QuotationLineWriteSerializer(many=True, write_only=True)

    customer_name = serializers.CharField(source="customer.customer_name", read_only=True)
    customer_state_display = serializers.CharField(source="customer_state", read_only=True)
    company_state_display = serializers.CharField(source="company_state", read_only=True)

    gst_mode = serializers.CharField(read_only=True)
    supply_type = serializers.CharField(required=False, default="GOODS")

    class Meta:
        model = Quotation
        fields = [
            "id",
            "customer",
            "quotation_number",
            "reference_number",
            "quotation_date",
            "expiry_date",
            "status",
            "company_state",
            "customer_state",
            "gst_mode",
            "supply_type",
            "discount_type",
            "discount_value",
            "shipping_charge",
            "service_charge_type",
            "service_charge_value",
            "adjustment",
            "notes",
            "terms_and_conditions",
            "attachment",
            "lines",
            "customer_name",
            "customer_state_display",
            "company_state_display",
        ]

    def validate(self, attrs):
        instance = getattr(self, "instance", None)
        request = self.context.get("request")
        customer = attrs.get("customer") or (instance.customer if instance else None)
        if not customer:
            raise serializers.ValidationError({"customer": "Customer is required."})
    
        # get company_state from request shop/admin payload/settings
        incoming_company_state = attrs.get("company_state")
        company_state = incoming_company_state

        # if shop logged in, take shop state automatically
        if request and getattr(request, "shop", None):
            company_state = request.shop.state

        # fallback from settings
        if not company_state:
            company_state = getattr(settings, "COMPANY_STATE", None)

        if not company_state:
            raise serializers.ValidationError({
                "company_state": "Company state is required. Set from shop state or settings.COMPANY_STATE."
            })

        customer_state = getattr(customer, "state", None)
        if not customer_state:
            raise serializers.ValidationError({
                "customer": "Selected customer does not have a state."
            })

        attrs["company_state"] = company_state
        attrs["customer_state"] = customer_state
        attrs["gst_mode"] = detect_gst_mode(company_state, customer_state)

        if not instance:
            lines = self.initial_data.get("lines", [])
            if not lines:
                raise serializers.ValidationError({"lines": "At least one item is required."})
        
        # -----------------------------
        # quotation expiry logic here
        # -----------------------------
        expiry_date = attrs.get("expiry_date", getattr(instance, "expiry_date", None))
        new_status = attrs.get("status", getattr(instance, "status", "DRAFT"))
        today = timezone.localdate()

        # if already expired by date, force status EXPIRED
        if expiry_date and expiry_date < today and new_status == "SENT":
            attrs["status"] = "EXPIRED"

        # block editing if existing quotation is already expired
        if instance:
            if instance.expiry_date and instance.expiry_date < today and instance.status == "SENT":
                raise serializers.ValidationError({
                       "detail": "This quotation is expired and cannot be modified."
                    })

            if instance.status == "EXPIRED":
                raise serializers.ValidationError({
                    "detail": "Expired quotation cannot be modified."
                })

            if instance.status in ["CONVERTED", "CANCELLED"]:
                raise serializers.ValidationError({
                    "detail": f"{instance.get_status_display()} quotation cannot be modified."
                })
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])

        quotation = Quotation.objects.create(**validated_data)

        sub_total = Decimal("0.00")
        total_tax = Decimal("0.00")

        line_objects = []

        for line_data in lines_data:
            qty = q2(line_data["qty"])
            rate = q2(line_data["rate"])
            gst_percent = q2(line_data.get("gst_percent", Decimal("18.00")))

            line_subtotal = q2(qty * rate)
            tax_data = split_tax_by_mode(line_subtotal, gst_percent, quotation.gst_mode)
            line_total = q2(line_subtotal + tax_data["line_tax"])

            line = QuotationLine.objects.create(
                quotation=quotation,
                item=line_data["item"],
                description=line_data.get("description"),
                qty=qty,
                rate=rate,
                gst_percent=gst_percent,
                line_subtotal=line_subtotal,
                cgst_amount=tax_data["cgst_amount"],
                sgst_amount=tax_data["sgst_amount"],
                igst_amount=tax_data["igst_amount"],
                line_tax=tax_data["line_tax"],
                line_total=line_total,
            )
            line_objects.append(line)

            sub_total += line_subtotal
            total_tax += tax_data["line_tax"]

        sub_total = q2(sub_total)
        total_tax = q2(total_tax)

        discount_amount = calculate_discount(
            sub_total,
            quotation.discount_type,
            quotation.discount_value
        )

        base_after_discount = q2(sub_total - discount_amount)

        service_charge_amount = calculate_service_charge(
            base_after_discount,
            quotation.service_charge_type,
            quotation.service_charge_value
        )

        taxable_amount = q2(
            base_after_discount
            + q2(quotation.shipping_charge)
            + q2(service_charge_amount)
            + q2(quotation.adjustment)
        )

        grand_total = q2(taxable_amount + total_tax)

        quotation.sub_total = sub_total
        quotation.discount_amount = discount_amount
        quotation.service_charge_amount = service_charge_amount
        quotation.taxable_amount = taxable_amount
        quotation.total_tax = total_tax
        quotation.grand_total = grand_total
        quotation.save()

        return quotation

    @transaction.atomic
    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # always recalculate gst mode from states
        instance.gst_mode = detect_gst_mode(instance.company_state, instance.customer_state)
        instance.save()

        if lines_data is not None:
            instance.lines.all().delete()

            sub_total = Decimal("0.00")
            total_tax = Decimal("0.00")

            for line_data in lines_data:
                qty = q2(line_data["qty"])
                rate = q2(line_data["rate"])
                gst_percent = q2(line_data.get("gst_percent", Decimal("18.00")))

                line_subtotal = q2(qty * rate)
                tax_data = split_tax_by_mode(line_subtotal, gst_percent, instance.gst_mode)
                line_total = q2(line_subtotal + tax_data["line_tax"])

                QuotationLine.objects.create(
                    quotation=instance,
                    item=line_data["item"],
                    description=line_data.get("description"),
                    qty=qty,
                    rate=rate,
                    gst_percent=gst_percent,
                    line_subtotal=line_subtotal,
                    cgst_amount=tax_data["cgst_amount"],
                    sgst_amount=tax_data["sgst_amount"],
                    igst_amount=tax_data["igst_amount"],
                    line_tax=tax_data["line_tax"],
                    line_total=line_total,
                )
            # always recalc totals from current lines
            sub_total = Decimal("0.00")
            total_tax = Decimal("0.00")

            for line in instance.lines.all():
                sub_total += q2(line.line_subtotal)
                total_tax += q2(line.line_tax)   
                
            sub_total = q2(sub_total)
            total_tax = q2(total_tax)

            discount_amount = calculate_discount(
                sub_total,
                instance.discount_type,
                instance.discount_value
            )

            base_after_discount = q2(sub_total - discount_amount)

            service_charge_amount = calculate_service_charge(
                base_after_discount,
                instance.service_charge_type,
                instance.service_charge_value
            )

            taxable_amount = q2(
                base_after_discount
                + q2(instance.shipping_charge)
                + q2(service_charge_amount)
                + q2(instance.adjustment)
            )

            grand_total = q2(taxable_amount + total_tax)

            instance.sub_total = sub_total
            instance.discount_amount = discount_amount
            instance.service_charge_amount = service_charge_amount
            instance.taxable_amount = taxable_amount
            instance.total_tax = total_tax
            instance.grand_total = grand_total
            instance.save()

        return instance


# ----------------------------
# dropdown choice serializer
# ----------------------------

class QuotationMetaSerializer(serializers.Serializer):
    gst_percent_choices = serializers.SerializerMethodField()
    discount_type_choices = serializers.SerializerMethodField()
    service_charge_type_choices = serializers.SerializerMethodField()
    supply_type_choices = serializers.SerializerMethodField()
    status_choices = serializers.SerializerMethodField()

    def get_gst_percent_choices(self, obj):
        return [
            {"value": "0.00", "label": "0%"},
            {"value": "0.25", "label": "0.25%"},
            {"value": "3.00", "label": "3%"},
            {"value": "5.00", "label": "5%"},
            {"value": "12.00", "label": "12%"},
            {"value": "18.00", "label": "18%"},
            {"value": "28.00", "label": "28%"},
        ]

    def get_discount_type_choices(self, obj):
        return [
            {"value": "AMOUNT", "label": "Amount"},
            {"value": "PERCENT", "label": "%"},
        ]

    def get_service_charge_type_choices(self, obj):
        return [
            {"value": "NONE", "label": "No Service Charge"},
            {"value": "AMOUNT", "label": "Amount"},
            {"value": "PERCENT", "label": "Percent"},
        ]

    def get_supply_type_choices(self, obj):
        return [
            {"value": "GOODS", "label": "Goods"},
            {"value": "SERVICES", "label": "Services"},
            {"value": "GOODS_SERVICES", "label": "Goods + Services"},
        ]

    def get_status_choices(self, obj):
        return [
            {"value": "DRAFT", "label": "Draft"},
            {"value": "SENT", "label": "Sent"},
            {"value": "ACCEPTED", "label": "Accepted"},
            {"value": "CONVERTED", "label": "Converted"},
            {"value": "EXPIRED", "label": "Expired"},
            {"value": "CANCELLED", "label": "Cancelled"},
        ]