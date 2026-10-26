from django.db import models
from django.conf import settings
from django.db.models import Max
from django.db import transaction
from core.models import Growtags, Shop,Customer
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.db.models import Sum
from core.utils import generate_document_number
# core/models.py (AuditFields)

class AuditFields(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    created_on = models.DateField(null=True, blank=True)

    # admin user (JWT)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by",
    )

    # ✅ token roles
    created_by_role = models.CharField(
        max_length=20,
        null=True, blank=True,
        choices=[
            ("admin", "Admin"),
            ("shop", "Shop"),
            ("franchise", "Franchise"),
            ("othershop", "Other Shop"),
            ("growtag", "Growtag"),
            ("customer", "Customer"),
        ],
    )

    created_by_shop = models.ForeignKey(
        "core.Shop",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by_shop",
    )
    created_by_growtag = models.ForeignKey(
        "core.Growtags",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by_growtag",
    )
    created_by_customer = models.ForeignKey(
        "core.Customer",
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by_customer",
    )

    class Meta:
        abstract = True
        
class LocalItem(AuditFields):
    # Basic fields
    product_type = models.CharField(
        max_length=20,
        choices=[("goods", "Goods"), ("service", "Service")],
        default="goods"
    )

    name = models.CharField(max_length=150)
    sku = models.CharField(
        max_length=100,
        unique=True,
        blank=True,
        null=True,
        help_text="Unique Stock Keeping Unit"
    )
    UNIT_CHOICES = [
        ("PIECE", "PIECE"),
        ("BOX", "BOX"),
        ("SET", "SET"),
        ("UNIT", "UNIT"),
    ]

    unit = models.CharField(
        max_length=20,
        choices=UNIT_CHOICES,
        default="PIECE"
    )
    TAX_PREFERENCE_CHOICES = [
        ("taxable", "Taxable"),
        ("non_taxable", "Non-Taxable"),
    ]
    tax_preference = models.CharField(
        max_length=20,
        choices=TAX_PREFERENCE_CHOICES,
        default="taxable"
    )
    
    GST_TREATMENT_CHOICES = [
        ("NO_TAX", "No Tax (0%)"),
        ("IGST_5", "5% IGST"),
        ("IGST_12", "12% IGST"),
        ("IGST_18", "18% IGST"),
        ("IGST_28", "28% IGST"),
        ("GST_5", "5% GST (2.5% CGST + 2.5% SGST)"),
        ("GST_12", "12% GST (6% CGST + 6% SGST)"),
        ("GST_18", "18% GST (9% CGST + 9% SGST)"),
        ("GST_28", "28% GST (14% CGST + 14% SGST)"),
    ]

    gst_treatment = models.CharField(
        max_length=20,
        choices=GST_TREATMENT_CHOICES,
        default="NO_TAX",
        blank=True,
    )
    hsn_or_sac = models.CharField(max_length=30, blank=True, null=True, unique=True)
    item_image = models.ImageField(upload_to="zoho_items/", null=True, blank=True)

    # Sales
    is_sellable = models.BooleanField(default=True)
    selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    service_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    SALES_ACCOUNT_CHOICES = [
        ("sales", "Sales"),
        ("service_income", "Service Income"),
        ("cogs", "Cost of Goods Sold"),
        ("other_income", "Other Income"),
    ]
    sales_account = models.CharField(
        max_length=50,
        choices=SALES_ACCOUNT_CHOICES,
        default="sales",
        blank=True
    )
    sales_description = models.TextField(blank=True, default="")

    # Purchase
    is_purchasable = models.BooleanField(default=False)
    cost_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    PURCHASE_ACCOUNT_CHOICES = [
        ("sales", "Sales"),
        ("service_income", "Service Income"),
        ("cogs", "Cost of Goods Sold"),
        ("other_income", "Other Income"),
    ]
    purchase_account = models.CharField(
        max_length=50,
        choices=PURCHASE_ACCOUNT_CHOICES,
        default="cogs",
        blank=True
    )
    preferred_vendor = models.ForeignKey(
        "core.Vendor",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="local_items"
    )
    purchase_description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    zoho_item_id = models.CharField(max_length=100, blank=True, null=True)
    sync_status = models.CharField(max_length=20, default="PENDING")  # PENDING/SYNCED/FAILED
 
# =========================
# CUSTOMER (already exists)
# =========================
class LocalCustomer(AuditFields):
    name = models.CharField(max_length=150)

    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, default="")
    state = models.CharField(max_length=60,null=True,blank=True)
    # Zoho reference
    zoho_contact_id = models.CharField(max_length=80,blank=True,default="",help_text="Zoho Books contact_id")
    # ✅ Sync tracking (add)
    sync_status = models.CharField(max_length=20, default="PENDING")  # PENDING/SYNCED/FAILED
    last_error = models.TextField(blank=True, default="")
    
    def __str__(self):
        return f"{self.name} - {self.state}"

    # =========================
    # INVOICE
    # =========================
class LocalInvoice(AuditFields):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SENT", "Sent"),
        ("CANCELLED", "Cancelled"),
    ]
    PAYMENT_STATUS_CHOICES = [
        ("UNPAID", "Unpaid"),
        ("PARTIALLY_PAID", "Partially Paid"),
        ("PAID", "Paid"),
        ("OVERDUE", "Overdue"),
    ]
    GST_TREATMENT_CHOICES = [
        ("NO_TAX", "No Tax (0%)"),

        ("GST_5", "5% GST (2.5% CGST + 2.5% SGST)"),
        ("GST_12", "12% GST (6% CGST + 6% SGST)"),
        ("GST_18", "18% GST (9% CGST + 9% SGST)"),
        ("GST_28", "28% GST (14% CGST + 14% SGST)"),

        ("IGST_5", "5% IGST"),
        ("IGST_12", "12% IGST"),
        ("IGST_18", "18% IGST"),
        ("IGST_28", "28% IGST"),
    ]
    
    complaint = models.OneToOneField(
        "core.Complaint",
        on_delete=models.PROTECT,
        related_name="invoice",
        null=True,
        blank=True
    )
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT,related_name="local_invoices")
    #invoice_number = models.CharField(max_length=50, blank=True, default="", unique=True, db_index=True) # INV-001
    invoice_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = generate_document_number("invoice")
        super().save(*args, **kwargs)
    def _generate_next_invoice_number(self) -> str:
        """
        Generates next invoice number like INV-0001, INV-0002...
        Safe under concurrency.
        """
        # Lock the latest invoice row so only one request can generate next number at a time
        last_invoice = (
            LocalInvoice.objects
            .select_for_update()
            .filter(invoice_number__startswith="INV-")
            .order_by("-id")
            .first()
        )

        if not last_invoice or not last_invoice.invoice_number:
            return "INV-0001"

        try:
            last_num = int(last_invoice.invoice_number.split("-")[-1])
        except Exception:
            last_num = 0

        return f"INV-{last_num + 1:04d}"
    def clean(self):
      if self.assigned_shop_id and self.assigned_growtag_id:
        raise ValidationError("Invoice cannot be assigned to both shop and growtag.")
      if not self.assigned_shop_id and not self.assigned_growtag_id:
        raise ValidationError("Invoice must be assigned to either shop or growtag.")
      
    def save(self, *args, **kwargs):
        # ✅ enforce clean() every time (owner mandatory)
        validate = kwargs.pop("validate", True)
        # Generate only on create
        if not self.pk and not self.invoice_number:
            with transaction.atomic():
                self.invoice_number = self._generate_next_invoice_number()
                if validate:
                   self.full_clean()
                super().save(*args, **kwargs)   # ✅ save INSIDE the transaction
            return
        if validate:
           self.full_clean()
        super().save(*args, **kwargs)
    @property
    def owner_type(self):
       if self.assigned_shop_id:
          return "shop"
       if self.assigned_growtag_id:
          return "growtag"
       return None

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default="UNPAID")
    invoice_date = models.DateField()
    due_date = models.DateField(blank=True, null=True)
    sub_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    service_charge_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    DISCOUNT_TYPE_CHOICES = [
    ("AMOUNT", "Rupees (₹)"),
    ("PERCENT", "Percentage (%)"),
      ]
    discount_type = models.CharField(max_length=10,choices=DISCOUNT_TYPE_CHOICES,default="PERCENT")
    discount_value = models.DecimalField(max_digits=12,decimal_places=2,default=0,help_text="If type=PERCENT → %, if type=AMOUNT → ₹")
    discount_amount = models.DecimalField(max_digits=12,decimal_places=2,default=0,help_text="Computed final discount in ₹")
    shipping_charge = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    adjustment = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True, default="")
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # optional: store GST breakup like {"GST_5": {"tax": 12.5, "amount": 250}, ...}
    gst_breakdown = models.JSONField(default=dict, blank=True)

    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    terms_conditions = models.TextField(blank=True, default="") 
    zoho_invoice_id = models.CharField(max_length=80,blank=True,default="",db_index=True,help_text="Zoho Books invoice_id") 
    assigned_growtag = models.ForeignKey(
        Growtags,
        on_delete=models.PROTECT,
        null=True, blank=True,
        db_index=True,
        related_name="local_invoices"
    )

    assigned_shop = models.ForeignKey(
        Shop,
        on_delete=models.PROTECT,
        null=True, blank=True,
        db_index=True,
        related_name="local_invoices"
    )
    sync_status = models.CharField(max_length=20,default="PENDING",blank=True)
    last_error = models.TextField(default="",blank=True)
    

    def __str__(self):
        return self.invoice_number or f"INV-{self.id}"
    
    def get_total_paid(self):
        total = self.payments.aggregate(total=Sum("amount"))["total"] or Decimal("0.00")
        return total

    def get_balance_due(self):
        balance = Decimal(self.grand_total or 0) - self.get_total_paid()
        if balance < 0:
            balance = Decimal("0.00")
        return balance

    def update_payment_status(self, save=True):
        total_paid = Decimal(self.get_total_paid() or 0)
        grand_total = Decimal(self.grand_total or 0)
        today = timezone.localdate()

        if self.status == "CANCELLED":
            new_status = "UNPAID"
        elif total_paid <= Decimal("0.00"):
            if self.due_date and self.due_date < today and grand_total > Decimal("0.00"):
                new_status = "OVERDUE"
            else:
                new_status = "UNPAID"
        elif total_paid < grand_total:
            if self.due_date and self.due_date < today:
                new_status = "OVERDUE"
            else:
                new_status = "PARTIALLY_PAID"
        else:
            new_status = "PAID"

        changed = self.payment_status != new_status
        self.payment_status = new_status

        if save and changed:
            self.save(update_fields=["payment_status", "updated_at"])

        return changed
from decimal import Decimal, ROUND_HALF_UP
class LocalInvoiceLine(AuditFields):
    GST_CHOICES = LocalInvoice.GST_TREATMENT_CHOICES

    invoice = models.ForeignKey(LocalInvoice, on_delete=models.CASCADE, related_name="lines")
    item = models.ForeignKey(LocalItem, on_delete=models.PROTECT)

    qty = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    rate = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    description = models.TextField(blank=True, default="")
    SERVICE_CHARGE_TYPE_CHOICES = [
    ("AMOUNT", "Rupees (₹)"),
    ("PERCENT", "Percentage (%)"),
     ]

    service_charge_type = models.CharField(max_length=10, choices=SERVICE_CHARGE_TYPE_CHOICES, default="AMOUNT")
    service_charge_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    gst_treatment = models.CharField(max_length=20, choices=GST_CHOICES, default="NO_TAX")

    line_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)          # qty*rate
    service_charge_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)       # line_amount + service_charge_amount
    line_tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)           # taxable_amount + line_tax
    
    def __str__(self):
       return f"Line #{self.id} - item:{self.item_id} (inv:{self.invoice_id})"

    # -----------------------------
    # Helpers
    # -----------------------------
    def _gst_rate_percent(self) -> Decimal:
        """Return GST/IGST percent as Decimal (e.g., 18)."""
        if not self.gst_treatment or self.gst_treatment == "NO_TAX":
            return Decimal("0")

        # Handles GST_18, IGST_18 etc.
        try:
            pct = self.gst_treatment.split("_")[1]
            return Decimal(pct)
        except Exception:
            return Decimal("0")

    def _q2(self, val: Decimal) -> Decimal:
        """Quantize to 2 decimals."""
        return (val or Decimal("0")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def recalc(self, save: bool = False):
        """Recalculate stored totals based on qty/rate/service charge/gst."""
        qty = Decimal(self.qty or 0)
        rate = Decimal(self.rate or 0)
        sc_val = Decimal(self.service_charge_value or 0)

        base_amount = qty * rate  # qty * rate
        base_amount = self._q2(base_amount)

        # service charge amount
        if self.service_charge_type == "PERCENT":
            sc_amount = (base_amount * sc_val) / Decimal("100")
        else:
            sc_amount = sc_val

        sc_amount = self._q2(sc_amount)

        taxable = self._q2(base_amount + sc_amount)

        gst_pct = self._gst_rate_percent()
        tax = self._q2((taxable * gst_pct) / Decimal("100"))

        total = self._q2(taxable + tax)

        self.line_amount = base_amount
        self.service_charge_amount = sc_amount
        self.taxable_amount = taxable
        self.line_tax = tax
        self.line_total = total

        if save:
            super(LocalInvoiceLine, self).save(update_fields=[
                    "line_amount", "service_charge_amount", "taxable_amount",
                    "line_tax", "line_total", "updated_at"
         ])

    def save(self, *args, **kwargs):
        do_recalc = kwargs.pop("recalc", True)
        if do_recalc:
           self.recalc(save=False)
        super().save(*args, **kwargs)
#payments
class LocalInvoicePayment(AuditFields):
    PAYMENT_MODE_CHOICES = [
        ("CASH", "Cash"),
        ("CARD", "Card"),
        ("UPI", "UPI"),
        ("BANK", "Bank Transfer"),
    ]

    invoice = models.ForeignKey(
        LocalInvoice,
        on_delete=models.CASCADE,
        related_name="payments"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateField()
    payment_mode = models.CharField(max_length=20, choices=PAYMENT_MODE_CHOICES, default="CASH")
    reference_no = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True, default="")

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.amount}"

    def clean(self):
        if Decimal(self.amount or 0) <= Decimal("0.00"):
           raise ValidationError({"amount": "Payment amount must be greater than 0."})

        if not self.invoice_id:
           raise ValidationError({"invoice": "Invoice is required."})

        if self.invoice.status != "SENT":
           raise ValidationError({"invoice": "Payment can be added only when invoice status is SENT."})

        if self.invoice.status == "CANCELLED":
           raise ValidationError({"invoice": "Cannot add payment to a cancelled invoice."})

        old_amount = Decimal("0.00")
        if self.pk:
            old_obj = LocalInvoicePayment.objects.filter(pk=self.pk).first()
            if old_obj:
               old_amount = Decimal(old_obj.amount or 0)

        total_paid_except_current = self.invoice.get_total_paid() - old_amount
        new_total = total_paid_except_current + Decimal(self.amount or 0)

        if new_total > Decimal(self.invoice.grand_total or 0):
            raise ValidationError({
            "amount": f"Payment exceeds balance due. Current balance is {self.invoice.get_balance_due()}."
        })
    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return super().delete(*args, **kwargs)
#Quatation
class Quotation(models.Model):
    STATUS_CHOICES = [
        ("DRAFT", "Draft"),
        ("SENT", "Sent"),
        ("ACCEPTED", "Accepted"),
        ("CONVERTED", "converted"),
        ("EXPIRED", "Expired"),
        ("CANCELLED", "Cancelled"),
    ]

    DISCOUNT_TYPE_CHOICES = [
        ("AMOUNT", "Amount"),
        ("PERCENT", "Percent"),
    ]

    GST_MODE_CHOICES = [
        ("INTRA", "Intra State"),   # CGST + SGST
        ("INTER", "Inter State"),   # IGST
    ]

    SUPPLY_TYPE_CHOICES = [
        ("GOODS", "Goods"),
        ("SERVICES", "Services"),
        ("GOODS_SERVICES", "Goods + Services"),
    ]

    SERVICE_CHARGE_TYPE_CHOICES = [
        ("NONE", "No Service Charge"),
        ("AMOUNT", "Amount"),
        ("PERCENT", "Percent"),
    ]
    
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_on = models.DateField(auto_now_add=True)
    
    # Creator fields
    created_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by_user",
    )
    created_by_shop = models.ForeignKey(
        "core.Shop",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by_shop",
    )
    created_by_growtag = models.ForeignKey(
        "core.Growtags",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by_growtag",
    )
    created_by_customer = models.ForeignKey(
        "core.Customer",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created_by_customer",
    )

    customer = models.ForeignKey(
        Customer,
        on_delete=models.PROTECT,
        related_name="quotations"
    )

    # optional shop / company snapshot
    shop = models.ForeignKey(
        Shop,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="quotations"
    )
    growtag = models.ForeignKey(
    "core.Growtags",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="quotations"
    )
    quotation_number = models.CharField(max_length=50, unique=True, blank=True, null=True)
    
    reference_number = models.CharField(max_length=100, blank=True, null=True)

    quotation_date = models.DateField(default=timezone.now)
    expiry_date = models.DateField()

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")

    # Snapshot fields
    company_state = models.CharField(max_length=100, blank=True, null=True)
    customer_state = models.CharField(max_length=100, blank=True, null=True)

    # derived
    gst_mode = models.CharField(max_length=10, choices=GST_MODE_CHOICES, blank=True)
    supply_type = models.CharField(max_length=20, choices=SUPPLY_TYPE_CHOICES, default="GOODS")

    # summary fields
    sub_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_type = models.CharField(max_length=10, choices=DISCOUNT_TYPE_CHOICES, default="AMOUNT")
    discount_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    shipping_charge = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    service_charge_type = models.CharField(
        max_length=10,
        choices=SERVICE_CHARGE_TYPE_CHOICES,
        default="NONE"
    )
    service_charge_value = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    service_charge_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    adjustment = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    grand_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    notes = models.TextField(blank=True, null=True)
    terms_and_conditions = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to="quotation_attachments/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.quotation_number
    def should_expire(self):
        """
        Quotation expires only when:
        expiry_date is before today
        current status is SENT
        """
        if not self.expiry_date:
            return False

        today = timezone.localdate()
        return self.expiry_date < today and self.status == "SENT"

    def mark_expired(self, save=True):
        """
        Mark quotation as expired if eligible.
        """
        if self.should_expire():
            self.status = "EXPIRED"
            if save:
                self.save(update_fields=["status", "updated_at"])
            return True
        return False

    def save(self, *args, **kwargs):
        if not self.quotation_number:
             self.quotation_number = generate_document_number("quotation")

        # auto-expire before save
        if self.should_expire():
            self.status = "EXPIRED"
        super().save(*args, **kwargs)


class QuotationLine(models.Model):
    GST_PERCENT_CHOICES = [
        (Decimal("0.00"), "0%"),
        (Decimal("0.25"), "0.25%"),
        (Decimal("3.00"), "3%"),
        (Decimal("5.00"), "5%"),
        (Decimal("12.00"), "12%"),
        (Decimal("18.00"), "18%"),
        (Decimal("28.00"), "28%"),
    ]

    quotation = models.ForeignKey(
        Quotation,
        on_delete=models.CASCADE,
        related_name="lines"
    )
    item = models.ForeignKey(
        LocalItem,
        on_delete=models.PROTECT,
        related_name="quotation_lines"
    )

    description = models.TextField(blank=True, null=True)
    qty = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    rate = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])

    gst_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("18.00")
    )

    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    cgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    sgst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    igst_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_tax = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    line_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.quotation.quotation_number} - {self.item}"   