# core/views_reports.py
from decimal import Decimal
from django.db.models import (
    Q, F, Value, Case, When, CharField,
    Sum, Count, DecimalField
)
from django.db.models.functions import Coalesce, TruncDate
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser

from core.models import Complaint, Growtags
from zoho_integration.models import LocalInvoice
from expenses.models import Expense  # adjust import if your app name differs
from core.authentication import  UnifiedTokenAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from core.permissions import CrudByRole
from rest_framework import status
from core.report_utils import (
    parse_int, year_month_week_range, export_xlsx, export_pdf
)
from zoho_integration.models import LocalCustomer

PAID_INVOICE_STATUSES = ["PAID", "PARTIALLY_PAID"]


class ReportBaseAPIView(APIView):
    authentication_classes = [
        JWTAuthentication,          # ✅ admin
        SessionAuthentication,
         UnifiedTokenAuthentication,
    ]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"GET"},
        "franchise": {"GET"},
        "othershop": {"GET"},
        "growtag": {"GET"},
        "customer": {"GET"},   # or set() to block customers
    }
    def apply_date_filters_datetime(self, qs, date_field: str):
        """
        For DateTimeField filters (Complaint.created_at etc.)
        """
        year = parse_int(self.request.query_params.get("year"))
        month = parse_int(self.request.query_params.get("month"))
        week = parse_int(self.request.query_params.get("week"))
        start, end = year_month_week_range(year=year, month=month, week=week)
        if start and end:
            qs = qs.filter(**{f"{date_field}__gte": start, f"{date_field}__lt": end})
        return qs

    def apply_date_filters_date(self, qs, date_field: str):
        """
        For DateField filters (LocalInvoice.invoice_date, Expense.date)
        """
        year = parse_int(self.request.query_params.get("year"))
        month = parse_int(self.request.query_params.get("month"))
        week = parse_int(self.request.query_params.get("week"))

        if not year:
            return qs

        # Year only
        if year and not month and not week:
            return qs.filter(**{f"{date_field}__year": year})

        # Year + month
        if year and month and not week:
            return qs.filter(**{f"{date_field}__year": year, f"{date_field}__month": month})

        # ISO week
        if year and week:
            # Django supports __week for DateField / DateTimeField (week number)
            # but it's not ISO-week safe for all DBs; still works in many cases.
            return qs.filter(**{f"{date_field}__year": year, f"{date_field}__week": week})

        return qs

    def apply_search(self, qs, lookups: list[str]):
        search = (self.request.query_params.get("search") or "").strip()
        if not search:
            return qs
        q = Q()
        for lk in lookups:
            q |= Q(**{lk: search}) if lk.endswith("__exact") else Q(**{lk: search})  # keep safe
        # For icontains fields, pass "field__icontains" in list
        q = Q()
        for lk in lookups:
            q |= Q(**{lk: search})
        return qs.filter(q)

    def maybe_export(self, filename, title, columns, rows):
        export = (self.request.query_params.get("export") or "").lower()
        if export == "xlsx":
            return export_xlsx(filename, columns, rows)
        if export == "pdf":
            return export_pdf(filename, title, columns, rows)
        return None


# =========================================================
# 1) Complaints Report
# ID | DATE | CUSTOMER NAME | ISSUE | ASSIGN TO | ASSIGN TYPE | STATUS
# Filters: year/month/week, status, assign_to, search
# =========================================================
class ComplaintsReportAPIView(ReportBaseAPIView):
    def get(self, request):
        qs = Complaint.objects.select_related("assigned_shop", "assigned_Growtags").all()
        # ✅ OWNER FILTER (important)
        if request.user and request.user.is_authenticated and request.user.is_staff:
           pass
        elif getattr(request, "shop", None):
           qs = qs.filter(assigned_shop=request.shop)
        elif getattr(request, "growtag", None):
           qs = qs.filter(assigned_Growtags=request.growtag)
        elif getattr(request, "customer", None):
           qs = qs.filter(customer=request.customer)  # only if Complaint has FK customer
        else:
           qs = qs.none()


        # created_at is DateTimeField (AuditModel)
        qs = self.apply_date_filters_datetime(qs, "created_at")

        status = request.query_params.get("status")
        if status and status.lower() != "all":
            qs = qs.filter(status__iexact=status)

        assign_to = (request.query_params.get("assign_to") or "").lower()
        if assign_to in ["franchise", "othershop", "growtag"]:
            qs = qs.filter(assign_to=assign_to)

        # Labels for UI
        qs = qs.annotate(
            assign_type_label=Case(
                When(assign_to="growtag", then=Value("Growtag")),
                When(assign_to="franchise", then=Value("Franchise")),
                When(assign_to="othershop", then=Value("Other Shop")),
                default=Value("Unassigned"),
                output_field=CharField(),
            ),
            assign_to_label=Case(
                When(assign_to="growtag", then=F("assigned_Growtags__name")),
                When(assign_to__in=["franchise", "othershop"], then=F("assigned_shop__shopname")),
                default=Value("-"),
                output_field=CharField(),
            ),
        )

        # search (icontains)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(customer_name__icontains=search)
                | Q(customer_phone__icontains=search)
                | Q(issue_details__icontains=search)
                | Q(status__icontains=search)
                | Q(assigned_shop__shopname__icontains=search)
                | Q(assigned_Growtags__name__icontains=search)
            )

        qs = qs.order_by("-created_at")[:5000]

        columns = ["ID", "DATE", "CUSTOMER NAME", "ISSUE", "ASSIGN TO", "ASSIGN TYPE", "STATUS"]
        rows = [
            [
                c.id,
                c.created_at.date().isoformat() if c.created_at else "",
                c.customer_name,
                (c.issue_details or "")[:80],
                c.assign_to_label or "-",
                c.assign_type_label,
                c.status,
            ]
            for c in qs
        ]

        export_resp = self.maybe_export("complaints_report", "Total Complaints Report", columns, rows)
        if export_resp:
            return export_resp

        return Response({"filters": request.query_params, "count": len(rows), "columns": columns, "results": rows})


# =========================================================
# 2) Grow Tags Report
# GROW ID | JOIN DATE | NAME | AADHAR NO | PHONE | EMAIL | STATUS
# Filters: year/month/week, status, search
# =========================================================
class GrowtagsReportAPIView(ReportBaseAPIView):

    def get(self, request):
        qs = Growtags.objects.all()

        # Admin -> all growtags
        if request.user and request.user.is_authenticated and request.user.is_staff:
            pass

        # Shop token -> only growtags assigned to this shop
        elif getattr(request, "shop", None):
            qs = qs.filter(assignment__shop=request.shop)

        # Growtag token -> only self
        elif getattr(request, "growtag", None):
            qs = qs.filter(id=request.growtag.id)

        # Customer / anonymous -> no access
        else:
            return Response({"detail": "Not allowed."}, status=403)

        # date filter
        qs = self.apply_date_filters_date(qs, "created_on")

        status = request.query_params.get("status")
        if status and status.lower() != "all":
            qs = qs.filter(status__iexact=status)

        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(grow_id__icontains=search)
                | Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(email__icontains=search)
                | Q(adhar__icontains=search)
                | Q(status__icontains=search)
            )

        qs = qs.order_by("-id")[:5000]

        columns = ["GROW ID", "JOIN DATE", "NAME", "AADHAR NO", "PHONE", "EMAIL", "STATUS"]
        rows = []
        for g in qs:
            rows.append([
                g.grow_id,
                str(getattr(g, "created_on", "")),
                g.name,
                g.adhar or "",
                g.phone or "",
                g.email or "",
                g.status,
            ])

        export_resp = self.maybe_export("growtags_report", "Total Growth Tags Report", columns, rows)
        if export_resp:
            return export_resp

        return Response({
            "filters": request.query_params,
            "count": len(rows),
            "columns": columns,
            "results": rows
        })

# =========================================================
# 3) Customers Report
# Based on Complaint rows (like your UI):
# CUSTOMER ID | DATE | NAME | PHONE | ISSUE | ASSIGN TO | ASSIGN TYPE
# Filters: year/month/week, assign_to, search
# =========================================================
class CustomersReportAPIView(ReportBaseAPIView):
    def get(self, request):
        qs = Complaint.objects.select_related("customer", "assigned_shop", "assigned_Growtags").all()
        # ✅ OWNER FILTER (important)
        if request.user and request.user.is_authenticated and request.user.is_staff:
           pass
        elif getattr(request, "shop", None):
           qs = qs.filter(assigned_shop=request.shop)
        elif getattr(request, "growtag", None):
           qs = qs.filter(assigned_Growtags=request.growtag)
        elif getattr(request, "customer", None):
           qs = qs.filter(customer=request.customer)  # only if Complaint has FK customer
        else:
           qs = qs.none()


        qs = self.apply_date_filters_datetime(qs, "created_at")

        assign_to = (request.query_params.get("assign_to") or "").lower()
        if assign_to in ["franchise", "othershop", "growtag"]:
            qs = qs.filter(assign_to=assign_to)

        qs = qs.annotate(
            assign_type_label=Case(
                When(assign_to="growtag", then=Value("Growtag")),
                When(assign_to="franchise", then=Value("Franchise")),
                When(assign_to="othershop", then=Value("Other Shop")),
                default=Value("Unassigned"),
                output_field=CharField(),
            ),
            assign_to_label=Case(
                When(assign_to="growtag", then=F("assigned_Growtags__name")),
                When(assign_to__in=["franchise", "othershop"], then=F("assigned_shop__shopname")),
                default=Value("-"),
                output_field=CharField(),
            ),
        )

        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(customer_name__icontains=search)
                | Q(customer_phone__icontains=search)
                | Q(issue_details__icontains=search)
                | Q(assigned_shop__shopname__icontains=search)
                | Q(assigned_Growtags__name__icontains=search)
            )

        qs = qs.order_by("-created_at")[:5000]

        columns = ["CUSTOMER ID", "DATE", "NAME", "PHONE", "ISSUE", "ASSIGN TO", "ASSIGN TYPE"]
        rows = []
        for c in qs:
            rows.append([
                c.customer_id if c.customer_id else "-",  # FK id if exists
                c.created_at.date().isoformat() if c.created_at else "",
                c.customer_name,
                c.customer_phone,
                (c.issue_details or "")[:80],
                c.assign_to_label or "-",
                c.assign_type_label,
            ])

        export_resp = self.maybe_export("customers_report", "Total Customers Report", columns, rows)
        if export_resp:
            return export_resp

        return Response({"filters": request.query_params, "count": len(rows), "columns": columns, "results": rows})


# =========================================================
# 4) Sales Summary Report
# DATE | INVOICE COUNT | TOTAL SALES | TOTAL SALES WITH TAX | TOTAL TAX AMOUNT
# Your invoice fields:
# - sub_total (pre tax) OR taxable_amount (better)
# - grand_total (with tax)
# Tax = grand_total - taxable_amount
# Filters: year/month/week, search
# =========================================================
class SalesSummaryReportAPIView(ReportBaseAPIView):
    def get(self, request):
        # Always return invoice-level fields (paid amount, customer name,
        # invoice number, balance due) in this report.
        detailed = True

        # Default behavior (backward compatible): keep the existing day-wise aggregate
        # report for PAID invoices.
        #
        # If `?detailed=1` is provided, return invoice-level rows including:
        # PAID AMOUNT, CUSTOMER NAME, INVOICE NUMBER, BALANCE DUE.
        if detailed:
            payment_status = (request.query_params.get("payment_status") or "PAID").strip()
            if payment_status.lower() == "all":
                payment_statuses = ["PAID", "PARTIALLY_PAID", "OVERDUE"]
            else:
                # allow "PAID,PARTIALLY_PAID"
                payment_statuses = [x.strip() for x in payment_status.split(",") if x.strip()]

            qs = LocalInvoice.objects.select_related(
                "customer",
                "assigned_shop",
                "assigned_growtag",
            ).filter(status="SENT", payment_status__in=payment_statuses)
        else:
            qs = LocalInvoice.objects.filter(status="SENT", payment_status="PAID")
        # ✅ OWNER FILTER
        if request.user and request.user.is_authenticated and request.user.is_staff:
          pass
        elif getattr(request, "shop", None):
            qs = qs.filter(assigned_shop=request.shop)
        elif getattr(request, "growtag", None):
            qs = qs.filter(assigned_growtag=request.growtag)
        elif getattr(request, "customer", None):
            cust = request.customer

            cust_phone = (
               getattr(cust, "phone", None)
               or getattr(cust, "customer_phone", None)
               or getattr(cust, "mobile", None)
               or getattr(cust, "phone_number", None)
                )

            if not cust_phone:
               qs = qs.none()
            else:
             # If your invoice.customer FK points to Zoho/LocalCustomer
             qs = qs.filter(customer__phone=cust_phone)   # change __phone if LocalCustomer uses different field

        else:
            qs = qs.none()


        # invoice_date is DateField
        qs = self.apply_date_filters_date(qs, "invoice_date")

        if detailed:
            search = (request.query_params.get("search") or "").strip()
            if search:
                qs = qs.filter(
                    Q(invoice_number__icontains=search)
                    | Q(customer__customer_name__icontains=search)
                    | Q(customer__name__icontains=search)
                )

            qs = qs.order_by("-invoice_date", "-id")

            columns = [
                "INVOICE DATE",
                "INVOICE NUMBER",
                "CUSTOMER NAME",
                "PAID AMOUNT",
                "BALANCE DUE",
                "TOTAL SALES",
                "TOTAL SALES WITH TAX",
                "TOTAL TAX AMOUNT",
            ]

            rows = []
            total_paid_amount = Decimal("0.00")
            total_balance_due = Decimal("0.00")
            total_sales_sum = Decimal("0.00")
            total_sales_with_tax_sum = Decimal("0.00")
            total_tax_amount_sum = Decimal("0.00")
            for inv in qs[:5000]:
                customer_name = (
                    getattr(inv.customer, "customer_name", None)
                    or getattr(inv.customer, "name", None)
                    or ""
                )

                total_sales = inv.taxable_amount or Decimal("0.00")
                total_sales_with_tax = inv.grand_total or Decimal("0.00")
                total_tax_amount = total_sales_with_tax - total_sales

                paid_amount = inv.get_total_paid() if hasattr(inv, "get_total_paid") else Decimal("0.00")
                balance_due = inv.get_balance_due() if hasattr(inv, "get_balance_due") else Decimal("0.00")

                rows.append([
                    str(inv.invoice_date) if inv.invoice_date else "",
                    inv.invoice_number or f"INV-{inv.id}",
                    customer_name,
                    str(paid_amount),
                    str(balance_due),
                    str(total_sales),
                    str(total_sales_with_tax),
                    str(total_tax_amount),
                ])

                total_paid_amount += paid_amount
                total_balance_due += balance_due
                total_sales_sum += total_sales
                total_sales_with_tax_sum += total_sales_with_tax
                total_tax_amount_sum += total_tax_amount

            # Keep response consistent with non-detailed mode: always add a "Total" row.
            # When there are no invoices, totals remain 0.
            rows.append([
                "Total",
                "",
                "",
                str(total_paid_amount),
                str(total_balance_due),
                str(total_sales_sum),
                str(total_sales_with_tax_sum),
                str(total_tax_amount_sum),
            ])

            export_resp = self.maybe_export(
                "sales_summary_report",
                "Sales Summary Report",
                columns,
                rows,
            )
            if export_resp:
                return export_resp

            return Response(
                {
                    "filters": request.query_params,
                    "count": len(rows),
                    "columns": columns,
                    "results": rows,
                }
            )

        # Backward-compatible default: day-wise aggregate report
        qs = qs.annotate(day=TruncDate("invoice_date")).values("day").annotate(
            invoice_count=Count("id"),
            total_sales=Coalesce(Sum("taxable_amount"), Value(0), output_field=DecimalField()),
            total_sales_with_tax=Coalesce(Sum("grand_total"), Value(0), output_field=DecimalField()),
            total_tax_amount=Coalesce(
                Sum(F("grand_total") - F("taxable_amount")),
                Value(0),
                output_field=DecimalField(),
            ),
        ).order_by("day")

        columns = ["DATE", "INVOICE COUNT", "TOTAL SALES", "TOTAL SALES WITH TAX", "TOTAL TAX AMOUNT"]

        total_count = 0
        sum_sales = Decimal("0")
        sum_with_tax = Decimal("0")
        sum_tax = Decimal("0")

        rows = []
        for r in qs:
            total_count += r["invoice_count"]
            sum_sales += r["total_sales"]
            sum_with_tax += r["total_sales_with_tax"]
            sum_tax += r["total_tax_amount"]

            rows.append([
                str(r["day"]),
                r["invoice_count"],
                str(r["total_sales"]),
                str(r["total_sales_with_tax"]),
                str(r["total_tax_amount"]),
            ])

        rows.append(["Total", total_count, str(sum_sales), str(sum_with_tax), str(sum_tax)])

        export_resp = self.maybe_export("sales_summary_report", "Sales Summary Report", columns, rows)
        if export_resp:
            return export_resp

        return Response({"filters": request.query_params, "count": len(rows), "columns": columns, "results": rows})




# =========================================================
# 5) Profit Share Distribution Report
# Your LocalInvoice does NOT have complaint_id, so we do:
# INVOICE NO | INVOICE DATE | CUSTOMER | TOTAL AMOUNT | SHOP(40%) | GROW(40%) | ADMIN(20%)
# Filters: year/month/week, search
# =========================================================
class ProfitShareReportAPIView(ReportBaseAPIView):
    SHOP_SHARE = Decimal("0.40")
    GROW_SHARE = Decimal("0.40")
    ADMIN_SHARE = Decimal("0.20")

    def get(self, request):
        qs = LocalInvoice.objects.select_related(
            "customer", "assigned_shop", "assigned_growtag"
        ).filter(
            status="SENT",
            payment_status__in=["PAID", "PARTIALLY_PAID"]
        )

        # Role-based access
        if request.user and request.user.is_authenticated and request.user.is_staff:
            pass
        elif getattr(request, "shop", None):
            qs = qs.filter(assigned_shop=request.shop)
        elif getattr(request, "growtag", None):
            qs = qs.filter(assigned_growtag=request.growtag)
        else:
            return Response(
                {"detail": "You do not have permission to view this report."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Date filter
        qs = self.apply_date_filters_date(qs, "invoice_date")

        # Search filter
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(invoice_number__icontains=search)
                | Q(customer__customer_name__icontains=search)
                | Q(assigned_shop__shopname__icontains=search)
                | Q(assigned_growtag__name__icontains=search)
            )

        qs = qs.order_by("-invoice_date")[:5000]

        columns = [
            "INVOICE NO",
            "INVOICE DATE",
            "CUSTOMER",
            "TOTAL AMOUNT",
            "SHOP (40%)",
            "GROW TAGS (40%)",
            "ADMIN (20%)",
        ]

        if not qs.exists():
            return Response({
                "filters": request.query_params,
                "count": 0,
                "columns": columns,
                "results": [],
                "message": "No matching paid invoices found."
            })

        rows = []
        total_amount = Decimal("0.00")
        total_shop = Decimal("0.00")
        total_grow = Decimal("0.00")
        total_admin = Decimal("0.00")

        for inv in qs:
            amount = inv.grand_total or Decimal("0.00")
            shop_amt = amount * self.SHOP_SHARE
            grow_amt = amount * self.GROW_SHARE
            admin_amt = amount * self.ADMIN_SHARE

            total_amount += amount
            total_shop += shop_amt
            total_grow += grow_amt
            total_admin += admin_amt

            customer_name = (
                getattr(inv.customer, "customer_name", None)
                or getattr(inv.customer, "name", None)
                or ""
            )

            rows.append([
                inv.invoice_number or f"INV-{inv.id}",
                str(inv.invoice_date) if inv.invoice_date else "",
                customer_name,
                str(amount),
                str(shop_amt),
                str(grow_amt),
                str(admin_amt),
            ])

        rows.append([
            "Total",
            "",
            "",
            str(total_amount),
            str(total_shop),
            str(total_grow),
            str(total_admin),
        ])

        export_resp = self.maybe_export(
            "profit_share_report",
            "Profit Share Distribution Report",
            columns,
            rows
        )
        if export_resp:
            return export_resp

        return Response({
            "filters": request.query_params,
            "count": len(rows) - 1,
            "columns": columns,
            "results": rows
        })

# =========================================================
# 6) Expense Report
# EXPENSE ID | DATE | TITLE | CATEGORY | AMOUNT | PAYMENT METHOD | RECEIPT
# Filters: year/month/week, category, search
# =========================================================
class ExpenseReportAPIView(ReportBaseAPIView):
    def get(self, request):
        qs = Expense.objects.select_related("category").all()
        # ✅ OWNER FILTER
        if request.user and request.user.is_authenticated and request.user.is_staff:
           pass
        elif getattr(request, "shop", None):
           qs = qs.filter(owner_type="shop", owner_shop=request.shop)
        elif getattr(request, "growtag", None):
           qs = qs.filter(owner_type="growtag", owner_growtag=request.growtag)
        else:
           qs = qs.none()


        # Expense.date is DateField
        qs = self.apply_date_filters_date(qs, "date")

        category = request.query_params.get("category")
        if category and category.lower() != "all":
            if category.isdigit():
                qs = qs.filter(category_id=int(category))
            else:
                qs = qs.filter(category__name__iexact=category)

        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(title__icontains=search)
                | Q(merchant__icontains=search)
                | Q(category__name__icontains=search)
                | Q(payment_method__icontains=search)
                | Q(status__icontains=search)
            )

        qs = qs.order_by("-date")[:5000]

        columns = ["EXPENSE ID", "DATE", "TITLE", "CATEGORY", "AMOUNT", "PAYMENT METHOD", "RECEIPT"]
        rows = []
        for e in qs:
            rows.append([
                e.id,
                str(e.date),
                e.title,
                e.category.name if e.category else "-",
                str(e.amount),
                e.payment_method,
                "Available" if e.receipt else "-",
            ])

        export_resp = self.maybe_export("expense_report", "Expense Report", columns, rows)
        if export_resp:
            return export_resp

        return Response({"filters": request.query_params, "count": len(rows), "columns": columns, "results": rows})
