from rest_framework import viewsets, status,permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import IntegrityError
from django.conf import settings
from .models import Shop, Growtags, Complaint,GrowTagAssignment,Customer,Lead,InventoryStock, StockLedger
from .serializers import ShopSerializer, GrowtagsSerializer, ComplaintSerializer,GrowTagAssignmentSerializer,CustomerSerializer,LeadSerializer
from .serializers import  (ShopViewSerializer, GrowtagViewSerializer,InventoryStockSerializer, 
                           StockLedgerSerializer,GrowtagPopupSerializer,ShopPopupSerializer,InventoryStockAdjustSerializer)
from .services import _ensure_complaint_coords,sync_complaint_to_customer
from .services import (
    geocode_address_pincode,
    nearest_lists_for_address,
    get_nearest_shop,
    get_nearest_growtag,
)
from zoho_integration.customer_sync import sync_core_customer_to_zoho_contact
from zoho_integration.zoho_books import ZohoBooksError
from django.db.models import Q,Count
from rest_framework.permissions import IsAuthenticated,IsAdminUser
from rest_framework.views import APIView
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail
from django.contrib.auth import get_user_model
from rest_framework.parsers import MultiPartParser, FormParser,JSONParser

from core.permissions import IsCustomer,IsShop, BasePermission
from core.authentication import UnifiedTokenAuthentication
from core.serializers import CustomerRegisterSerializer, CustomerLoginSerializer, PublicComplaintSerializer
from core.models import CustomerAuthToken
from core.mixins import BulkDeleteMixin
from .models import Vendor
from .serializers import VendorSerializer
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.filters import SearchFilter,OrderingFilter
from .models import PurchaseOrder,PurchaseBill, PurchaseOrderItem
from .serializers import PurchaseOrderSerializer,PurchaseOrderListSerializer,PurchaseBillListSerializer, PurchaseBillCreateUpdateSerializer,PurchaseOrderItemSerializer
from django.contrib.auth.hashers import check_password
from django.db.models import F
from django.db import transaction
from zoho_integration.models import LocalInvoice
from zoho_integration.models import LocalCustomer
from zoho_integration.serializers import LocalInvoiceReadSerializer
from core.permissions import IsFranchiseShop,IsOtherShop,IsGrowtag,CrudByRole,IsAdminOrCustomerSelf,IsAnyStaffOrShopOrGrowtagOrCustomer
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from core.models import Customer
from django.contrib.auth.hashers import check_password,make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from decimal import Decimal
from core.serializers import PurchaseBillPaymentSerializer, PurchaseBillCreateUpdateSerializer
from core.models import PurchaseBill, PurchaseBillPayment, PurchaseBillItem
from django.db.models import Prefetch
import logging
import os
from pathlib import Path
from decimal import Decimal
from django.http import HttpResponse
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.exceptions import PermissionDenied
from rest_framework.authentication import SessionAuthentication
from rest_framework_simplejwt.authentication import JWTAuthentication
from datetime import timedelta
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
    Image,
)
import traceback
from .models import PurchaseOrder
from .authentication import UnifiedTokenAuthentication
from .permissions import CrudByRole
from .utils import (
    po_register_unicode_font,
    po_money,
    purchase_order_amount_to_words,
    pb_register_unicode_font,pb_money,pb_text,
)
from .tasks import send_shop_created_email_task, geocode_shop_task
from io import BytesIO
import requests
from .models import PasswordResetOTP
from core.audit import get_actor
from django.utils import timezone
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
from django.db.models.deletion import ProtectedError
from rest_framework.exceptions import ValidationError 
logger = logging.getLogger(__name__)


User = get_user_model()

class CreatedByMixin:
    def _set_creator_fields(self, serializer):
        request = self.request

        audit_data = {
            "created_on": timezone.now().date(),
        }

        if request.user and request.user.is_authenticated and request.user.is_staff:
            audit_data["created_by_user"] = request.user

        elif getattr(request, "shop", None):
            audit_data["created_by_shop"] = request.shop

        elif getattr(request, "growtag", None):
            audit_data["created_by_growtag"] = request.growtag

        elif getattr(request, "customer", None):
            audit_data["created_by_customer"] = request.customer

        return serializer.save(**audit_data)
    def perform_create(self, serializer):
        return self._set_creator_fields(serializer)

import requests
import logging

logger = logging.getLogger(__name__)


class ShopViewSet(BulkDeleteMixin, CreatedByMixin, viewsets.ModelViewSet):
    authentication_classes = [
        JWTAuthentication,
        UnifiedTokenAuthentication,
        SessionAuthentication,
    ]
    permission_classes = [CrudByRole]
    queryset = Shop.objects.all().order_by("-id")
    serializer_class = ShopSerializer

    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE", "PUT"},
        "franchise": {"GET", "PATCH", "PUT"},
        "othershop": {"GET", "PATCH", "PUT"},
        "growtag": set(),
        "customer": {"GET"}, 
    }

    def get_queryset(self):
        qs = super().get_queryset()

        # Admin sees all
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # Logged-in shop sees only its own record
        if getattr(self.request, "shop", None):
            return qs.filter(id=self.request.shop.id)

        return qs.none()

    def destroy(self, request, *args, **kwargs):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            raise PermissionDenied("Only admin can delete shops.")

        instance = self.get_object()

        try:
           self.perform_destroy(instance)
           return Response(
            {"message": "Shop deleted successfully."},
            status=status.HTTP_204_NO_CONTENT
            )

        except ProtectedError as e:
            protected_models = set()

            for obj in e.protected_objects:
                protected_models.add(obj.__class__.__name__)

            return Response(
            {
                "success": False,
                "message": f"Cannot delete this shop. It is linked to: {', '.join(protected_models)}"
            },
            status=status.HTTP_400_BAD_REQUEST
            )
    @action(
        detail=False,
        methods=["get", "patch"],
        url_path="my",
        authentication_classes=[UnifiedTokenAuthentication],
        permission_classes=[IsShop],
    )
    def my(self, request):
        if request.method == "GET":
            return Response(ShopSerializer(request.shop).data)

        serializer = ShopSerializer(request.shop, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="view")
    def view_popup(self, request, pk=None):
        shop = self.get_object()
        data = ShopViewSerializer(shop).data
        return Response(data)

    def create(self, request, *args, **kwargs):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            raise PermissionDenied("Only admin can create shops.")

        data = request.data.copy()

        area = (data.get("area") or "").strip()
        state = (data.get("state") or "").strip()
        pincode = (data.get("pincode") or "").strip()

        # Convert empty strings to None for nullable unique fields
        for field in ["email", "phone", "gst_pin"]:
            if data.get(field) in ("", None):
                data[field] = None

        # Optional geocoding - never block shop creation if this fails
        try:
            query = ""

            if pincode:
                query = f"{pincode}, India"
            elif area and state:
                query = f"{area}, {state}, India"
            elif area:
                query = f"{area}, India"
            elif state:
                query = f"{state}, India"

            logger.info("SHOP GEOCODE QUERY: %s", query)

            if query:
                response = requests.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": query,
                        "format": "json",
                        "limit": 1,
                    },
                    headers={
                        "User-Agent": "FixlyApp/1.0"
                    },
                    timeout=5,
                )

                if response.status_code == 200:
                    geo_data = response.json()
                    logger.info("SHOP GEOCODE RESPONSE: %s", geo_data)

                    if geo_data:
                        data["latitude"] = float(geo_data[0]["lat"])
                        data["longitude"] = float(geo_data[0]["lon"])
                else:
                    logger.warning(
                        "SHOP GEOCODE SKIPPED: status=%s response=%s",
                        response.status_code,
                        response.text,
                    )

        except Exception as geocode_error:
            logger.exception("SHOP GEOCODE ERROR: %s", geocode_error)
            # continue without blocking creation

        try:
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            shop = self.perform_create(serializer)

            return Response(
                {
                    "status": "success",
                    "message": "Shop created successfully",
                    "data": self.get_serializer(shop).data,
                },
                status=status.HTTP_201_CREATED,
            )
        except ValidationError as e:
            errors = e.detail

            if "email" in errors:
                return Response(
                  {
                    "status": "error",
                    "message": "email already exists",
                     "error": {
                        "email": ["This email is already registered to another shop."]
                      },
                  },
                  status=status.HTTP_400_BAD_REQUEST,
                )

            if "phone" in errors:
                return Response(
                   {
                    "status": "error",
                    "message": "phone already exists",
                    "error": {
                        "phone": ["This phone number is already registered to another shop."]
                    },
                   },
                   status=status.HTTP_400_BAD_REQUEST,
                )

            if "gst_pin" in errors:
                return Response(
                   {
                     "status": "error",
                     "message": "gst pin already exists",
                    "error": {
                        "gst_pin": ["This GST number is already registered to another shop."]
                    },
                   },
                   status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                  "status": "error",
                  "message": "validation failed",
                   "error": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IntegrityError as e:
            error_message = str(e).lower()

            if "email" in error_message:
                return Response(
                    {
                        "status": "error",
                        "message": "email already exists",
                        "error": {"email": ["this email already exists"]},
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "phone" in error_message:
                return Response(
                    {
                        "status": "error",
                        "message": "phone already exists",
                        "error": {"phone": ["this phone already exists"]},
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "gst_pin" in error_message:
                return Response(
                    {
                        "status": "error",
                        "message": "gst pin already exists",
                        "error": {"gst_pin": ["this gst pin already exists"]},
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status": "error",
                    "message": "database error",
                    "error": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            logger.exception("SHOP CREATE ERROR: %s", e)
            return Response(
                {
                    "status": "error",
                    "message": "failed to create shop",
                    "error": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    def perform_create(self, serializer):
        raw_password = self.request.data.get("password")

        # Save shop with creator fields
        shop = self._set_creator_fields(serializer)

        admin_emails = (
            User.objects.filter(is_superuser=True)
            .exclude(email__isnull=True)
            .exclude(email="")
            .values_list("email", flat=True)
        )

        recipients = list(admin_emails)

        if shop.email:
            recipients = [shop.email] + recipients

        # Remove duplicates
        recipients = list(dict.fromkeys(recipients))

        def send_direct_email():
            if not recipients:
                return

            try:
                send_mail(
                    subject="New Shop Created",
                    message=(
                        "A new Shop has been created.\n\n"
                        f"Shop ID: {getattr(shop, 'shop_id', shop.id)}\n"
                        f"Shop Name: {shop.shopname}\n"
                        f"Email: {shop.email or '-'}\n"
                        f"Login Password: {raw_password or '-'}\n\n"
                        f"Phone: {shop.phone or '-'}\n"
                        f"GST PIN: {shop.gst_pin or '-'}\n"
                        f"Area: {shop.area or '-'}\n"
                        f"State: {shop.state or '-'}\n"
                        f"Pincode: {shop.pincode or '-'}\n"
                        f"Shop Type: {shop.shop_type or '-'}\n"
                        f"Status: {shop.status}\n\n"
                        "Please change your password after first login."
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=recipients,
                    fail_silently=True,
                )
            except Exception as e:
                logger.exception("SHOP DIRECT EMAIL FAILED: %s", e)

        def after_commit():
            try:
                send_shop_created_email_task.delay(shop.id, raw_password)
                logger.info("SHOP EMAIL TASK QUEUED: shop_id=%s", shop.id)
            except Exception as celery_error:
                logger.exception("SHOP CELERY FAILED: %s", celery_error)
                send_direct_email()

        transaction.on_commit(after_commit)
        return shop

    @action(detail=False, methods=["get"], url_path="franchise")
    def franchise_shops(self, request):
        qs = Shop.objects.filter(shop_type="franchise", status=True).order_by("shopname")
        return Response(ShopSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="othershop")
    def other_shops(self, request):
        qs = Shop.objects.filter(shop_type="othershop", status=True).order_by("shopname")
        return Response(ShopSerializer(qs, many=True).data)
class GrowtagsViewSet(BulkDeleteMixin,CreatedByMixin, viewsets.ModelViewSet):
    authentication_classes = [
        SessionAuthentication,
        JWTAuthentication,# optional
        UnifiedTokenAuthentication
    ]
    permission_classes = [CrudByRole]
    queryset = Growtags.objects.all()
    serializer_class = GrowtagsSerializer
    parser_classes = (MultiPartParser, FormParser,JSONParser)
    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE","PUT"},
        "growtag": {"GET", "PATCH","PUT"},      # own only
        "franchise": {"GET"},
        "othershop": {"GET"},
        "customer": {"GET"}, 
    }
    def get_queryset(self):
        qs = super().get_queryset()

        # admin sees all
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # growtag sees own record
        if getattr(self.request, "growtag", None):
            return qs.filter(id=self.request.growtag.id)

        # shop sees assigned growtags only
        if getattr(self.request, "shop", None):
            return qs.filter(assignment__shop=self.request.shop)

        return qs.none()
    @action(detail=False, methods=["get"], url_path="franchise", permission_classes=[IsAdminUser])
    def franchise_shops(self, request): ...


    @action(detail=False, methods=["get","patch"], url_path="my",
        authentication_classes=[UnifiedTokenAuthentication],
        permission_classes=[IsGrowtag])
    def my(self, request):
        if request.method == "GET":
           return Response(GrowtagsSerializer(request.growtag).data)
        try:
           serializer = GrowtagsSerializer(request.growtag, data=request.data, partial=True)
           serializer.is_valid(raise_exception=True)
           serializer.save()
           return Response(serializer.data)
        except ValidationError as e:
            errors = e.detail

            if "email" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "email already exists",
                        "error": {
                            "email": ["This email is already registered to another growtag."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "phone" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "phone already exists",
                        "error": {
                            "phone": ["This phone number is already registered to another growtag."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "grow_id" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "grow id already exists",
                        "error": {
                            "grow_id": ["This GrowTag ID is already in use."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "adhar" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "adhar already exists",
                        "error": {
                            "adhar": ["This Aadhaar number is already registered to another growtag."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status": "error",
                    "message": "validation failed",
                    "error": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": "something went wrong",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["get"], url_path="view")
    def view_popup(self, request, pk=None):
        growtag = self.get_object()
        data = GrowtagViewSerializer(growtag).data
        return Response(data)

    def create(self, request, *args, **kwargs):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
           raise PermissionDenied("Only admin can create growtags.")
        data = request.data.copy()
        area = data.get("area", "")
        pincode = data.get("pincode", "")
        try:
            lat_lon = geocode_address_pincode(area, pincode)
            if lat_lon:
              lat, lon,precision = lat_lon
              data["latitude"] = lat
              data["longitude"] = lon
        except Exception as e:
            print("Geocode error:", e)
        try:
           serializer = self.get_serializer(data=data)
           serializer.is_valid(raise_exception=True)
           self.perform_create(serializer)
           return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValidationError as e:
            errors = e.detail

            if "email" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "email already exists",
                        "error": {
                            "email": ["This email is already registered to another growtag."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "phone" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "phone already exists",
                        "error": {
                            "phone": ["This phone number is already registered to another growtag."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "grow_id" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "grow id already exists",
                        "error": {
                            "grow_id": ["This GrowTag ID is already in use."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "adhar" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "adhar already exists",
                        "error": {
                            "adhar": ["This Aadhaar number is already registered to another growtag."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status": "error",
                    "message": "validation failed",
                    "error": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except IntegrityError as e:
            return Response(
                {
                    "status": "error",
                    "message": "database integrity error",
                    "error": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": "something went wrong",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    def perform_create(self, serializer):
        raw_password = self.request.data.get("password")
        growtag = self._set_creator_fields(serializer)

        admin_emails = (
            User.objects.filter(is_superuser=True)
            .exclude(email__isnull=True)
           .exclude(email="")
           .values_list("email", flat=True)
        )

        recipients = list(admin_emails)

        if growtag.email:
            recipients = [growtag.email] + recipients

        recipients = list(dict.fromkeys(recipients))

        if recipients:
            try:
                send_mail(
                        subject="New Growtag Created",
                        message=(
                    "A new Growtag has been created.\n\n"
                    f"Grow ID: {growtag.grow_id}\n"
                    f"Name: {growtag.name}\n"
                    f"Email: {growtag.email}\n"
                    f"Login Password: {raw_password}\n\n"
                    f"Phone: {growtag.phone or '-'}\n"
                    f"Adhar: {growtag.adhar or '-'}\n"
                    f"Area: {growtag.area or '-'}\n"
                    f"Pincode: {growtag.pincode}\n"
                    f"Status: {growtag.status}\n"
                    "Please change your password after first login."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=recipients,
                fail_silently=True,
                )
            except Exception as e:
               print("Growtag email failed:", e)

        return growtag
    # Active GrowTags dropdown
    # GET /api/growtags/active/
    @action(detail=False, methods=["get"], url_path="active")
    def active_growtags(self, request):
        qs = Growtags.objects.filter(status="Active").order_by("grow_id")
        return Response(self.get_serializer(qs, many=True).data)


    @action(detail=True, methods=["post"])
    def set_status(self, request, pk=None):
        """
        Simple endpoint to change tech status:
        POST /api/growtags/<id>/set_status/
        { "status": "Active" }  or  { "status": "Inactive" }
        """
        tech = self.get_object()
        new_status = request.data.get("status")

        # 💡 adjust choices to match your model's STATUS choices
        allowed = ["Active", "Inactive"]

        if new_status not in allowed:
            return Response(
                {"detail": f"Invalid status. Allowed: {allowed}"},
                status=drf_status.HTTP_400_BAD_REQUEST,
            )

        tech.status = new_status
        tech.save(update_fields=["status"])

        return Response(
            {
                "id": tech.id,
                "status": tech.status,
            }
        )
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
            return Response(
                {"message": "Growtag deleted successfully."},
                status=status.HTTP_204_NO_CONTENT
            )
        except ProtectedError as e:
            # Extract model names
            protected_models = set()

            for obj in e.protected_objects:
                protected_models.add(obj.__class__.__name__)

            return Response(
                {
                "success": False,
                "message": f"Cannot delete this growtag. It is used in: {', '.join(protected_models)}"
                },
                status=status.HTTP_400_BAD_REQUEST
            )
class CustomerViewSet(BulkDeleteMixin, CreatedByMixin, viewsets.ModelViewSet):
    authentication_classes = [
        UnifiedTokenAuthentication,
        JWTAuthentication,
        SessionAuthentication,
    ]
    permission_classes = [CrudByRole]
    queryset = Customer.objects.all().prefetch_related("complaints")
    serializer_class = CustomerSerializer

    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE", "PUT"},
        "franchise": {"GET"},
        "othershop": {"GET"},
        "growtag": {"GET"},
        "customer": {"GET", "PATCH", "PUT"},
    }

    def get_queryset(self):
        qs = super().get_queryset()

        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        if getattr(self.request, "customer", None):
            return qs.filter(id=self.request.customer.id)

        if getattr(self.request, "shop", None):
            return qs.filter(complaints__assigned_shop=self.request.shop).distinct()

        if getattr(self.request, "growtag", None):
            return qs.filter(complaints__assigned_Growtags=self.request.growtag).distinct()

        return qs.none()
    def create(self, request, *args, **kwargs):
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
            raise PermissionDenied("Only admin can create customers here (use public register API)")

        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            customer = self.perform_create(serializer)

            return Response(
                {
                    "status": "success",
                    "message": "Customer created successfully",
                    "data": self.get_serializer(customer).data,
                },
                status=status.HTTP_201_CREATED,
            )

        except ValidationError as e:
            errors = e.detail

            if "email" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "email already exists",
                        "error": {
                            "email": ["This email is already registered to another customer."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "customer_phone" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "phone already exists",
                        "error": {
                            "customer_phone": ["This phone number is already registered to another customer."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "phone" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "phone already exists",
                        "error": {
                            "phone": ["This phone number is already registered to another customer."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status": "error",
                    "message": "validation failed",
                    "error": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except IntegrityError as e:
            return Response(
                {
                    "status": "error",
                    "message": "database integrity error",
                    "error": str(e),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": "something went wrong",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def perform_create(self, serializer):
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return self._set_creator_fields(serializer)
        raise PermissionDenied("Only admin can create customers here (use public register API)")
        

    @action(
        detail=False,
        methods=["get"],
        url_path="my",
        authentication_classes=[UnifiedTokenAuthentication],
        permission_classes=[IsCustomer],
    )
    def my(self, request):
        if request.method == "GET":
           return Response(CustomerSerializer(request.customer).data)
        try:
            serializer = CustomerSerializer(
                request.customer,
                data=request.data,
                partial=True
            )
            serializer.is_valid(raise_exception=True)
            serializer.save()

            return Response(
                {
                    "status": "success",
                    "message": "Customer updated successfully",
                    "data": serializer.data,
                },
                status=status.HTTP_200_OK,
            )

        except ValidationError as e:
            errors = e.detail

            if "email" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "email already exists",
                        "error": {
                            "email": ["This email is already registered to another customer."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "customer_phone" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "phone already exists",
                        "error": {
                            "customer_phone": ["This phone number is already registered to another customer."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if "phone" in errors:
                return Response(
                    {
                        "status": "error",
                        "message": "phone already exists",
                        "error": {
                            "phone": ["This phone number is already registered to another customer."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {
                    "status": "error",
                    "message": "validation failed",
                    "error": errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            return Response(
                {
                    "status": "error",
                    "message": "something went wrong",
                    "error": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    def destroy(self, request, *args, **kwargs):
        # 🔐 Only admin can delete
        if not (request.user and request.user.is_authenticated and request.user.is_staff):
           raise PermissionDenied("Only admin can delete customers.")

        instance = self.get_object()

        try:
           self.perform_destroy(instance)
           return Response(
            {
                "success": True,
                "message": "Customer deleted successfully."
            },
            status=status.HTTP_200_OK
           )

        except ProtectedError as e:
            protected_models = {obj.__class__.__name__ for obj in e.protected_objects}

            return Response(
            {
                "success": False,
                "message": "Cannot delete this customer because it is linked to another module.",
                "used_in": list(protected_models)
            },
            status=status.HTTP_400_BAD_REQUEST
            )


class ComplaintViewSet(BulkDeleteMixin,viewsets.ModelViewSet):
    authentication_classes = [
        SessionAuthentication,
        UnifiedTokenAuthentication,
        JWTAuthentication,
    ]
    permission_classes = [CrudByRole]
    queryset = Complaint.objects.all().order_by("-created_at")
    serializer_class = ComplaintSerializer

    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE", "PUT"},
        "franchise": {"GET", "PATCH", "PUT"},
        "othershop": {"GET", "PATCH", "PUT"},
        "growtag": {"GET", "PATCH", "PUT"},
        "customer": {"GET", "POST"},
    }

    def get_queryset(self):
        qs = super().get_queryset()

        # admin sees all
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # shop sees their assigned complaints
        if getattr(self.request, "shop", None):
            return qs.filter(assigned_shop=self.request.shop)

        # growtag sees their assigned complaints
        if getattr(self.request, "growtag", None):
            return qs.filter(assigned_Growtags=self.request.growtag)

        # customer sees only their complaints
        if getattr(self.request, "customer", None):
            return qs.filter(customer=self.request.customer)

        return qs.none()

    # ----------------- CREATE -----------------
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        customer_name = data.get("customer_name")
        customer_phone = data.get("customer_phone")
        email = data.get("email")
        password = data.get("password")
        raw_password = password
        phone_model = data.get("phone_model")
        issue_details = data.get("issue_details")
        address = data.get("address")
        state = data.get("state")
        pincode = data.get("pincode")
        area = data.get("area", "")
        assign_to = data.get("assign_to")
        status_value = data.get("status", "Pending")

        # ✅ Manual selection from request
        assigned_shop = data.get("assigned_shop")
        assigned_gt = data.get("assigned_Growtags")

        # 1️⃣ Find existing customer by phone OR email
        lookup = Q()
        if customer_phone:
            lookup |= Q(customer_phone=customer_phone)
        if email:
            lookup |= Q(email=email)

        customer = None
        role, actor = get_actor(request)
        customer_audit_data = {}
        if role == "admin":
            customer_audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            customer_audit_data["created_by_shop"] = actor
        elif role == "growtag":
            customer_audit_data["created_by_growtag"] = actor
        elif role == "customer":
            customer_audit_data["created_by_customer"] = actor
        if lookup:
            customer = Customer.objects.filter(lookup).first()

        # 2️⃣ Existing customer conflict check
        if customer:
            conflict_messages = {}

            if customer_name and customer.customer_name and customer.customer_name != customer_name:
                conflict_messages["customer_name"] = "Customer name does not match the existing account."

            if password and customer.password and not check_password(password, customer.password):
                conflict_messages["password"] = "Password does not match the existing account."

            if conflict_messages:
                return Response(conflict_messages, status=status.HTTP_400_BAD_REQUEST)

        else:
            # 3️⃣ Create new customer
            customer = Customer.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                email=email,
                password=make_password(password) if password else "",
                address=address,
                state=state,
                pincode=pincode,
                area=area,
                **customer_audit_data,
            )

        # ✅ Zoho sync (best-effort)
        try:
            local_customer = sync_core_customer_to_zoho_contact(customer)
            print("Zoho contact synced:", local_customer.zoho_contact_id)
        except Exception as e:
            print("Zoho customer sync failed:", str(e))
        role, actor = get_actor(request)

        audit_data = {
         "created_on": timezone.now().date(),
        }

        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
    
        # 4️⃣ Create complaint with manual assignment
        complaint = Complaint.objects.create(
            customer=customer,
            customer_name=customer.customer_name,
            customer_phone=customer.customer_phone,
            email=customer.email,
            password=customer.password,
            phone_model=phone_model,
            issue_details=issue_details,
            address=address,
            state=state,
            pincode=pincode,
            area=area,
            assign_to=assign_to,
            assigned_shop=assigned_shop if assign_to in ["franchise", "othershop"] else None,
            assigned_Growtags=assigned_gt if assign_to == "growtag" else None,
            status="Assigned" if (assigned_shop or assigned_gt) else status_value,
            **audit_data,
        )
        
        # ✅ Ensure coords
        _ensure_complaint_coords(complaint)

        # 🔁 Sync complaint → customer
        sync_complaint_to_customer(complaint)

        # ✅ Send email
        if complaint.email:
            subject = f"Complaint Registered Successfully (ID: {complaint.id})"
            message = (
                f"Dear {complaint.customer_name},\n\n"
                f"Your complaint has been registered successfully.\n\n"
                f"Customer Details:\n"
                f"Customer ID: {customer.id}\n"
                f"Complaint ID: {complaint.id}\n"
                f"Customer Name: {complaint.customer_name}\n"
                f"Mobile No: {complaint.customer_phone}\n"
                f"Email: {complaint.email}\n"
                f"Password: {raw_password or ''}\n"
                f"Phone Model: {complaint.phone_model}\n"
                f"Address: {complaint.address}\n"
                f"State: {complaint.state}\n"
                f"Pincode: {complaint.pincode}\n"
                f"Issue: {complaint.issue_details}\n"
                f"Assign To: {complaint.assign_to}\n"
                f"Assigned To: {complaint.assigned_shop_name}\n"
                f"Status: {complaint.status}\n\n"
                f"Thank you for contacting us.\n"
                f"Support Team"
            )

            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[complaint.email],
                    fail_silently=False,
                )
            except Exception as e:
                print("Email Error:", e)

        out = ComplaintSerializer(complaint)
        return Response(out.data, status=status.HTTP_201_CREATED)

    # ----------------- UPDATE / PATCH -----------------
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        complaint = self.get_object()

        serializer = self.get_serializer(complaint, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        status_in_request = "status" in data

        if not partial:
            required = [
                "customer_name",
                "customer_phone",
                "phone_model",
                "issue_details",
                "address",
                "state",
                "pincode",
                "assign_to",
                "area",
            ]
            missing = [f for f in required if f not in data]
            if missing:
                return Response(
                    {"detail": f"PUT requires fields: {', '.join(missing)}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ====== CUSTOMER LOGIC ======
        customer_name = data.get("customer_name", complaint.customer_name)
        customer_phone = data.get("customer_phone", complaint.customer_phone)
        email = data.get("email", complaint.email)
        password = data.get("password", complaint.password)
        address = data.get("address", complaint.address)
        state = data.get("state", complaint.state)
        pincode = data.get("pincode", complaint.pincode)
        area = data.get("area", complaint.area)

        customer = complaint.customer
        role, actor = get_actor(request)
        customer_audit_data = {}
        if role == "admin":
            customer_audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            customer_audit_data["created_by_shop"] = actor
        elif role == "growtag":
            customer_audit_data["created_by_growtag"] = actor
        elif role == "customer":
            customer_audit_data["created_by_customer"] = actor

        lookup = Q()
        if customer_phone:
            lookup |= Q(customer_phone=customer_phone)
        if email:
            lookup |= Q(email=email)

        existing_customer = Customer.objects.filter(lookup).first() if lookup else None

        if existing_customer:
            conflict_messages = {}

            if customer and existing_customer.id != customer.id:
                if customer_name and existing_customer.customer_name != customer_name:
                    conflict_messages["customer_name"] = "Customer name does not match the existing account."
                if password and not check_password(password, existing_customer.password):
                    conflict_messages["password"] = "Password does not match the existing account."
                if conflict_messages:
                    return Response(conflict_messages, status=status.HTTP_400_BAD_REQUEST)

                customer = existing_customer

            if customer is None:
                customer = existing_customer

        if customer is None:
            customer = Customer.objects.create(
                customer_name=customer_name,
                customer_phone=customer_phone,
                email=email,
                password=make_password(password) if password else "",
                address=address,
                state=state,
                pincode=pincode,
                area=area,
                **customer_audit_data,
            )
        else:
            if not partial:
                customer.customer_name = customer_name
                customer.customer_phone = customer_phone
                customer.email = email
                customer.password = make_password(password) if password else ""
                customer.address = address
                customer.state = state
                customer.pincode = pincode
                customer.area = area
            else:
                if "customer_name" in data:
                    customer.customer_name = customer_name
                if "customer_phone" in data:
                    customer.customer_phone = customer_phone
                if "email" in data:
                    customer.email = email
                if "password" in data:
                    customer.password = make_password(password) if password else ""
                if "address" in data:
                    customer.address = address
                if "state" in data:
                    customer.state = state
                if "pincode" in data:
                    customer.pincode = pincode
                if "area" in data:
                    customer.area = area

            customer.save()

        # ✅ Zoho sync (best-effort)
        try:
            local_customer = sync_core_customer_to_zoho_contact(customer)
            print("Zoho contact synced:", local_customer.zoho_contact_id)
        except Exception as e:
            print("Zoho customer sync failed:", str(e))

        # ====== SAVE COMPLAINT ======
        complaint = serializer.save(customer=customer)

        complaint.customer_name = customer.customer_name
        complaint.customer_phone = customer.customer_phone
        complaint.email = customer.email
        complaint.password = customer.password
        complaint.address = customer.address
        complaint.state = customer.state
        complaint.pincode = customer.pincode
        complaint.area = customer.area

        assign_to = data.get("assign_to", complaint.assign_to)
        assigned_shop = data.get("assigned_shop", complaint.assigned_shop)
        assigned_gt = data.get("assigned_Growtags", complaint.assigned_Growtags)

        complaint.assign_to = assign_to

        if assign_to == "growtag":
            complaint.assigned_shop = None
            complaint.assigned_Growtags = assigned_gt

        elif assign_to in ["franchise", "othershop"]:
            complaint.assigned_Growtags = None
            complaint.assigned_shop = assigned_shop

        if not status_in_request:
            if complaint.assigned_shop or complaint.assigned_Growtags:
                complaint.status = "Assigned"
            else:
                complaint.status = "Pending"

        complaint.save()

        # ✅ Ensure coords
        _ensure_complaint_coords(complaint)

        # 🔁 Sync complaint → customer
        sync_complaint_to_customer(complaint)

        return Response(self.get_serializer(complaint).data)

    def partial_update(self, request, *args, **kwargs):
        kwargs["partial"] = True
        return self.update(request, *args, **kwargs)

    # ----------------- NEAREST OPTIONS -----------------
    @action(detail=False, methods=["get"], url_path="nearest-options")
    def nearest_options(self, request):
        """
        GET /api/complaints/nearest-options/?area=...&pincode=...&assign_to=franchise|othershop|growtag
        """
        area = request.query_params.get("area", "")
        pincode = str(request.query_params.get("pincode", "")).strip()
        assign_to = request.query_params.get("assign_to", "").lower()
        lat = request.query_params.get("lat")
        lon = request.query_params.get("lon")

        if not area or not pincode:
            return Response(
                {"error": "area and pincode required"},
                status=400
            )

        lists = nearest_lists_for_address(area, pincode, lat=lat, lon=lon)

        return Response({
            "franchise_shops": lists.get("franchise", []),
            "other_shops": lists.get("othershop", []),
            "growtags": lists.get("growtag", []),
        })

    @action(detail=True, methods=["POST"], url_path="create-invoice")
    @transaction.atomic
    def create_invoice(self, request, pk=None):
        complaint = self.get_object()

        if LocalInvoice.objects.filter(complaint=complaint).exists():
            return Response(
                {"detail": "Invoice already created for this complaint"},
                status=status.HTTP_400_BAD_REQUEST
            )

        cust = complaint.customer
        if not cust:
            return Response({"detail": "Complaint has no linked customer."}, status=400)

        local_customer, _ = LocalCustomer.objects.get_or_create(
            phone=cust.customer_phone,
            defaults={
                "name": cust.customer_name,
                "email": cust.email,
                "state": cust.state,
            }
        )

        assigned_shop = None
        assigned_growtag = None

        if complaint.assign_to in ["franchise", "othershop"]:
            assigned_shop = getattr(complaint, "assigned_shop", None)
            if not assigned_shop:
                return Response({"detail": "Complaint is not assigned to a shop."}, status=400)

            assigned_growtag = None

        elif complaint.assign_to == "growtag":
            assigned_growtag = getattr(complaint, "assigned_Growtags", None)
            if not assigned_growtag:
                return Response({"detail": "Complaint is not assigned to a growtag."}, status=400)

            assigned_shop = None

        else:
            return Response({"detail": "Complaint assign_to is missing/invalid."}, status=400)

        try:
            invoice = LocalInvoice.objects.create(
                complaint=complaint,
                customer=local_customer,
                invoice_date=timezone.localdate(),
                status="DRAFT",
                assigned_shop=assigned_shop,
                assigned_growtag=assigned_growtag,
                created_by=request.user
            )
        except ValidationError as e:
            return Response(e.message_dict, status=400)

        return Response(LocalInvoiceReadSerializer(invoice).data, status=status.HTTP_201_CREATED)
class GrowTagAssignmentViewSet(BulkDeleteMixin,CreatedByMixin, viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication, JWTAuthentication]
    permission_classes = [IsAdminUser]
    queryset = GrowTagAssignment.objects.select_related("growtag", "shop").order_by("-assigned_at")
    serializer_class = GrowTagAssignmentSerializer

    # GET list (for the table)
    # GET /api/growtag-assignments/
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    # Assign button
    # POST /api/growtag-assignments/assign/
    @action(detail=False, methods=["post"], url_path="assign")
    def assign(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        growtag_id = request.data.get("growtag") or request.data.get("growtag_id")
        franchise_shop_id = serializer.validated_data.get("franchise_shop_id")
        othershop_shop_id = serializer.validated_data.get("othershop_shop_id")

        # Active GrowTag only
        try:
            growtag = Growtags.objects.get(id=growtag_id, status="Active")
        except Growtags.DoesNotExist:
            return Response({"error": "GrowTag not found or inactive"}, status=404)

        # pick shop based on dropdown selection
        shop_id = franchise_shop_id or othershop_shop_id
        try:
            shop = Shop.objects.get(id=shop_id, status=True)
        except Shop.DoesNotExist:
            return Response({"error": "Shop not found"}, status=404)

        # ensure dropdown matches shop type
        if franchise_shop_id and shop.shop_type != "franchise":
            return Response({"error": "Selected shop is not Franchise"}, status=400)

        if othershop_shop_id and shop.shop_type != "othershop":
            return Response({"error": "Selected shop is not Other Shop"}, status=400)

        # One assignment per GrowTag (update if exists)
        assignment, created = GrowTagAssignment.objects.update_or_create(
            growtag=growtag,
            defaults={"shop": shop}
        )
        self._send_assignment_email(assignment, created)
        return Response(self.get_serializer(assignment).data, status=201)

    # Unassign Selected
    # DELETE /api/growtag-assignments/<id>/unassign/
    @action(detail=True, methods=["delete"], url_path="unassign")
    def unassign(self, request, pk=None):
        assignment = self.get_object()
        assignment.delete()
        return Response(status=204)
       #email
    def _send_assignment_email(self, assignment, created: bool):
       growtag = assignment.growtag
       shop = assignment.shop

       # admin emails
       admin_emails = (
          User.objects.filter(is_superuser=True)
        .exclude(email__isnull=True)
        .exclude(email="")
        .values_list("email", flat=True)
       )

       recipients = list(admin_emails)

       # growtag email
       if getattr(growtag, "email", None):
            recipients = [growtag.email] + recipients

       recipients = list(dict.fromkeys(recipients))  # unique

       if not recipients:
            return

       subject = "Growtag Assigned to Shop" if created else "Growtag Re-Assigned to Shop"

       message = (
        f"{'New' if created else 'Updated'} Growtag Assignment\n\n"
        f"Grow ID: {growtag.grow_id}\n"
        f"Growtag Name: {growtag.name}\n"
        f"Growtag Email: {growtag.email}\n"
        f"Shop: {shop.shopname}\n"
        f"Shop Type: {shop.shop_type}\n"
        f"Shop Phone: {shop.phone or '-'}\n"
        f"Assigned At: {assignment.assigned_at}\n"
        )

       send_mail(
          subject=subject,
          message=message,
          from_email=settings.DEFAULT_FROM_EMAIL,
          recipient_list=recipients,
          fail_silently=True,  # set False while testing
        )

#not confirmed

class ConfirmComplaintAPIView(APIView):
    authentication_classes = [
        UnifiedTokenAuthentication,
        JWTAuthentication,
        SessionAuthentication,
    ]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"PATCH"},
        "franchise": {"PATCH"},
        "othershop": {"PATCH"},
        "growtag": {"PATCH"},
        "customer": set(),
    }

    def patch(self, request, pk):
        complaint = get_object_or_404(Complaint, pk=pk)

        actor_name = None

        if request.user and request.user.is_authenticated and request.user.is_staff:
            actor_name = request.user.username

        elif getattr(request, "shop", None):
            if complaint.assigned_shop_id != request.shop.id:
                return Response({"error": "Not your complaint"}, status=status.HTTP_403_FORBIDDEN)
            actor_name = request.shop.shopname

        elif getattr(request, "growtag", None):
            if complaint.assigned_Growtags_id != request.growtag.id:
                return Response({"error": "Not your complaint"}, status=status.HTTP_403_FORBIDDEN)
            actor_name = getattr(request.growtag, "name", str(request.growtag))

        else:
            return Response({"error": "Not allowed"}, status=status.HTTP_403_FORBIDDEN)

        new_status = request.data.get("confirm_status")
        if new_status not in ["CONFIRMED", "NOT CONFIRMED"]:
            return Response(
                {"error": "confirm_status must be CONFIRMED or NOT CONFIRMED"},
                status=status.HTTP_400_BAD_REQUEST
            )

        if new_status == "CONFIRMED":
            complaint.confirm_status = "CONFIRMED"
            complaint.confirmed_at = timezone.now()

            # only admin user can be stored in confirmed_by if it is FK to User
            if request.user and request.user.is_authenticated and request.user.is_staff:
                complaint.confirmed_by = request.user
            else:
                complaint.confirmed_by = None

            message = "Complaint confirmed successfully"

        else:
            complaint.confirm_status = "NOT CONFIRMED"
            complaint.confirmed_at = None
            complaint.confirmed_by = None
            message = "Complaint unconfirmed successfully"

        complaint.save(update_fields=["confirm_status", "confirmed_by", "confirmed_at"])

        return Response({
            "message": message,
            "confirm_status": complaint.confirm_status,
            "confirmed_at": complaint.confirmed_at,
            "confirmed_by": actor_name if new_status == "CONFIRMED" else None,
        }, status=status.HTTP_200_OK)
#public customer
from django.db import transaction
from .models import Customer
from rest_framework.exceptions import ValidationError
class CustomerRegisterView(APIView):
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        email = request.data.get("email")
        phone = request.data.get("customer_phone")

        # Check existing customer by email or phone
        existing_customer = Customer.objects.filter(
            Q(email__iexact=email) | Q(customer_phone=phone)
        ).first()

        if existing_customer:
            return Response(
                {
                    "exists": True,
                    "message": "Customer already exists. Please login with your credentials."
                },
                status=status.HTTP_409_CONFLICT
            )

        ser = CustomerRegisterSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        customer = ser.save()
         # Dynamic creator-role mapping (same style as other APIs)
        role, actor = get_actor(request)
        update_fields = []

        if role == "admin":
            customer.created_by_user = actor
            update_fields.append("created_by_user")
        elif role in ("franchise", "othershop", "shop"):
            customer.created_by_shop = actor
            update_fields.append("created_by_shop")
        elif role == "growtag":
            customer.created_by_growtag = actor
            update_fields.append("created_by_growtag")
        elif role == "customer":
            customer.created_by_customer = actor
            update_fields.append("created_by_customer")
        else:
            # Public register without actor -> self-created
            customer.created_by_customer = customer
            update_fields.append("created_by_customer")

        if update_fields:
            customer.save(update_fields=update_fields)
        token, _ = CustomerAuthToken.objects.get_or_create(
            customer=customer,
            defaults={"key": CustomerAuthToken.generate_key()}
        )

        return Response(
            {
                "exists": False,
                "message": "Customer registered successfully.",
                "customer": ser.data,
                "token": token.key
            },
            status=status.HTTP_201_CREATED
        )


class CustomerLoginView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        ser = CustomerLoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        email = ser.validated_data["email"]
        password = ser.validated_data["password"]

        customer = Customer.objects.filter(email=email).first()
        if not customer or not check_password(password, customer.password):
            return Response({"detail": "Invalid email or password"}, status=status.HTTP_400_BAD_REQUEST)

        token, _ = CustomerAuthToken.objects.get_or_create(
            customer=customer,
            defaults={"key": CustomerAuthToken.generate_key()}
        )
        return Response({"token": token.key, "customer_id": customer.id, "customer_name": customer.customer_name})
    

    
class PublicComplaintViewSet(BulkDeleteMixin,viewsets.ModelViewSet):
    
    serializer_class = PublicComplaintSerializer
    authentication_classes = [UnifiedTokenAuthentication,JWTAuthentication,SessionAuthentication]
    permission_classes = [CrudByRole]
    role_perms = {
    "admin": {"GET"},
   "customer": {"GET", "POST", "PUT", "PATCH"},
    "franchise": set(),
    "othershop": set(),
    "growtag": set(),
}
    
    def get_queryset(self):
        customer = getattr(self.request, "customer", None)
        if not customer:
            return Complaint.objects.none()

        # ✅ filtered by token customer id
        return Complaint.objects.filter(customer_id=customer.id).order_by("-created_at")
       
    def perform_create(self, serializer):
        token_customer = getattr(self.request, "customer", None)
        data = serializer.validated_data

        if token_customer:
            customer = token_customer
        else:
            phone = (data.get("customer_phone") or "").strip()
            name = (data.get("customer_name") or "").strip()
            email = data.get("email") or None

            if not phone:
               raise ValidationError({"customer_phone": ["This field is required."]})
            if not name:
               raise ValidationError({"customer_name": ["This field is required."]})

            with transaction.atomic():
                customer, created = Customer.objects.get_or_create(
                   customer_phone=phone,
                   defaults={
                    "customer_name": name,
                    "email": email,
                    "address": data.get("address") or "",
                    "state": data.get("state") or "",
                    "pincode": data.get("pincode") or "",
                    "area": data.get("area") or "",
                    },
                )

                updates = []
                if name and customer.customer_name != name:
                    customer.customer_name = name
                    updates.append("customer_name")
                if email and customer.email != email:
                    customer.email = email
                    updates.append("email")
                if updates:
                    customer.save(update_fields=updates)
        role, actor = get_actor(self.request)
        
        # Prepare audit data
        audit_data = {
           "created_on": timezone.now().date(),
        }
    
    # Set the appropriate creator field based on role
        role, actor = get_actor(self.request)

        audit_data = {
         "created_on": timezone.now().date(),
        }

        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
    

        complaint = serializer.save(
                    customer=customer,
                    customer_name=customer.customer_name,
                    customer_phone=customer.customer_phone,
                    address=data.get("address"),
                    state=data.get("state"),
                    pincode=data.get("pincode"),
                    area=data.get("area"),
                    status="Assigned" if data.get("assigned_shop") or data.get("assigned_Growtags") else "Pending",
                     **audit_data,
            )
        if complaint.email:
            subject = f"Complaint Registered Successfully (ID: {complaint.id})"
            message = (
                f"Dear {complaint.customer_name},\n\n"
                f"Your complaint has been registered successfully.\n\n"
                f"Customer ID: {customer.id}\n"
                f"Complaint ID: {complaint.id}\n"
                f"Phone: {complaint.customer_phone}\n"
                f"Issue: {complaint.issue_details}\n"
                f"Status: {complaint.status}\n\n"
                f"Assigned Type: {complaint.get_assign_to_display()}\n"
                f"Assigned To: {complaint.assigned_shop_name}\n"
                f"Thank you\nSupport Team"
            )

            try:
                send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[complaint.email],
                fail_silently=False,
                )
            except Exception as e:
               print("Email Error:", e)

        _ensure_complaint_coords(complaint)
        complaint.save()

        sync_complaint_to_customer(complaint)
    def perform_update(self, serializer):
        complaint = self.get_object()
        data = serializer.validated_data

        data.pop("customer", None)

        if getattr(self.request, "customer", None):
           data.pop("status", None)

        updated_complaint = serializer.save()

        if any(field in data for field in ["pincode", "area", "address"]):
              _ensure_complaint_coords(updated_complaint)

        if updated_complaint.assigned_shop or updated_complaint.assigned_Growtags:
            updated_complaint.status = "Assigned"
        else:
           updated_complaint.status = "Pending"

        updated_complaint.save()
        return updated_complaint

#lead viewset
from core.services import geocode_address_pincode
class LeadViewSet(BulkDeleteMixin,viewsets.ModelViewSet):
    """
    Admin: full CRUD
    Shop: create/view/update own leads
    Growtag: view own assigned leads (optional PATCH status)
    """
    authentication_classes = [UnifiedTokenAuthentication,JWTAuthentication,SessionAuthentication]
    permission_classes = [CrudByRole]
    queryset = Lead.objects.all().order_by("-created_at")
    serializer_class = LeadSerializer
    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE","PUT"},
        "franchise": {"GET", "POST", "PATCH"},
        "othershop": {"GET", "POST", "PATCH"},
        "growtag": {"GET", "PATCH"},  # optional: allow PATCH only for status fields
        # "customer": {"POST"}  # only if you want public lead create
    }
    def get_queryset(self):
        qs = super().get_queryset()

        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        if getattr(self.request, "shop", None):
            return qs.filter(assigned_shop=self.request.shop)

        if getattr(self.request, "growtag", None):
            return qs.filter(assigned_growtag=self.request.growtag)

        if getattr(self.request, "customer", None):
            return qs.filter(created_by_customer=self.request.customer)

        return qs.none()
    

    def perform_create(self, serializer):
        role, actor = get_actor(self.request)

        audit_data = {
           "created_on": timezone.now().date(),
        }
        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
        

        # ✅ THIS IS WHERE DATA IS SAVED
        serializer.save(**audit_data)
    def perform_update(self, serializer):
        # Admin / Shop: ok
        if (self.request.user and self.request.user.is_authenticated and self.request.user.is_staff) or getattr(self.request, "shop", None):
            serializer.save()
            return

        # Growtag: restrict update fields
        if getattr(self.request, "growtag", None):
            allowed_fields = {"status"}  # you can add remarks field if exists
            incoming = set(serializer.validated_data.keys())
            if not incoming.issubset(allowed_fields):
                raise PermissionDenied("Growtag can update only status")
            serializer.save()
            return

        raise PermissionDenied("Not allowed to update leads")
    
    @action(detail=True, methods=["post"])
    @transaction.atomic
    def register_complaint(self, request, pk=None):
        lead = self.get_object()

        if lead.status == "CONVERTED":
           return Response({"error": "Lead already converted"}, status=400)

        assign_to = request.data.get("assign_to")
        assigned_shop_id = request.data.get("assigned_shop")
        assigned_growtag_id = request.data.get("assigned_growtag")
        raw_password = request.data.get("password")

        if assign_to not in ["franchise", "othershop", "growtag"]:
           return Response({"error": "assign_to is required"}, status=400)

        assigned_shop = None
        assigned_growtag = None

        if assign_to in ["franchise", "othershop"]:
            if not assigned_shop_id:
               return Response({"error": "assigned_shop is required"}, status=400)
            assigned_shop = Shop.objects.filter(id=assigned_shop_id).first()
            if not assigned_shop:
               return Response({"error": "assigned_shop invalid"}, status=400)

        if assign_to == "growtag":
            if not assigned_growtag_id:
               return Response({"error": "assigned_growtag is required"}, status=400)
            assigned_growtag = Growtags.objects.filter(id=assigned_growtag_id).first()
            if not assigned_growtag:
               return Response({"error": "assigned_growtag invalid"}, status=400)

        customer = Customer.objects.filter(customer_phone=lead.customer_phone).first()
        created = False

        if not customer:
            if lead.email and Customer.objects.filter(email=lead.email).exists():
               return Response(
                {"error": "This email is already used by another customer."},
                status=400
            )

            customer = Customer(
            customer_name=lead.customer_name,
            customer_phone=lead.customer_phone,
            email=lead.email,
            address=lead.address,
            pincode=lead.pincode,
            state=lead.state,
            area=getattr(lead, "area", None),
            )
            created = True
        else:
            if lead.email and Customer.objects.filter(email=lead.email).exclude(id=customer.id).exists():
              return Response(
                {"error": "This email is already used by another customer."},
                status=400
            )

            customer.customer_name = lead.customer_name
            customer.email = lead.email
            customer.address = lead.address
            customer.pincode = lead.pincode
            customer.state = lead.state
            customer.area = getattr(lead, "area", None)

        if created:
            if not raw_password:
               return Response({"error": "password is required for new customer"}, status=400)
            customer.set_password(raw_password)
            customer.save()
        else:
           if raw_password:
            customer.set_password(raw_password)
            customer.save()
        role, actor = get_actor(request)
    
        # Prepare audit data
        audit_data = {
            "created_on": timezone.now().date(),
        }
    
        # Set the appropriate creator field based on role
        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
    
        
        complaint = Complaint.objects.create(
        customer=customer,
        customer_name=lead.customer_name,
        customer_phone=lead.customer_phone,
        email=lead.email,
        password=raw_password,
        phone_model=lead.phone_model,
        issue_details=lead.issue_detail,
        address=lead.address,
        pincode=lead.pincode,
        area=getattr(lead, "area", None),
        state=getattr(lead, "state", None),
        assign_to=assign_to,
        assigned_shop=assigned_shop,
        assigned_Growtags=assigned_growtag,
        status="Assigned",
        **audit_data,
        )
        # ✅ SEND EMAIL HERE
        if complaint.email:
            subject = f"Complaint Registered Successfully (ID: {complaint.id})"
            message = (
                    f"Dear {complaint.customer_name},\n\n"
                    f"Your complaint has been registered successfully.\n\n"
                    f"Customer ID: {customer.id}\n"
                    f"Complaint ID: {complaint.id}\n"
                    f"Phone: {complaint.customer_phone}\n"
                    f"Issue: {complaint.issue_details}\n"
                    f"Status: {complaint.status}\n\n"
                    f"Assigned Type: {complaint.get_assign_to_display()}\n"
                    f"Assigned To: {complaint.assigned_shop_name}\n"
                    f"Thank you\nSupport Team"
                )

            try:
                send_mail(
                  subject=subject,
                  message=message,
                  from_email=settings.DEFAULT_FROM_EMAIL,
                  recipient_list=[complaint.email],
                  fail_silently=False,
                )
            except Exception as e:
               print("Email Error:", e)

        try:
           res = geocode_address_pincode(complaint.area, complaint.pincode)
           if res and len(res) == 3:
            lat, lon, precision = res
            complaint.latitude = lat
            complaint.longitude = lon
            complaint.save(update_fields=["latitude", "longitude"])
        except Exception as e:
           print("Geocode Error:", str(e))

        lead.complaint = complaint
        lead.status = Lead.STATUS_COMPLAINT
        lead.save(update_fields=["complaint", "status"])

        return Response(
        {
            "message": "Complaint created (manual assignment)",
            "complaint_id": complaint.id,
            "latitude": complaint.latitude,
            "longitude": complaint.longitude,
        },
        status=status.HTTP_201_CREATED
       )
@action(detail=True, methods=["get"])
def complaint_prefill(self, request, pk=None):
        lead = self.get_object()

        return Response({
            "customer_name": lead.customer_name,
            "customer_phone": lead.customer_phone,
            "email": lead.email,
            "phone_model": lead.phone_model,
            "issue_details": lead.issue_detail,
            "address": lead.address,
            "pincode": lead.pincode,
            "area": getattr(lead, "area", None),
            "state": getattr(lead, "state", None),
            # defaults for form
            "assign_to": "franchise",
            "assigned_shop": None,
            "assigned_growtag": None,
        })
    
class SalesIQLeadWebhook(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        payload = request.data or {}

        visitor = payload.get("visitor") or {}
        chat = payload.get("chat") or {}

        # ✅ extract from visitor
        phone = (visitor.get("phone") or "").strip()
        email = (visitor.get("email") or "").strip() or None
        name = (visitor.get("name") or "Unknown").strip()

        # ✅ visitor id (if present)
        visitor_id = (
            payload.get("visitor_id")
            or visitor.get("id")
            or payload.get("salesiq_visitor_id")
        )

        # ✅ issue from chat (optional but recommended)
        subject = (chat.get("subject") or "").strip()
        message = (chat.get("message") or "").strip()
        issue_detail = " - ".join([x for x in [subject, message] if x])

        # dedupe: prefer phone else visitor_id
        lead = None
        if phone:
            lead = Lead.objects.filter(customer_phone=phone).first()
        if not lead and visitor_id:
            lead = Lead.objects.filter(salesiq_visitor_id=visitor_id).first()

        if lead:
            lead.customer_name = name or lead.customer_name
            lead.customer_phone = phone or lead.customer_phone
            lead.email = email or lead.email
            lead.source = "SALESIQ"
            lead.raw_payload = payload

            # save issue if your Lead model has it
            if hasattr(lead, "issue_detail") and issue_detail:
                lead.issue_detail = issue_detail

            lead.save()
            return Response({"message": "Lead updated", "lead_code": lead.lead_code})

        create_kwargs = dict(
            customer_name=name,
            customer_phone=phone or "",
            email=email,
            source="SALESIQ",
            salesiq_visitor_id=visitor_id,
            raw_payload=payload,
        )
        if hasattr(Lead, "issue_detail") and issue_detail:
            create_kwargs["issue_detail"] = issue_detail

        lead = Lead.objects.create(**create_kwargs)
        return Response({"message": "Lead created", "lead_code": lead.lead_code}, status=201)

#vendor
from collections import Counter
from django.db.models import Q, Count

from .models import Vendor
from .serializers import VendorSerializer

class VendorListCreateAPIView(APIView):
    """
    Vendors page API:
    - GET: list vendors + search + status filter + counts (active/inactive)
    - POST: create vendor (Add Vendor popup)
    """
    authentication_classes = [UnifiedTokenAuthentication,JWTAuthentication,SessionAuthentication]
    permission_classes = [CrudByRole]
    queryset = Vendor.objects.all().order_by("-id")
    serializer_class = VendorSerializer

    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE","PUT"},
        "franchise": {"GET", "POST", "PATCH","PUT"},
        "othershop": {"GET", "POST", "PATCH","PUT"},
        "growtag": {"GET", "POST", "PATCH", "PUT"},
    }
    def base_queryset(self, request):
        qs = Vendor.objects.all()

        # Admin sees all vendors
        if request.user and request.user.is_authenticated and request.user.is_staff:
            return qs

        # Shop: assigned shop OR legacy rows (shop NULL but created by this shop)
        if getattr(request, "shop", None):
            s = request.shop
            return qs.filter(Q(shop=s) | Q(shop__isnull=True, created_by_shop=s))

        if getattr(request, "growtag", None):
            g = request.growtag
            return qs.filter(
                Q(growtag=g) | Q(growtag__isnull=True, created_by_growtag=g)
            )
        return qs.none()

    def perform_create(self,serializer):
        role, actor = get_actor(self.request)
    
        # Prepare audit data
        audit_data = {
            "created_on": timezone.now().date(),
        }
    
        # Set the appropriate creator field based on role
        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
            if actor is not None:
                audit_data["shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
            if actor is not None:
                audit_data["growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
        
        serializer.save(**audit_data)
    

    def get(self, request):
        search = (request.query_params.get("search") or "").strip()
        status_filter = (request.query_params.get("status") or "").strip().lower()
        ordering = (request.query_params.get("ordering") or "-created_at").strip()

        qs = self.base_queryset(request)

        if status_filter in ["active", "inactive"]:
            qs = qs.filter(status=status_filter)

        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(email__icontains=search)
                | Q(phone__icontains=search)
                | Q(website__icontains=search)
                | Q(address__icontains=search)
            )

        allowed_ordering = {"name", "-name", "created_at", "-created_at", "id", "-id"}
        if ordering not in allowed_ordering:
            ordering = "-created_at"
        qs = qs.order_by(ordering)

        data = VendorSerializer(qs, many=True).data

        # Count from the same payload we return (avoids ORM group-by / order_by quirks)
        status_counts = Counter(
            (row.get("status") or "").strip().lower() for row in data
        )

        return Response(
            {
                "success": True,
                "message": "Vendors fetched successfully",
                "count": len(data),
                "counts": {
                    "active": status_counts.get("active", 0),
                    "inactive": status_counts.get("inactive", 0),
                },
                "data": data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        serializer = VendorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)  # ✅ important
        return Response(
            {
                "success": True,
                "message": "Vendor created successfully",
                "data": serializer.data,
            },
            status=status.HTTP_201_CREATED,
        )


class VendorDetailAPIView(APIView):
    """
    Row Actions API:
    - PATCH: edit vendor (pencil)
    - DELETE: delete vendor (trash)
    - GET: optional (fetch single vendor for edit form)
    """
    authentication_classes = [UnifiedTokenAuthentication,JWTAuthentication,SessionAuthentication]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"GET", "PATCH", "DELETE","PUT"},
        "franchise": {"GET", "PATCH","PUT"},
        "othershop": {"GET", "PATCH","PUT"},
        "growtag": {"GET", "PATCH", "PUT"},
    }

    def get_object(self, pk):
        vendor = get_object_or_404(Vendor, pk=pk)

        # Admin can access any vendor
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return vendor

        # Shop can access ONLY its own vendors
        if getattr(self.request, "shop", None):
            if getattr(vendor, "shop_id", None) != self.request.shop.id:
                raise PermissionDenied("You cannot access this vendor.")
            return vendor

        if getattr(self.request, "growtag", None):
            if getattr(vendor, "growtag_id", None) != self.request.growtag.id:
                raise PermissionDenied("You cannot access this vendor.")
            return vendor

        raise PermissionDenied("Not allowed.")

    def get(self, request, pk):
        vendor = self.get_object(pk)
        return Response({"success": True, "data": VendorSerializer(vendor).data}, status=200)

    def patch(self, request, pk):
        vendor = self.get_object(pk)
        serializer = VendorSerializer(vendor, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {"success": True, "message": "Vendor updated successfully", "data": serializer.data},
            status=200,
        )

    def delete(self, request, pk):
        vendor = self.get_object(pk)
        vendor.delete()
        return Response({"success": True, "message": "Vendor deleted successfully"}, status=200)
    def put(self, request, pk):
        vendor = self.get_object(pk)
        serializer = VendorSerializer(vendor, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(
            {
            "success": True,
            "message": "Vendor updated successfully",
            "data": serializer.data,
            },
           status=200,
        )
    
#purchase order
class PurchaseOrderItemViewSet(viewsets.ModelViewSet):
    authentication_classes = [
        SessionAuthentication,
       JWTAuthentication,
       UnifiedTokenAuthentication
    ]
    permission_classes = [CrudByRole]
    queryset = PurchaseOrderItem.objects.select_related("purchase_order").all().order_by("-created_at")
    serializer_class = PurchaseOrderItemSerializer

    # same style permissions
    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE","PUT"},
        "franchise": {"GET", "POST", "PATCH","PUT"},
        "othershop": {"GET", "POST", "PATCH","PUT"},
        "growtag": {"GET"},      # view only (change if you want)
        "customer": set(),
    }

    def get_queryset(self):
        qs = super().get_queryset()

        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
           return qs

        if getattr(self.request, "shop", None):
           return qs.filter(purchase_order__shop=self.request.shop)

        # ✅ FIX: PurchaseOrder has no growtag field
        if getattr(self.request, "growtag", None):
           return qs.none()

        return qs.none()

    def get_object(self):
        obj = super().get_object()

        # Admin ok
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
           return obj

        # Shop ownership check
        if getattr(self.request, "shop", None):
           if getattr(obj.purchase_order, "shop_id", None) != self.request.shop.id:
              raise PermissionDenied("You cannot access this purchase order item.")
           return obj

        # Growtag ownership check
        if getattr(self.request, "growtag", None):
            raise PermissionDenied("You cannot access this purchase order item.")
        raise PermissionDenied("Not allowed")

    def perform_create(self, serializer):
        po = serializer.validated_data.get("purchase_order")
        if not po:
            raise PermissionDenied("purchase_order is required")
        role, actor = get_actor(self.request)

        audit_data = {
           "created_on": timezone.now().date(),
        }
        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
        

        # ✅ THIS IS WHERE DATA IS SAVED
        serializer.save(**audit_data)
        

    def perform_update(self, serializer):
        # Admin can update anything
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            serializer.save()
            return

        # Shop can update only its own PO items (already restricted by get_queryset)
        if getattr(self.request, "shop", None):
             # ✅ Block editing if the PurchaseOrder is confirmed/cancelled
            po = serializer.instance.purchase_order
            if getattr(po, "status", "").upper() in ("SENT", "RECEIVED", "CANCELLED"):
                raise PermissionDenied("Cannot edit items after PO confirmed/cancelled")
            serializer.save()
            return

        raise PermissionDenied("Not allowed to update purchase order items")
class PurchaseOrderListCreateAPIView(ListCreateAPIView):
    
    authentication_classes = [
        SessionAuthentication,
        JWTAuthentication,
        UnifiedTokenAuthentication
    ]
    permission_classes = [CrudByRole]
    filter_backends = [SearchFilter]
    search_fields = ["po_number", "vendor__name", "status"]
    role_perms = {
        "admin": {"GET", "POST","PATCH","PUT","DELETE"},
        "franchise": {"GET", "POST","PATCH","PUT"},
        "othershop": {"GET", "POST","PATCH","PUT"},
        "growtag": {"GET"},   # usually view only
        "customer": set(),
    }
    
    def get_queryset(self):
        qs = (PurchaseOrder.objects
               .select_related("vendor", "shop")
               .prefetch_related(
                   Prefetch(
                           "items",
                  queryset=PurchaseOrderItem.objects.select_related("item")
              )
            )
            .order_by("-id")
        )

        # Admin sees all
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # Shop sees only its purchase orders (CHANGE FIELD NAME if needed)
        if getattr(self.request, "shop", None):
            return qs.filter(shop=self.request.shop)

        # PurchaseOrder has no growtag field
        if getattr(self.request, "growtag", None):
           return qs.none()
        return qs.none()

    def get_serializer_class(self):
        if self.request.method == "GET":
            return PurchaseOrderListSerializer
        return PurchaseOrderSerializer  # POST create uses full serializer
    def perform_create(self, serializer):
        created_by_data = {}

        # Admin can create any
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            created_by_data["created_by_user"] = self.request.user
            serializer.save(**created_by_data)
            return

        # Shop creates PO for itself
        if getattr(self.request, "shop", None):
            created_by_data["created_by_shop"] = self.request.shop
            serializer.save(shop=self.request.shop, **created_by_data)
            return

        raise PermissionDenied("Not allowed to create Purchase Order")


class PurchaseOrderDetailAPIView(RetrieveUpdateDestroyAPIView):
    authentication_classes = [
        SessionAuthentication,
        JWTAuthentication,
        UnifiedTokenAuthentication,
    ]
    permission_classes = [CrudByRole]
    serializer_class = PurchaseOrderSerializer
    role_perms = {
        "admin": {"GET", "PATCH", "DELETE","PUT"},
        "franchise": {"GET", "PATCH","PUT"},
        "othershop": {"GET", "PATCH","PUT"},
        "growtag": {"GET"},
        "customer": set(),
    }
    
    def get_queryset(self):
        qs = (
              PurchaseOrder.objects
              .select_related("vendor", "shop")
              .prefetch_related(
                    Prefetch(
                         "items",
                          queryset=PurchaseOrderItem.objects.select_related("item")
                    )
                )
                .order_by("-id")
              )
        # Admin sees all
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # Shop sees only its POs (CHANGE FIELD NAME if needed)
        if getattr(self.request, "shop", None):
            return qs.filter(shop=self.request.shop)

        # PurchaseOrder has no growtag field
        if getattr(self.request, "growtag", None):
           return qs.none()

        return qs.none()

    def perform_update(self, serializer):
        obj = self.get_object()

        # Admin can update anything
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            serializer.save()
            return

        # Shop can update ONLY if not confirmed
        if getattr(self.request, "shop", None):
            if getattr(obj, "status", "").upper() in ("SENT", "RECEIVED", "CANCELLED"):
                raise PermissionDenied("Cannot edit after confirmed/cancelled")
            serializer.save()
            return

        raise PermissionDenied("Not allowed to update Purchase Order")
#pdf_view
@api_view(["GET"])
@authentication_classes([JWTAuthentication, SessionAuthentication, UnifiedTokenAuthentication])
@permission_classes([CrudByRole])
def purchase_order_pdf_view(request, pk):
    po = get_object_or_404(
        PurchaseOrder.objects.select_related("vendor", "shop").prefetch_related("items__item"),
        pk=pk
    )

    # permission check
    u = getattr(request, "user", None)
    if u and u.is_authenticated and u.is_staff:
        pass
    elif getattr(request, "shop", None):
        if po.shop_id != request.shop.id:
            raise PermissionDenied("You cannot access this purchase order.")
    else:
        raise PermissionDenied("Not allowed.")

    items = po.items.all()
    total_in_words = purchase_order_amount_to_words(po.grand_total)
    base_font = po_register_unicode_font()

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="POTitle",
        parent=styles["Title"],
        fontName=base_font,
        fontSize=22,
        leading=26,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    ))

    styles.add(ParagraphStyle(
        name="POSmall",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#475569"),
    ))

    styles.add(ParagraphStyle(
        name="POBody",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
    ))

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="purchase_order_{po.id}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Purchase Order {po.po_number}",
    )

    elements = []

    PAGE_WIDTH = 182 * mm
    LEFT_BOX_W = 112 * mm
    RIGHT_BOX_W = PAGE_WIDTH - LEFT_BOX_W

    # logo
    logo_path = Path(settings.BASE_DIR) / "static" / "img" / "logo.jpg"
    if os.path.exists(logo_path):
        logo = Image(str(logo_path))
        logo.drawHeight = 25 * mm
        logo.drawWidth = 60 * mm
        logo.hAlign = "LEFT"
        elements.append(logo)
        elements.append(Spacer(1, 8))

    elements.append(Paragraph("PURCHASE ORDER", styles["POTitle"]))

    right_style = ParagraphStyle(
        "POOrgRight",
        parent=styles["POSmall"],
        alignment=TA_RIGHT
    )

    left_block = Paragraph(
        f'PO Number: <b>{po.po_number}</b><br/>'
        f'PO Date: <b>{po.po_date}</b><br/>'
        f'Expected Delivery: <b>{po.expected_delivery_date or "-"}</b><br/>'
        f'Status: <b>{po.get_status_display()}</b>',
        styles["POSmall"]
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

    # vendor section
    vendor_data = [
        ["Vendor Name", po.vendor.name if po.vendor else "-"],
        ["Phone", getattr(po.vendor, "phone", "-") or "-"],
        ["Email", getattr(po.vendor, "email", "-") or "-"],
        ["Address", getattr(po.vendor, "address", "-") or "-"],
        ["Ship To", po.ship_to or "-"],
        ["Bill To", po.bill_to or "-"],
    ]

    vendor_tbl = Table(vendor_data, colWidths=[42 * mm, 140 * mm], hAlign="LEFT")
    vendor_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cfd8e3")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(vendor_tbl)
    elements.append(Spacer(1, 10))

    # items table
    item_data = [[
        "#", "Item", "Description", "Qty", "Unit Price",
        "Tax %", "Disc %", "Tax Amt", "Amount"
    ]]

    for i, item in enumerate(items, start=1):
        item_data.append([
            str(i),
            item.item_name or (item.item.name if item.item else ""),
            item.description or "",
            str(item.qty),
            po_money(item.unit_price),
            f"{Decimal(item.tax_percent or 0):.2f}%",
            f"{Decimal(item.discount_percent or 0):.2f}%",
            po_money(item.tax_amount),
            po_money(item.line_total),
        ])

    items_tbl = Table(
        item_data,
        colWidths=[8 * mm, 32 * mm, 38 * mm, 14 * mm, 22 * mm, 15 * mm, 15 * mm, 18 * mm, 20 * mm],
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
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(items_tbl)
    elements.append(Spacer(1, 10))

    # totals section
    totals = [
        ["Sub Total", po_money(po.subtotal)],
        ["Discount (-)", po_money(po.total_discount)],
        ["Total Tax", po_money(po.total_tax)],
        ["Shipping Charges", po_money(po.shipping_charges)],
        ["Adjustment", po_money(po.adjustment)],
        ["GRAND TOTAL", po_money(po.grand_total)],
    ]

    totals_tbl = Table(totals, colWidths=[42 * mm, 28 * mm], hAlign="LEFT")
    totals_tbl.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8e3")),
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 5), (-1, 5), colors.HexColor("#1e4d86")),
        ("TEXTCOLOR", (0, 5), (-1, 5), colors.white),
    ]))

    notes_box = [
        Paragraph("<b>Total In Words</b>", styles["POBody"]),
        Spacer(1, 4),
        Paragraph(f"<i>{total_in_words}</i>", styles["POBody"]),
        Spacer(1, 10),
        Paragraph("<b>Notes</b>", styles["POBody"]),
        Spacer(1, 4),
        Paragraph(po.notes or "-", styles["POSmall"]),
        Spacer(1, 10),
        Paragraph("<b>Terms and Conditions</b>", styles["POBody"]),
        Spacer(1, 4),
        Paragraph(po.terms_and_conditions or "-", styles["POSmall"]),
    ]

    left_box = Table([[notes_box]], colWidths=[LEFT_BOX_W])
    left_box.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cfd8e3")),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
    ]))

    bottom_tbl = Table([[left_box, totals_tbl]], colWidths=[LEFT_BOX_W, RIGHT_BOX_W], hAlign="LEFT")
    bottom_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))

    elements.append(bottom_tbl)

    doc.build(elements)
    return response


purchase_order_pdf_view.cls.role_perms = {
    "admin": {"GET"},
    "franchise": {"GET"},
    "othershop": {"GET"},
    "growtag": set(),
    "customer": set(),
}
#bills
class PurchaseBillViewSet(viewsets.ModelViewSet):
    authentication_classes = [
        SessionAuthentication,
        JWTAuthentication,
        UnifiedTokenAuthentication
    ]
    permission_classes = [CrudByRole]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ["bill_number", "vendor_name", "payment_status", "status"]
    ordering_fields = ["bill_date", "due_date", "created_at", "total", "balance_due"]
    ordering = ["-created_at"]
    queryset = PurchaseBill.objects.prefetch_related(
                  Prefetch("items", queryset=PurchaseBillItem.objects.select_related("item")),
                  "payments"
               )
    role_perms = {
        "admin": {"GET", "POST", "PATCH", "DELETE","PUT"},
        "franchise": {"GET", "POST", "PATCH","PUT"},   # shop users
        "othershop": {"GET", "POST", "PATCH","PUT"},   # shop users
        "growtag": {"GET", "POST", "PATCH","PUT"},     # allow create/update for their own bills
        "customer": set(),
    }
   


    def get_serializer_class(self):
        if self.action == "list":
            return PurchaseBillListSerializer
        return PurchaseBillCreateUpdateSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # ✅ Admin sees all
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # ✅ Shop sees only its own bills (owner_type=shop AND shop=request.shop)
        if getattr(self.request, "shop", None):
            return qs.filter(owner_type="shop", shop=self.request.shop)

        # ✅ Growtag sees only its own bills (owner_type=growtag AND growtag=request.growtag)
        if getattr(self.request, "growtag", None):
            return qs.filter(owner_type="growtag", growtag=self.request.growtag)

        return qs.none()

    def perform_create(self,serializer):
        role, actor = get_actor(self.request)
    
        # Prepare audit data
        audit_data = {
        "created_on": timezone.now().date(),
        }
    
        # Set the appropriate creator field based on role
        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
    

        else:
            raise PermissionDenied("Not allowed to create PurchaseBill")

        serializer.save(**audit_data)
    def perform_update(self, serializer):
        # ✅ Admin can update any
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            serializer.save()
            return

        # ✅ Shop: cannot change ownership; keep owner_type/shop/growtag locked
        if getattr(self.request, "shop", None):
            serializer.save(
                owner_type="shop",
                shop=self.request.shop,
                growtag=None,
            )
            return

        # ✅ Growtag: cannot change ownership; keep owner_type/shop/growtag locked
        if getattr(self.request, "growtag", None):
            serializer.save(
                owner_type="growtag",
                growtag=self.request.growtag,
                shop=None,
            )
            return

        raise PermissionDenied("Not allowed to update PurchaseBill")

    def perform_destroy(self, instance):
        # ✅ Admin only delete (recommended for accounting)
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            instance.delete()
            return
        raise PermissionDenied("Only admin can delete PurchaseBill")
    @action(detail=True, methods=["post"], url_path="add-payment")
    @transaction.atomic
    def add_payment(self, request, pk=None):
        # lock bill row so balance_due can't change mid-request
        bill = PurchaseBill.objects.select_for_update().get(pk=pk)

        ser = PurchaseBillPaymentSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        amount = ser.validated_data.get("amount") or Decimal("0.00")
        if amount <= 0:
            raise ValidationError({"amount": "Amount must be greater than 0."})

        # IMPORTANT: make sure bill balance_due is fresh
        bill.recalc_totals()
        bill.refresh_from_db(fields=["balance_due", "total", "amount_paid", "payment_status"])

        if bill.balance_due <= 0:
            raise ValidationError({"detail": "Bill is already fully paid. No further payment allowed."})

        if amount > bill.balance_due:
            raise ValidationError({"amount": f"Amount cannot exceed balance due ({bill.balance_due})."})
        

        role, actor = get_actor(request)
    
        # Prepare audit data
        audit_data = {
            "created_on": timezone.now().date(),
        }
        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
        # Set the appropriate creator field based on role
        
        PurchaseBillPayment.objects.create(
            bill=bill,
            payment_date=ser.validated_data.get("payment_date"),
            amount=amount,
            method=ser.validated_data.get("method", ""),
            reference=ser.validated_data.get("reference", ""),
             **audit_data
        )

        bill.recalc_totals()
        bill.refresh_from_db()

        out = PurchaseBillCreateUpdateSerializer(bill, context={"request": request})
        return Response(out.data, status=status.HTTP_200_OK)
#bill pdf view
@api_view(["GET"])
@authentication_classes([JWTAuthentication, SessionAuthentication, UnifiedTokenAuthentication])
@permission_classes([CrudByRole])
def purchase_bill_pdf_view(request, pk):
    bill = get_object_or_404(PurchaseBill, pk=pk)

    # permissions - same style as quotation
    u = getattr(request, "user", None)
    if u and u.is_authenticated and u.is_staff:
        pass
    elif getattr(request, "shop", None):
        if bill.shop_id != request.shop.id:
            raise PermissionDenied("You cannot access this purchase bill.")
    elif getattr(request, "growtag", None):
        if bill.growtag_id != request.growtag.id:
            raise PermissionDenied("You cannot access this purchase bill.")
    else:
        raise PermissionDenied("Not allowed.")

    # refresh totals before print
    bill.recalc_totals()
    bill.refresh_from_db()

    items = bill.items.select_related("item").all()
    base_font = pb_register_unicode_font()

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="PBTitle",
        parent=styles["Title"],
        fontName=base_font,
        fontSize=24,
        leading=28,
        spaceAfter=8,
        textColor=colors.HexColor("#0f172a"),
    ))

    styles.add(ParagraphStyle(
        name="PBSmall",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#475569"),
    ))

    styles.add(ParagraphStyle(
        name="PBBody",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=11,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
    ))

    styles.add(ParagraphStyle(
        name="PBRight",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=10,
        leading=13,
        alignment=TA_RIGHT,
        textColor=colors.HexColor("#0f172a"),
    ))

    styles.add(ParagraphStyle(
        name="PBCenter",
        parent=styles["Normal"],
        fontName=base_font,
        fontSize=9,
        leading=12,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#0f172a"),
    ))

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="purchase_bill_{bill.bill_number}.pdf"'

    doc = SimpleDocTemplate(
        response,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=f"Purchase Bill {bill.bill_number}",
    )

    elements = []

    PAGE_WIDTH = 182 * mm
    LEFT_BOX_W = 112 * mm
    RIGHT_BOX_W = PAGE_WIDTH - LEFT_BOX_W

    # logo
    logo_path = Path(settings.BASE_DIR) / "static" / "img" / "logo.jpg"
    if os.path.exists(logo_path):
        logo = Image(str(logo_path))
        logo.drawHeight = 25 * mm
        logo.drawWidth = 60 * mm
        logo.hAlign = "LEFT"
        elements.append(logo)
        elements.append(Spacer(1, 8))

    # title
    elements.append(Paragraph("PURCHASE BILL", styles["PBTitle"]))

    right_style = ParagraphStyle(
        "PBOrgRight",
        parent=styles["PBSmall"],
        alignment=TA_RIGHT
    )

    #owner_name = "-"
    #owner_type = "-"
    #if bill.shop:
        #owner_name = getattr(bill.shop, "name", "") or str(bill.shop)
        #owner_type = "Shop"
    #elif bill.growtag:
        #owner_name = getattr(bill.growtag, "name", "") or str(bill.growtag)
        #owner_type = "Growtag"

    left_block = Paragraph(
        f'Bill Number: <b>{pb_text(bill.bill_number)}</b><br/>'
        f'Bill Date: <b>{bill.bill_date or "-"}</b><br/>'
        f'Due Date: <b>{bill.due_date or "-"}</b><br/>'
        f'Status: <b>{bill.get_status_display() if hasattr(bill, "get_status_display") else pb_text(bill.status)}</b><br/>'
        f'Payment Status: <b>{bill.get_payment_status_display() if hasattr(bill, "get_payment_status_display") else pb_text(bill.payment_status)}</b>',
        styles["PBSmall"]
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

    # vendor + address section
    vendor_data = [
        ["Vendor Name", bill.vendor_name or "-"],
        ["Email", bill.vendor_email or "-"],
        ["Phone", bill.vendor_phone or "-"],
        ["GSTIN", bill.vendor_gstin or "-"],
        ["Vendor Address", bill.vendor_address or "-"],
        ["Bill To", bill.bill_to or "-"],
        ["Ship To", bill.ship_to or "-"],
        ["Order Number", bill.order_number or "-"],
    ]

    vendor_tbl = Table(vendor_data, colWidths=[42 * mm, 140 * mm], hAlign="LEFT")
    vendor_tbl.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), base_font),
        ("GRID", (0, 0), (-1, -1), 0.6, colors.HexColor("#cfd8e3")),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(vendor_tbl)
    elements.append(Spacer(1, 10))

    # items table
    data = [["#", "Item", "Description", "Qty", "Rate", "Tax %", "Discount %", "Amount"]]
    for i, ln in enumerate(items, start=1):
        data.append([
            str(i),
            ln.name or (ln.item.name if ln.item else ""),
            ln.description or "",
            f"{Decimal(ln.qty or 0):.2f}",
            pb_money(ln.rate),
            f"{Decimal(ln.tax_percent or 0):.2f}%",
            f"{Decimal(ln.discount_percent or 0):.2f}%",
            pb_money(ln.amount),
        ])

    items_tbl = Table(
        data,
        colWidths=[8 * mm, 34 * mm, 50 * mm, 14 * mm, 20 * mm, 18 * mm, 20 * mm, 18 * mm],
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
        ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elements.append(items_tbl)
    elements.append(Spacer(1, 10))

    # totals section
    totals = [
        ["Sub Total", pb_money(bill.subtotal)],
        ["Discount (-)", pb_money(bill.total_discount)],
        ["Tax", pb_money(bill.total_tax)],
        ["TDS %", f"{Decimal(bill.tds_percent or 0):.2f}%"],
        ["TDS Amount", pb_money(bill.tds_amount)],
        ["Shipping Charge", pb_money(bill.shipping_charges)],
        ["Adjustment", pb_money(bill.adjustment)],
        ["GRAND TOTAL", pb_money(bill.total)],
        ["Amount Paid", pb_money(bill.amount_paid)],
        ["Balance Due", pb_money(bill.balance_due)],
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
        Paragraph("<b>Notes</b>", styles["PBBody"]),
        Spacer(1, 4),
        Paragraph(bill.notes or "-", styles["PBSmall"]),
        Spacer(1, 10),

        Paragraph("<b>Terms and Conditions</b>", styles["PBBody"]),
        Spacer(1, 4),
        Paragraph(bill.terms_and_conditions or "-", styles["PBSmall"]),
    ]

    bottom_tbl = Table(
        [[notes_box, totals_tbl]],
        colWidths=[LEFT_BOX_W, RIGHT_BOX_W],
        hAlign="LEFT"
    )

    bottom_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (0, 0), 0.8, colors.HexColor("#cfd8e3")),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("LEFTPADDING", (0, 0), (0, 0), 10),
        ("RIGHTPADDING", (0, 0), (0, 0), 10),
        ("TOPPADDING", (0, 0), (0, 0), 10),
        ("BOTTOMPADDING", (0, 0), (0, 0), 10),
    ]))

    elements.append(bottom_tbl)
    elements.append(Spacer(1, 10))

    elements.append(
        Paragraph("This is a system generated purchase bill.", styles["PBSmall"])
    )

    doc.build(elements)
    return response


purchase_bill_pdf_view.cls.role_perms = {
    "admin": {"GET"},
    "franchise": {"GET"},
    "othershop": {"GET"},
    "growtag": {"GET"},
    "customer": set(),
}
#stock
# Replace these permissions with your real ones:
class IsShopOrGrowtag(BasePermission):
    def has_permission(self, request, view):
        return bool(getattr(request, "shop", None) or getattr(request, "growtag", None))


class InventoryStockViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Admin:
      - can view all stocks
      - can filter by group=franchise|othershop|growtag
      - can use filters/summary/adjust

    Franchise / Other shop:
      - GET /stocks/?group=franchise or ?group=othershop
      - sees only own stock

    Growtag:
      - GET /stocks/?group=growtag
      - sees only own stock
    """

    authentication_classes = [
        SessionAuthentication,
        JWTAuthentication,
        UnifiedTokenAuthentication,
    ]
    permission_classes = [CrudByRole]
    serializer_class = InventoryStockSerializer
    queryset = InventoryStock.objects.select_related(
        "item", "shop", "growtag"
    ).all().order_by("-updated_at")

    role_perms = {
        "admin": {"GET", "POST"},
        "franchise": {"GET"},
        "othershop": {"GET"},
        "growtag": {"GET"},
        "customer": set(),
    }

    # -----------------------------
    # Helpers
    # -----------------------------
    def is_admin_user(self, request):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )

    def apply_status_filter(self, qs, status_filter):
        if status_filter == "in_stock":
            qs = qs.filter(qty_on_hand__gt=F("reorder_level"))
        elif status_filter == "low_stock":
            qs = qs.filter(qty_on_hand__gt=0, qty_on_hand__lte=F("reorder_level"))
        elif status_filter == "out_of_stock":
            qs = qs.filter(qty_on_hand__lte=0)
        return qs

    def get_base_filtered_queryset(self):
        """
        Common filtering logic used by list + summary.
        """
        #qs = self.queryset
        qs = self.queryset.all()

        group = self.request.query_params.get("group")
        shop_id = self.request.query_params.get("shop_id")
        growtag_id = self.request.query_params.get("growtag_id")
        item_id = self.request.query_params.get("item")
        status_filter = self.request.query_params.get("status")

        # -------------------------
        # ADMIN
        # -------------------------
        if self.is_admin_user(self.request):
            if group == "franchise":
                qs = qs.filter(owner_type="shop", shop__shop_type="franchise")
            elif group == "othershop":
                qs = qs.filter(owner_type="shop", shop__shop_type="othershop")
            elif group == "growtag":
                qs = qs.filter(owner_type="growtag")

            if shop_id:
                qs = qs.filter(owner_type="shop", shop_id=shop_id)

            if growtag_id:
                qs = qs.filter(owner_type="growtag", growtag_id=growtag_id)

            if item_id:
                qs = qs.filter(item_id=item_id)

            qs = self.apply_status_filter(qs, status_filter)
            return qs

        # -------------------------
        # SHOP TOKEN
        # -------------------------
        if getattr(self.request, "shop", None):
            shop = self.request.shop

            qs = qs.filter(owner_type="shop", shop=shop)

            # group handling
            if group == "franchise" and shop.shop_type != "franchise":
                return qs.none()

            if group == "othershop" and shop.shop_type != "othershop":
                return qs.none()

            if group == "growtag":
                return qs.none()

            # prevent access to another shop
            if shop_id and str(shop.id) != str(shop_id):
                return qs.none()

            # shop cannot query growtag stock
            if growtag_id:
                return qs.none()

            if item_id:
                qs = qs.filter(item_id=item_id)

            qs = self.apply_status_filter(qs, status_filter)
            return qs

        # -------------------------
        # GROWTAG TOKEN
        # -------------------------
        if getattr(self.request, "growtag", None):
            growtag = self.request.growtag

            qs = qs.filter(owner_type="growtag", growtag=growtag)

            if group in ("franchise", "othershop"):
                return qs.none()

            # prevent access to another growtag
            if growtag_id and str(growtag.id) != str(growtag_id):
                return qs.none()

            # growtag cannot query shop stock
            if shop_id:
                return qs.none()

            if item_id:
                qs = qs.filter(item_id=item_id)

            qs = self.apply_status_filter(qs, status_filter)
            return qs

        return qs.none()

    # -----------------------------
    # Main list / detail
    # -----------------------------
    def get_queryset(self):
        return self.get_base_filtered_queryset()

    # -----------------------------
    # Filters - admin only
    # -----------------------------
    @action(detail=False, methods=["get"], url_path="filters")
    def filters(self, request):
        if not self.is_admin_user(request):
            return Response(
                {"detail": "Only admin can view stock filters."},
                status=status.HTTP_403_FORBIDDEN,
            )

        data = {
            "franchise_shops": list(
                Shop.objects.filter(shop_type="franchise")
                .values("id", "shopname")
                .order_by("shopname")
            ),
            "other_shops": list(
                Shop.objects.filter(shop_type="othershop")
                .values("id", "shopname")
                .order_by("shopname")
            ),
            "growtags": list(
                Growtags.objects.values("id", "grow_id", "name").order_by("grow_id")
            ),
            "status_options": [
                {"key": "in_stock", "label": "In Stock"},
                {"key": "low_stock", "label": "Low Stock"},
                {"key": "out_of_stock", "label": "Out of Stock"},
            ],
            "group_options": [
                {"key": "franchise", "label": "Franchise"},
                {"key": "othershop", "label": "Other Shop"},
                {"key": "growtag", "label": "Growtag"},
            ],
        }
        return Response(data)

    # -----------------------------
    # Summary - role based
    # -----------------------------
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        qs = self.get_base_filtered_queryset()

        total_items = qs.count()
        in_stock = qs.filter(qty_on_hand__gt=F("reorder_level")).count()
        low_stock = qs.filter(qty_on_hand__gt=0, qty_on_hand__lte=F("reorder_level")).count()
        out_of_stock = qs.filter(qty_on_hand__lte=0).count()

        return Response({
            "total_items": total_items,
            "in_stock": in_stock,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
        })

    # -----------------------------
    # My stocks - optional shortcut
    # -----------------------------
    @action(detail=False, methods=["get"], url_path="my")
    def my_stock(self, request):
        if getattr(request, "shop", None):
            qs = self.queryset.filter(owner_type="shop", shop=request.shop)
        elif getattr(request, "growtag", None):
            qs = self.queryset.filter(owner_type="growtag", growtag=request.growtag)
        else:
            return Response(
                {"detail": "Only shop or growtag can view own stock."},
                status=status.HTTP_403_FORBIDDEN,
            )

        item_id = request.query_params.get("item")
        status_filter = request.query_params.get("status")

        if item_id:
            qs = qs.filter(item_id=item_id)

        qs = self.apply_status_filter(qs, status_filter)

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="my-summary")
    def my_summary(self, request):
        if getattr(request, "shop", None):
            qs = self.queryset.filter(owner_type="shop", shop=request.shop)
        elif getattr(request, "growtag", None):
            qs = self.queryset.filter(owner_type="growtag", growtag=request.growtag)
        else:
            return Response(
                {"detail": "Only shop or growtag can view own stock summary."},
                status=status.HTTP_403_FORBIDDEN,
            )

        total_items = qs.count()
        in_stock = qs.filter(qty_on_hand__gt=F("reorder_level")).count()
        low_stock = qs.filter(qty_on_hand__gt=0, qty_on_hand__lte=F("reorder_level")).count()
        out_of_stock = qs.filter(qty_on_hand__lte=0).count()

        return Response({
            "total_items": total_items,
            "in_stock": in_stock,
            "low_stock": low_stock,
            "out_of_stock": out_of_stock,
        })

    @action(detail=False, methods=["POST"], url_path="adjust")
    def adjust_stock(self, request):
        if not self.is_admin_user(request):
            return Response({"detail": "Only admin can adjust stock."}, status=403)

        serializer = InventoryStockAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        owner_type = data["owner_type"]
        item_id = data["item"]
        action_type = data["action"]
        quantity = data["quantity"]
        reorder_level = data.get("reorder_level")

        shop_obj = None
        growtag_obj = None

        if owner_type == "shop":
            try:
                shop_obj = Shop.objects.get(id=data["shop"])
            except Shop.DoesNotExist:
                return Response({"detail": "Shop not found."}, status=404)

        elif owner_type == "growtag":
            try:
                growtag_obj = Growtags.objects.get(id=data["growtag"])
            except Growtags.DoesNotExist:
                return Response({"detail": "Growtag not found."}, status=404)

        with transaction.atomic():
            stock, created = InventoryStock.objects.select_for_update().get_or_create(
                owner_type=owner_type,
                shop=shop_obj,
                growtag=growtag_obj,
                item_id=item_id,
                defaults={
                    "qty_on_hand": Decimal("0.00"),
                    "reorder_level": reorder_level if reorder_level is not None else Decimal("5.00"),
                }
            )

            if reorder_level is not None:
                stock.reorder_level = reorder_level

            if action_type == "add":
                stock.qty_on_hand = stock.qty_on_hand + quantity

            elif action_type == "remove":
                if stock.qty_on_hand < quantity:
                    return Response(
                        {
                            "detail": "Insufficient stock.",
                            "available_qty": str(stock.qty_on_hand),
                            "requested_qty": str(quantity),
                        },
                        status=400,
                    )
                stock.qty_on_hand = stock.qty_on_hand - quantity

            stock.save()

        return Response(
            {
                "message": f"Stock {action_type} successful.",
                "created": created,
                "stock": InventoryStockSerializer(stock).data,
            },
            status=status.HTTP_200_OK,
        )
class StockLedgerViewSet(viewsets.ReadOnlyModelViewSet):
    
    authentication_classes = [UnifiedTokenAuthentication,JWTAuthentication,SessionAuthentication]
    permission_classes = [CrudByRole]
    queryset = StockLedger.objects.select_related("item", "shop", "growtag").all()
    serializer_class = StockLedgerSerializer
    role_perms = {
        "admin": {"GET"},
        "franchise": {"GET"},
        "othershop": {"GET"},
        "growtag": {"GET"},
    }


    def get_queryset(self):
        qs = super().get_queryset()

        if self.request.user.is_staff:
            group = self.request.query_params.get("group")  # franchise | othershop | growtag
            shop_id = self.request.query_params.get("shop_id")
            growtag_id = self.request.query_params.get("growtag_id")

            item_id = self.request.query_params.get("item")
            ref_type = self.request.query_params.get("ref_type")
            ref_id = self.request.query_params.get("ref_id")
            # ✅ Invalid combos (ADD HERE)
            if group == "growtag" and shop_id:
               return qs.none()
            if group in ("franchise", "othershop") and growtag_id:
               return qs.none()

            if group == "franchise":
                qs = qs.filter(owner_type="shop", shop__shop_type="franchise")
            elif group == "othershop":
                qs = qs.filter(owner_type="shop", shop__shop_type="othershop")
            elif group == "growtag":
                qs = qs.filter(owner_type="growtag")

            if shop_id:
                qs = qs.filter(owner_type="shop", shop_id=shop_id)
            if growtag_id:
                qs = qs.filter(owner_type="growtag", growtag_id=growtag_id)

            if item_id:
                qs = qs.filter(item_id=item_id)
            if ref_type:
                qs = qs.filter(ref_type=ref_type)
            if ref_id:
                qs = qs.filter(ref_id=ref_id)

            return qs

        return qs.none()
#password reset  api
from core.models import Customer, Shop, Growtags
def get_user_by_email(email):
    

    customer = Customer.objects.filter(email__iexact=email).first()
    if customer:
        return customer

    shop = Shop.objects.filter(email__iexact=email).first()
    if shop:
        return shop

    growtag = Growtags.objects.filter(email__iexact=email).first()
    if growtag:
        return growtag

    return None
class SendResetOTPAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")

        if not email:
            return Response({"detail": "email required"}, status=400)

        user = get_user_by_email(email)

        # do not reveal user existence
        if not user:
            return Response({"detail": "If account exists OTP sent"}, status=200)

        # delete old otp for this email
        PasswordResetOTP.objects.filter(email=email).delete()

        raw_otp = PasswordResetOTP.generate_otp()

        PasswordResetOTP.objects.create(
            email=email,
            otp_hash=make_password(raw_otp),
            expires_at=timezone.now() + timedelta(minutes=5)
        )

        send_mail(
            subject="Password Reset OTP",
            message=f"Your OTP is {raw_otp}",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )

        return Response({"detail": "OTP sent"}, status=200)
class VerifyResetOTPAPIView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get("email")
        otp = request.data.get("otp")
        new_password = request.data.get("new_password")
        confirm_password = request.data.get("confirm_password")

        if not email or not otp or not new_password or not confirm_password:
            return Response(
                {"detail": "email, otp, new_password, confirm_password required"},
                status=400
            )

        if new_password != confirm_password:
            return Response({"detail": "Passwords do not match"}, status=400)

        user = get_user_by_email(email)

        if not user:
            return Response({"detail": "Invalid OTP"}, status=400)

        otp_obj = PasswordResetOTP.objects.filter(email=email).first()

        if not otp_obj:
            return Response({"detail": "Invalid OTP"}, status=400)

        if otp_obj.is_expired():
            otp_obj.delete()
            return Response({"detail": "OTP expired"}, status=400)

        if not check_password(otp, otp_obj.otp_hash):
            return Response({"detail": "Invalid OTP"}, status=400)

        user.password = make_password(new_password)
        user.save()

        otp_obj.delete()

        return Response({"detail": "Password reset successful"}, status=200)
#growtag/shop popup viewset
# -----------------------------
# GET /api/growtags/<id>/
# -----------------------------
class GrowtagPopupViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only because you asked only for popup GET APIs.
    """
    queryset = Growtags.objects.all().order_by("-id")
    authentication_classes = [UnifiedTokenAuthentication,JWTAuthentication, SessionAuthentication]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"GET"},
        "franchise": {"GET"},
        "othershop": {"GET"},
        "growtag": {"GET"},
        "customer": set(),
    }

    serializer_class = GrowtagPopupSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Admin/staff -> all growtags
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # Growtag token -> only self
        if getattr(self.request, "growtag", None):
            return qs.filter(id=self.request.growtag.id)

        # Shop token -> only growtags mapped to this shop
        if getattr(self.request, "shop", None):
            growtag_ids = GrowTagAssignment.objects.filter(shop=self.request.shop)\
                .values_list("growtag_id", flat=True)
            return qs.filter(id__in=growtag_ids)

        return qs.none()
    def create(self, request, *args, **kwargs):
        # Get the role and actor (user/shop/growtag) from the request
        role, actor = get_actor(request)
    
        # Prepare audit data
        audit_data = {
        "created_on": timezone.now().date(),
         }
        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
        # Save with audit data
        GrowtagPopupSerializer.save(**audit_data)


# -----------------------------
# GET /api/shops/<id>/
# -----------------------------
class ShopPopupViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Shop.objects.all().order_by("-id")
    authentication_classes = [UnifiedTokenAuthentication,JWTAuthentication, SessionAuthentication]
    permission_classes = [CrudByRole]

    role_perms = {
        "admin": {"GET"},
        "franchise": {"GET"},
        "othershop": {"GET"},
        "growtag": {"GET"},
        "customer": set(),
    }

    serializer_class = ShopPopupSerializer

    def get_queryset(self):
        qs = super().get_queryset()

        # Admin/staff -> all shops
        if self.request.user and self.request.user.is_authenticated and self.request.user.is_staff:
            return qs

        # Shop token -> only self shop
        if getattr(self.request, "shop", None):
            return qs.filter(id=self.request.shop.id)

        # Growtag token -> shops mapped to this growtag
        if getattr(self.request, "growtag", None):
            return qs.filter(growtag_assignments__growtag=self.request.growtag).distinct()

        return qs.none()
        
    def create(self, request, *args, **kwargs):
        # Get the role and actor (user/shop/growtag) from the request
        role, actor = get_actor(request)
    
        # Prepare audit data
        audit_data = {
        "created_on": timezone.now().date(),
         }
        if role == "admin":
           audit_data["created_by_user"] = actor
        elif role in ("franchise", "othershop", "shop"):
            audit_data["created_by_shop"] = actor
        elif role == "growtag":
            audit_data["created_by_growtag"] = actor
        elif role == "customer":
            audit_data["created_by_customer"] = actor
    
        # Save with audit data
        ShopPopupSerializer.save(**audit_data)
