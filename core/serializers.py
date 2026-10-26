from rest_framework import serializers
from .models import Shop, Growtags, Complaint,GrowTagAssignment,Customer
from rest_framework.validators import UniqueValidator
from django.contrib.auth.hashers import make_password
from django.conf import settings
from core.models import Customer
from core.models import Complaint
from core.models import Lead
from .models import Vendor
from core.models import InventoryStock, StockLedger
from django.db import transaction
from .models import PurchaseOrder, PurchaseOrderItem,PurchaseBill, PurchaseBillItem, PurchaseBillPayment
from core.stock_service import add_stock, reverse_stock_for_ref
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from django.contrib.auth.hashers import make_password
from .models import Shop
from decimal import Decimal
class CreatedBySerializerMixin(serializers.ModelSerializer):
    created_by_info = serializers.SerializerMethodField()

    def get_created_by_info(self, obj):
        if obj.created_by_user:
            return {
              "role": "admin",
               "id": obj.created_by_user.id,
               "name": obj.created_by_user.username,
               "email": obj.created_by_user.email,
            }

        if obj.created_by_shop:
            return {
               "role": "shop",
               "id": obj.created_by_shop.id,
               "name": obj.created_by_shop.shopname,
             }

        if obj.created_by_growtag:
            return {
                "role": "growtag",
                 "id": obj.created_by_growtag.id,
                "name": obj.created_by_growtag.name,
            }

        if obj.created_by_customer:
            return {
              "role": "customer",
              "id": obj.created_by_customer.id,
              "name": obj.created_by_customer.customer_name,
            }

        return None


class ShopSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=False,
        min_length=4
    )
    email = serializers.EmailField(
        required=True,
        validators=[
            UniqueValidator(
                queryset=Shop.objects.all(),
                message="This email is already registered to another shop."
            )
        ]
    )

    phone = serializers.CharField(
        required=True,
        validators=[
            UniqueValidator(
                queryset=Shop.objects.all(),
                message="This phone number is already registered to another shop."
            )
        ]
    )

    gst_pin = serializers.CharField(
        required=True,
        validators=[
            UniqueValidator(
                queryset=Shop.objects.all(),
                message="This GST number is already registered to another shop."
            )
        ]
    )

    class Meta:
        model = Shop
        fields = [
            "id",
            "shop_type",
            "shopname",
            "pincode",
            "phone",
            "owner",
            "address",
            "state",
            "email",
            "area",
            "gst_pin",
            "status",
            "latitude",
            "longitude",
            "password",
            "created_at",
            "updated_at",
            "created_on",
            "created_by_info",
           
        ]
        read_only_fields = [
            "created_at",
            "updated_at",
            "created_on",
            "created_by_info",
            
        ]
    
    def create(self, validated_data):
        raw_password = validated_data.pop("password", None)

        if raw_password:
            validated_data["password"] = make_password(raw_password)

        shop = super().create(validated_data)
        return shop

    def update(self, instance, validated_data):
        raw_password = validated_data.pop("password", None)

        if raw_password:
            instance.password = make_password(raw_password)

        return super().update(instance, validated_data)

    
class GrowtagsSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    password = serializers.CharField(
        required=False,
        allow_blank=False,
        min_length=4
    )

    grow_id = serializers.CharField(
          validators=[
            UniqueValidator(
                queryset=Growtags.objects.all(),
                message="This GrowTag ID is already in use."
            )
        ]
       )

    phone = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        validators=[
            UniqueValidator(
                queryset=Growtags.objects.all(),
                message="This phone number is already registered to another GrowTag."
            )
        ],
       )

    email = serializers.EmailField(
        validators=[
            UniqueValidator(
                queryset=Growtags.objects.all(),
                message="This email is already registered to another GrowTag."
            )
        ]
       )

    adhar = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        validators=[
            UniqueValidator(
                queryset=Growtags.objects.all(),
                message="This Aadhaar number is already registered to another GrowTag."
            )
        ],
    )

    class Meta:
        model = Growtags
        fields = [
            "id",
            "image",
            "grow_id",
            "name",
            "phone",
            "email",
            "password",
            "address",
            "state",
            "pincode",
            "area",
            "latitude",
            "longitude",
            "adhar",
            "status",
            "created_at",
            "updated_at",
            "created_on",
            "created_by_info",
        ]
        read_only_fields = ("created_at", "updated_at", "created_on","created_by_info","created_by_user",
           "created_by_shop","created_by_growtag","created_by_customer")

    def create(self, validated_data):
        raw_password = validated_data.pop("password", None)
        if raw_password:
            validated_data["password"] = make_password(raw_password)
        return super().create(validated_data)

    # ✅ UPDATE
    def update(self, instance, validated_data):
        raw_password = validated_data.pop("password", None)
        if raw_password:
            instance.password = make_password(raw_password)
        return super().update(instance, validated_data)
    
class ComplaintHistorySerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    """Lightweight complaint view for customer history."""
    invoice_created = serializers.SerializerMethodField()
    invoice_id = serializers.SerializerMethodField()
    assigned_to_display = serializers.SerializerMethodField()
    class Meta:
        model = Complaint
        fields = [
            "id",
            "phone_model",
            "issue_details",
            "status",
            "assign_to",
            "created_at",
            "invoice_created",
            "invoice_id",
            "assigned_to_display",
        ]
    
    def get_invoice_created(self, obj):
        # OneToOneField => exists or not
        return hasattr(obj, "invoice")

    def get_invoice_id(self, obj):
        return obj.invoice.id if hasattr(obj, "invoice") else None
    
    def get_assigned_to_display(self, obj):
        """
        Adjust field names here to match your Complaint model:
        - If you have obj.assigned_shop / obj.assigned_growtag use below.
        - If your fields are different, replace accordingly.
        """
        # ✅ if assigned to shop
        shop = getattr(obj, "assigned_shop", None) or getattr(obj, "shop", None)
        if shop:
            st = getattr(shop, "shop_type", None)
            st_name = getattr(st, "name", None) if st else None
            return {
                "assign_type": "shop",
                "shop_type": st_name,     # Franchise / Other Shop etc
                "id": shop.id,
                "name": getattr(shop, "shopname", None) or getattr(shop, "shop_name", None) or str(shop),
            }

        # ✅ if assigned to growtag
        growtag = getattr(obj, "assigned_growtag", None) or getattr(obj, "growtag", None)
        if growtag:
            return {
                "assign_type": "growtag",
                "id": growtag.id,
                "name": growtag.name,
            }

        return None

class CustomerSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True,
        required=False,
        min_length=4
    )
    customer_phone = serializers.CharField(
    validators=[
        UniqueValidator(
            queryset=Customer.objects.all(),
            message="This phone number is already registered to another customer."
        )
    ]
)

    email = serializers.EmailField(
         required=False,
         allow_null=True,
         validators=[
          UniqueValidator(
            queryset=Customer.objects.all(),
            message="This email is already registered to another customer."
        )
       ]
     )
     # 🔹 All complaints linked to this customer (via Complaint.customer FK, related_name="complaints")
    complaints_history = ComplaintHistorySerializer(
        source="complaints",  # uses related_name="complaints"
        many=True,
        read_only=True,
    )

    # 🔹 NEW: include all complaints of this customer
    #complaints = ComplaintSerializer(many=True, read_only=True)  # uses related_name="complaints"

    class Meta:
        model = Customer
        fields = [
            "id",
            "customer_name",
            "customer_phone",
            "email",
            "password",
            "address",
            "state",
            "pincode",
            "area",
            "complaints_history",
            "created_at",
            "updated_at",
            "created_on",
            "created_by_info",
        ]
        read_only_fields = ("created_at", "updated_at", "created_on", "created_by_info")
    def create(self, validated_data):
        raw_password = validated_data.pop("password", None)
        if raw_password:
            validated_data["password"] = make_password(raw_password)
        return super().create(validated_data)

    # ✅ UPDATE
    def update(self, instance, validated_data):
        raw_password = validated_data.pop("password", None)
        if raw_password:
            instance.password = make_password(raw_password)
        return super().update(instance, validated_data)
    
class CustomerBasicSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = [
            "id",
            "customer_name",
            "customer_phone",
            "email",
            "address",
            "state",  
            "pincode",
        ]


    
class ComplaintSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    invoice_created = serializers.SerializerMethodField()
    invoice_id = serializers.IntegerField(source="invoice.id", read_only=True)
    

    ASSIGN_CHOICES = ["franchise", "othershop", "growtag"]

    assign_to = serializers.ChoiceField(
        choices=ASSIGN_CHOICES,
        required=True
    )

    assigned_shop = serializers.PrimaryKeyRelatedField(
        queryset=Shop.objects.all(),
        required=False,
        allow_null=True
    )
    assigned_Growtags = serializers.PrimaryKeyRelatedField(
        queryset=Growtags.objects.all(),
        required=False,
        allow_null=True
    )

    assigned_to_details = serializers.SerializerMethodField(read_only=True)
    customer_details = CustomerBasicSerializer(source="customer", read_only=True)

    class Meta:
        model = Complaint
        fields = [
            "id",
            "customer",
            "customer_name",
            "customer_phone",
            "email",
            "password",
            "phone_model",
            "issue_details",
            "address",
            "state",
            "pincode",
            "area",
            "assign_to",
            "latitude",
            "longitude",
            "status",
            "confirm_status",
            "confirmed_by",
            "confirmed_at",
            "created_at",
            "assigned_shop",
            "assigned_Growtags",
            "assigned_to_details",
            "customer_details",
            "created_by_info",
            "invoice_created",
            "invoice_id",
        ]
        read_only_fields = (
            "updated_at",
            "created_on",
            "customer",
            "created_by_info",
        )

    def validate(self, attrs):
        assign_to = attrs.get("assign_to", getattr(self.instance, "assign_to", None))
        assigned_shop = attrs.get("assigned_shop", getattr(self.instance, "assigned_shop", None))
        assigned_growtag = attrs.get("assigned_Growtags", getattr(self.instance, "assigned_Growtags", None))

        if assign_to == "growtag":
            if assigned_shop:
                raise serializers.ValidationError({
                    "assigned_shop": "Do not send assigned_shop when assign_to is growtag."
                })
            if not assigned_growtag:
                raise serializers.ValidationError({
                    "assigned_Growtags": "Please select a growtag."
                })

        elif assign_to in ["franchise", "othershop"]:
            if assigned_growtag:
                raise serializers.ValidationError({
                    "assigned_Growtags": "Do not send assigned_Growtags when assign_to is franchise/othershop."
                })
            if not assigned_shop:
                raise serializers.ValidationError({
                    "assigned_shop": "Please select a shop."
                })

            # optional type validation if shop_type field exists
            if hasattr(assigned_shop, "shop_type") and assigned_shop.shop_type != assign_to:
                raise serializers.ValidationError({
                    "assigned_shop": f"Selected shop must be of type '{assign_to}'."
                })

        return attrs

    def get_assigned_to_details(self, obj):
        if obj.assign_to == "growtag" and obj.assigned_Growtags:
            gt = obj.assigned_Growtags
            return {
                "type": "growtag",
                "id": gt.id,
                "name": getattr(gt, "name", None),
            }

        if obj.assign_to in ["franchise", "othershop"] and obj.assigned_shop:
            shop = obj.assigned_shop
            return {
                "type": obj.assign_to,
                "id": shop.id,
                "name": getattr(shop, "shopname", None),
            }

        return None

    def get_invoice_created(self, obj):
        return hasattr(obj, "invoice") and obj.invoice is not None

class GrowTagAssignmentSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    grow_id = serializers.CharField(source="growtag.grow_id", read_only=True)
    name = serializers.CharField(source="growtag.name", read_only=True)
    shop_name = serializers.CharField(source="shop.shopname", read_only=True)
    shop_type = serializers.CharField(source="shop.shop_type", read_only=True)

    # inputs from two dropdowns
    franchise_shop_id = serializers.IntegerField(write_only=True, required=False)
    othershop_shop_id = serializers.IntegerField(write_only=True, required=False)

    class Meta:
        model = GrowTagAssignment
        fields = [
            "id",
            "growtag",
            "shop",
            "grow_id",
            "name",
            "shop_name",
            "shop_type",
            "assigned_at",
            "franchise_shop_id",
            "othershop_shop_id",
            "created_by_info",
        ]
        read_only_fields = ["shop", "assigned_at","created_at", "updated_at", "created_on", "created_by_info",]
        
    def validate(self, attrs):
        f_id = attrs.get("franchise_shop_id")
        o_id = attrs.get("othershop_shop_id")

        if not f_id and not o_id:
            raise serializers.ValidationError("Select either Franchise shop or Other Shop.")

        if f_id and o_id:
            raise serializers.ValidationError("Select only one shop type (not both).")

        return attrs
    def create(self, validated_data):
        # extract dropdown IDs
        f_id = validated_data.pop("franchise_shop_id", None)
        o_id = validated_data.pop("othershop_shop_id", None)

        # convert selected ID → actual shop object
        shop_id = f_id or o_id

        try:
            shop = Shop.objects.get(id=shop_id)
        except Shop.DoesNotExist:
            raise serializers.ValidationError({"shop": "Invalid shop selected. Please select a valid shop from the dropdown."})

        validated_data["shop"] = shop

        return GrowTagAssignment.objects.create(**validated_data)
    

       #assigned compliant view


class ComplaintMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Complaint
        fields = [
            "id",
            "customer_name",
            "customer_phone",
            "phone_model",
            "issue_details",
            "status",
            "created_at",
        ]
    

class ShopViewSerializer(serializers.ModelSerializer):
    assigned_complaints = serializers.SerializerMethodField()
    assigned_complaints_count = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = [
            "id",
            "shop_type",
            "shopname",
            "owner",
            "email",
            "phone",
            "address",
            "area",
            "pincode",
            "gst_pin",
            "status",
            "latitude",
            "longitude",
            "assigned_complaints_count",
            "assigned_complaints",
        ]

    def get_assigned_complaints(self, obj):
        qs = Complaint.objects.filter(
        assigned_shop=obj,
        assign_to__in=["franchise", "othershop"],
        ).order_by("-created_at")
        return ComplaintMiniSerializer(qs, many=True).data

    def get_assigned_complaints_count(self, obj):
        return Complaint.objects.filter(
            assigned_shop=obj,
            assign_to__in=["franchise", "othershop"],
        ).count()


class GrowtagViewSerializer(serializers.ModelSerializer):
    assigned_complaints = serializers.SerializerMethodField()
    assigned_complaints_count = serializers.SerializerMethodField()

    class Meta:
        model = Growtags
        fields = [
            "id",
            "name",
            "phone",
            "email",
            "address",
            "area",
            "pincode",
            "status",
            "assigned_complaints_count",
            "assigned_complaints",
        ]

    def get_assigned_complaints(self, obj):
        qs = Complaint.objects.filter(
            assigned_Growtags=obj,
            assign_to="growtag",
        ).order_by("-created_at")
        return ComplaintMiniSerializer(qs, many=True).data

    def get_assigned_complaints_count(self, obj):
        return Complaint.objects.filter(
            assigned_Growtags=obj,
            assign_to="growtag",
        ).count()
    
#public customer
class CustomerRegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = Customer
        fields = [
            "id",
            "customer_name",
            "customer_phone",
            "email",
            "password",
            "confirm_password",
            "address",      
            "state",        
            "pincode", 
        ]
    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match"})
        return attrs
    def create(self, validated_data):
        validated_data.pop("confirm_password")
        raw_password = validated_data.pop("password")
        customer = Customer(**validated_data)
        customer.password = make_password(raw_password)  # ✅ hash
        customer.save()
        return customer


class CustomerLoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()
class PublicComplaintSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    assigned_to_details = serializers.SerializerMethodField(read_only=True)

    ASSIGN_CHOICES = [
        ("franchise", "Franchise"),
        ("othershop", "Other Shop"),
        ("growtag", "GrowTag"),
    ]
    assign_to = serializers.ChoiceField(choices=ASSIGN_CHOICES, required=True)

    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    address_line = serializers.CharField(source="address", required=True, allow_blank=False)
    pincode = serializers.CharField(required=True)
    area = serializers.CharField(required=True)
    state = serializers.CharField(required=True)

    assigned_shop = serializers.PrimaryKeyRelatedField(
        queryset=Shop.objects.all(),
        required=False,
        allow_null=True
    )
    assigned_Growtags = serializers.PrimaryKeyRelatedField(
        queryset=Growtags.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = Complaint
        fields = [
            "id",
            "customer_name",
            "customer_phone",
            "email",
            "phone_model",
            "address_line",
            "pincode",
            "area",
            "state",
            "issue_details",
            "assign_to",
            "status",
            "created_at",
            "assigned_shop",
            "assigned_Growtags",
            "assigned_to_details",
            "created_by_info",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_at",
            "assigned_to_details",
            "created_by_info",
        ]

    def validate(self, attrs):
        email = (attrs.get("email") or "").strip()
        if email == "":
            attrs["email"] = None

        if not (attrs.get("customer_name") or "").strip():
            raise serializers.ValidationError({"customer_name": "Customer Name is required."})

        if not (attrs.get("customer_phone") or "").strip():
            raise serializers.ValidationError({"customer_phone": "Mobile Number is required."})

        if not (attrs.get("address") or "").strip():
            raise serializers.ValidationError({"address_line": "Address Line is required."})

        if not (attrs.get("pincode") or "").strip():
            raise serializers.ValidationError({"pincode": "Pincode is required."})

        if not (attrs.get("area") or "").strip():
            raise serializers.ValidationError({"area": "Area is required."})

        if not (attrs.get("state") or "").strip():
            raise serializers.ValidationError({"state": "State is required."})

        assign_to = attrs.get("assign_to", getattr(self.instance, "assign_to", None))
        assigned_shop = attrs.get("assigned_shop", getattr(self.instance, "assigned_shop", None))
        assigned_growtag = attrs.get("assigned_Growtags", getattr(self.instance, "assigned_Growtags", None))

        if assign_to == "growtag":
            if not assigned_growtag:
                raise serializers.ValidationError({
                    "assigned_Growtags": "Please select a growtag."
                })
            attrs["assigned_shop"] = None

        elif assign_to in ["franchise", "othershop"]:
            if not assigned_shop:
                raise serializers.ValidationError({
                    "assigned_shop": "Please select a shop."
                })
            attrs["assigned_Growtags"] = None

        return attrs

    def get_assigned_to_details(self, obj):
        if obj.assign_to == "growtag" and obj.assigned_Growtags:
            gt = obj.assigned_Growtags
            return {
                "type": "growtag",
                "id": gt.id,
                "name": getattr(gt, "name", None),
            }

        if obj.assign_to in ["franchise", "othershop"] and obj.assigned_shop:
            shop = obj.assigned_shop
            return {
                "type": obj.assign_to,
                "id": shop.id,
                "name": getattr(shop, "shopname", None),
            }

        return None
#lead serializer
class LeadSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):    
    class Meta:
        model = Lead
        fields = [
            "id",
            "created_at",
            "updated_at",
            "created_on",
            "lead_code",
            "customer_name",
            "customer_phone",
            "email",
            "phone_model",
            "issue_detail",
            "address",
            "area",
            "state",
            "pincode",
            "status",
            "source",
            "salesiq_visitor_id",
            "raw_payload",
            "complaint",
            "assigned_shop",
            "assigned_growtag",
            "created_by_info",
        ]
        read_only_fields = ["id", "lead_code", "created_at", "updated_at","created_by_info",]
    
#vendor

class VendorSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ["id", "name", "email", "phone","gst_pin", "address", "website", "status", "created_at","created_by_info",]
        read_only_fields = ["id", "created_at","shop","created_by_info",]

    def validate(self, data):
        # For CREATE: enforce required fields (like popup required labels)
        if self.instance is None:
            required_fields = ["name", "email", "phone", "address"]
            for field in required_fields:
                if not data.get(field):
                    raise serializers.ValidationError({field: "This field is required"})
        return data
    
#puchase order

from .utils import generate_po_number, recompute_purchase_order_totals
class VendorMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ["id", "name", "email", "phone", "address"]


class PurchaseOrderItemSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    item_id = serializers.IntegerField(source="item.id", read_only=True)
    item_name_master = serializers.CharField(source="item.name", read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = [
            "id",
            "item",          # (optional) pk input/update
            "item_id", 
            "item_name_master", 
            "item_name",
            "description",
            "qty",
            "unit_price",
            "tax_percent",
            "discount_percent",
            "line_subtotal",
            "discount_amount",
            "tax_amount",
            "line_total",
            "created_by_info",
        ]
        read_only_fields = [
            "purchase_order","line_subtotal", "discount_amount", "tax_amount", "line_total","item_name_master","created_by_info",
        ]
    def validate(self, attrs):
        # basic numeric validation (optional)
        qty = attrs.get("qty", None)
        unit_price = attrs.get("unit_price", None)
        if qty is not None and qty <= 0:
            raise serializers.ValidationError({"qty": "qty must be > 0"})
        if unit_price is not None and unit_price < 0:
            raise serializers.ValidationError({"unit_price": "unit_price must be >= 0"})
        return attrs


class PurchaseOrderSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    vendor_details = VendorMiniSerializer(source="vendor", read_only=True)
    items = PurchaseOrderItemSerializer(many=True)
    pdf_url = serializers.SerializerMethodField()
    assigned_shop = serializers.IntegerField(source="shop.id", read_only=True)
    assigned_shop_name = serializers.CharField(source="shop.shopname", read_only=True)
    assigned_shop_type = serializers.CharField(source="shop.shop_type", read_only=True)
    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "created_at",
            "updated_at",
            "created_on",
            "po_number",
            "assigned_shop_type",
            "assigned_shop",
            "assigned_shop_name",   # ✅ add this
            "shop",            # optional, only if you also use it directly
            "po_date",
            "expected_delivery_date",
            "status",
            "vendor",
            "vendor_details",
            "ship_to",
            "bill_to",
            "subtotal",
            "total_discount",
            "total_tax",
            "shipping_charges",
            "adjustment",
            "grand_total",
            "terms_and_conditions",
            "notes",
            "items",
            "pdf_url",
            "created_by_info",
        ]
        read_only_fields = ["po_number", "subtotal", "total_discount", "total_tax", "grand_total","created_by_info",]
    def get_pdf_url(self, obj):
        request = self.context.get("request")
        if request:
           return request.build_absolute_uri(f"/purchase-orders/{obj.pk}/pdf/")
        return f"/purchase-orders/{obj.pk}/pdf/"
    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items")
        #validated_data["po_number"] = generate_po_number()

        po = PurchaseOrder.objects.create(**validated_data)

        for item in items_data:
            item_audit_data = {}

            if po.created_by_user:
               item_audit_data["created_by_user"] = po.created_by_user
            elif po.created_by_shop:
                 item_audit_data["created_by_shop"] = po.created_by_shop
            elif po.created_by_growtag:
                item_audit_data["created_by_growtag"] = po.created_by_growtag
            elif po.created_by_customer:
                 item_audit_data["created_by_customer"] = po.created_by_customer

            PurchaseOrderItem.objects.create(
               purchase_order=po,
               **item,
               **item_audit_data
            )

        recompute_purchase_order_totals(po)
        po.refresh_from_db()   # 🔹 recommended

        return po
    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        old_status = instance.status
        new_status = validated_data.get("status", instance.status)

        # 🚫 Block item edits when PO is OPEN
        if (
             old_status in ("SENT", "RECEIVED", "CANCELLED")
             and items_data is not None
        ):
            raise serializers.ValidationError(
              "Cannot edit items when Purchase Order is Sent / Received / Cancelled."
            )


        # update PO fields
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()

        # replace items if provided
        if items_data is not None:
            instance.items.all().delete()
            for item in items_data:
                PurchaseOrderItem.objects.create(purchase_order=instance, **item)

        recompute_purchase_order_totals(instance)
        instance.refresh_from_db()
        return instance
class PurchaseOrderListSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    assigned_shop = serializers.IntegerField(source="shop.id", read_only=True)
    assigned_shop_name = serializers.CharField(source="shop.shopname", read_only=True)
    assigned_shop_type = serializers.CharField(source="shop.shop_type", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    class Meta:
        model = PurchaseOrder
        fields = [
            "id",
            "po_number",
             "assigned_shop",
            "assigned_shop_name",
            "assigned_shop_type",
            "vendor_name",
            "po_date",
            "expected_delivery_date",
            "status",
            "grand_total",
             "pdf_url",
             "created_by_info",
        ]
    def get_pdf_url(self, obj):
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(f"/purchase-orders/{obj.pk}/pdf/")
        return f"/purchase-orders/{obj.pk}/pdf/"  
#bills
class PurchaseBillItemSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    item_id = serializers.IntegerField(source="item.id", read_only=True)
    item_name_master = serializers.CharField(source="item.name", read_only=True)

    class Meta:
        model = PurchaseBillItem
        fields = [
            "id", "item", "item_id",     # ✅ LocalItem id
            "item_name_master","name", "description", "account",
            "qty", "rate", "tax_percent", "discount_percent",
            "line_subtotal", "discount_amount", "tax_amount", "amount","created_by_info",
        ]
        read_only_fields = ["line_subtotal", "discount_amount", "tax_amount", "amount","item_id", "item_name_master","created_by_info",]


class PurchaseBillPaymentSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    class Meta:
        model = PurchaseBillPayment
        fields = ["id", "payment_date", "amount", "method", "reference", "created_at","created_by_info",]
        read_only_fields = ["created_at","created_by_info",]


class PurchaseBillListSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    pdf_url = serializers.SerializerMethodField()
    class Meta:
        model = PurchaseBill
        fields = [
            "id", "bill_number", "vendor_name", "bill_date", "due_date",
            "status", "payment_status",
            "amount_paid", "total", "balance_due","pdf_url",
            "created_at","created_by_info",
        ]
    def get_pdf_url(self, obj):
        request = self.context.get("request")
        url = f"/purchase-bills/{obj.id}/pdf/"
        return request.build_absolute_uri(url) if request else url

class PurchaseBillCreateUpdateSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    items = PurchaseBillItemSerializer(many=True)
    payments = PurchaseBillPaymentSerializer(many=True, required=False)
    assigned_shop = serializers.IntegerField(source="shop.id", read_only=True)
    assigned_shop_name = serializers.CharField(source="shop.shopname", read_only=True)
    assigned_shop_type = serializers.CharField(source="shop.shop_type", read_only=True)
    pdf_url = serializers.SerializerMethodField()
    class Meta:
        model = PurchaseBill
        fields = [
            "id",
            "owner_type", "shop", "growtag",
            "vendor",
            "bill_number",
            "order_number",
            "bill_date",
            "due_date",
            "status",
            "payment_status",
           # "payment_terms",
              "assigned_shop",
            "assigned_shop_name",
            "assigned_shop_type",
            "vendor_name", "vendor_email", "vendor_phone", "vendor_gstin", "vendor_address",

            "ship_to", "bill_to",

            "tds_percent", "shipping_charges", "adjustment",

            "subtotal", "total_discount", "total_tax", "tds_amount",
            "total", "amount_paid", "balance_due",

            "notes", "terms_and_conditions",
            "items", "payments","pdf_url",
            "created_at",
            "created_by_info",
        ]
        read_only_fields = [
            "vendor_name","vendor_email","vendor_phone","vendor_gstin","vendor_address",
            "subtotal","total_discount","total_tax","tds_amount","total","amount_paid","balance_due",
            "created_at","created_by_info",
        ]
    def get_pdf_url(self, obj):
        request = self.context.get("request")
        url = f"/purchase-bills/{obj.id}/pdf/"
        return request.build_absolute_uri(url) if request else url
    def validate(self, attrs):
        """
        ✅ Ensure owner rules:
        - owner_type=shop => shop required, growtag must be null
        - owner_type=growtag => growtag required, shop must be null
        """
        owner_type = attrs.get("owner_type") or getattr(self.instance, "owner_type", None)
        shop = attrs.get("shop") if "shop" in attrs else getattr(self.instance, "shop", None)
        growtag = attrs.get("growtag") if "growtag" in attrs else getattr(self.instance, "growtag", None)

        if owner_type == "shop":
            if not shop or growtag:
                raise serializers.ValidationError("owner_type='shop' requires shop and growtag must be null.")
        elif owner_type == "growtag":
            if not growtag or shop:
                raise serializers.ValidationError("owner_type='growtag' requires growtag and shop must be null.")
        else:
            raise serializers.ValidationError("owner_type must be 'shop' or 'growtag'.")

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        payments_data = validated_data.pop("payments", [])

        bill = PurchaseBill.objects.create(**validated_data)

        for it in items_data:
            PurchaseBillItem.objects.create(bill=bill, **it)

        for p in payments_data:
            PurchaseBillPayment.objects.create(bill=bill, **p)

        bill.recalc_totals()

        # ✅ Add stock only if bill is OPEN
        if bill.status == "OPEN":
            self._apply_stock_increase(bill)

        return bill

    @transaction.atomic
    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        payments_data = validated_data.pop("payments", None)

        old_status = instance.status

        # update main fields
        for k, v in validated_data.items():
            setattr(instance, k, v)
        instance.save()

        # update items
        if items_data is not None:
            instance.items.all().delete()
            for it in items_data:
                PurchaseBillItem.objects.create(bill=instance, **it)

        # update payments
        if payments_data is not None:
            #instance.payments.all().delete()
            for p in payments_data:
                PurchaseBillPayment.objects.create(bill=instance, **p)

        instance.recalc_totals()

        # ✅ Apply stock when status changes DRAFT -> OPEN
        if old_status != "OPEN" and instance.status == "OPEN":
            self._apply_stock_increase(instance)

        # ✅ Optional: reverse stock when OPEN -> CANCELLED
        # (Only enable if you want cancellation to rollback stock)
        if old_status == "OPEN" and instance.status == "CANCELLED":
            reverse_stock_for_ref(
                owner_type=instance.owner_type,
                shop=instance.shop if instance.owner_type == "shop" else None,
                growtag=instance.growtag if instance.owner_type == "growtag" else None,
                ref_type="PURCHASE_BILL",
                ref_id=instance.id,
            )

        return instance

    def _apply_stock_increase(self, bill: PurchaseBill):
        owner_type = bill.owner_type

        for it in bill.items.all():
            if not it.item_id:
                continue  # skip non-linked items if allowed

            add_stock(
                owner_type=owner_type,
                shop=bill.shop if owner_type == "shop" else None,
                growtag=bill.growtag if owner_type == "growtag" else None,
                item=it.item,
                qty=it.qty,
                ref_type="PURCHASE_BILL",
                ref_id=bill.id,
                note=f"Stock added from PurchaseBill {bill.bill_number}",
            )
#stock
class InventoryStockSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_sku = serializers.CharField(source="item.sku", read_only=True)

    shop_name = serializers.CharField(source="shop.shopname", read_only=True)
    shop_type = serializers.CharField(source="shop.shop_type", read_only=True)

    growtag_name = serializers.CharField(source="growtag.name", read_only=True)
    growtag_status = serializers.CharField(source="growtag.status", read_only=True)
    stock_status = serializers.CharField(read_only=True)
    class Meta:
        model = InventoryStock
        fields = [
            "id",
            "owner_type",

            "shop", "shop_name", "shop_type",
            "growtag", "growtag_name", "growtag_status",

            "item", "item_name", "item_sku",
            "qty_on_hand",
            "reorder_level",
            "stock_status",
            "updated_at",
            
        ]
        read_only_fields = ["qty_on_hand", "updated_at","stock_status","created_by",]
class InventoryStockAdjustSerializer(serializers.Serializer):
    owner_type = serializers.ChoiceField(choices=["shop", "growtag"])
    shop = serializers.IntegerField(required=False)
    growtag = serializers.IntegerField(required=False)
    item = serializers.IntegerField()
    action = serializers.ChoiceField(choices=["add", "remove"])
    quantity = serializers.DecimalField(max_digits=12, decimal_places=2)
    reorder_level = serializers.DecimalField(
        max_digits=12, decimal_places=2, required=False
    )

    def validate(self, attrs):
        owner_type = attrs.get("owner_type")
        shop = attrs.get("shop")
        growtag = attrs.get("growtag")
        quantity = attrs.get("quantity")

        if quantity is None or quantity <= 0:
            raise serializers.ValidationError({"quantity": "Quantity must be greater than 0."})

        if owner_type == "shop":
            if not shop:
                raise serializers.ValidationError({"shop": "shop is required when owner_type='shop'."})
            if growtag:
                raise serializers.ValidationError({"growtag": "growtag must be empty when owner_type='shop'."})

        if owner_type == "growtag":
            if not growtag:
                raise serializers.ValidationError({"growtag": "growtag is required when owner_type='growtag'."})
            if shop:
                raise serializers.ValidationError({"shop": "shop must be empty when owner_type='growtag'."})

        return attrs

class StockLedgerSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source="item.name", read_only=True)
    item_sku = serializers.CharField(source="item.sku", read_only=True)

    class Meta:
        model = StockLedger
        fields = [
            "id",
            "owner_type",
            "shop",
            "growtag",
            "item",
            "item_name",
            "item_sku",
            "qty_change",
            "balance_after",
            "ref_type",
            "ref_id",
            "note",
            "created_at",
        ]
# To view growtag and shop popup

# -----------------------------
# Complaint card (for popups)
# -----------------------------
class PopupComplaintSerializer(serializers.ModelSerializer):
    complaint_id = serializers.SerializerMethodField()
    title = serializers.SerializerMethodField()
    created_on = serializers.SerializerMethodField()
    created_at_time = serializers.SerializerMethodField()
    updated_at_time = serializers.SerializerMethodField()
    customer_name = serializers.SerializerMethodField()
    shop_name = serializers.SerializerMethodField()
    class Meta:
        model = Complaint
        fields = [
            "id",
            "complaint_id",
            "title",
            "area",
            "pincode",
            "status",
            "confirm_status",
            "assign_to",
            "shop_name",
            "customer_name",
            "created_on",
            "created_at_time",
            "updated_at_time",
        ]

    def get_complaint_id(self, obj):
        return f"COMP{obj.id:03d}"  # COMP001 format

    def get_title(self, obj):
        return (obj.issue_details or "N/A")[:60]
    def get_customer_name(self, obj):
        if getattr(obj, "customer_name", None):
            return obj.customer_name

        if getattr(obj, "customer", None):
            return getattr(obj.customer, "name", None) or getattr(obj.customer, "full_name", None)

        return None

    def get_shop_name(self, obj):
        # 1. direct assigned shop on complaint
        if getattr(obj, "assigned_shop", None):
            return getattr(obj.assigned_shop, "shopname", None)

        # 2. fallback from growtag assignment
        if getattr(obj, "assigned_Growtags", None):
            assignment = getattr(obj.assigned_Growtags, "assignment", None)
            if assignment and getattr(assignment, "shop", None):
               return getattr(assignment.shop, "shopname", None)

        return None
        

    def get_created_on(self, obj):
        return obj.created_at.strftime("%d/%m/%Y") if getattr(obj, "created_at", None) else None

    def get_created_at_time(self, obj):
        return obj.created_at.strftime("%d/%m/%Y, %H:%M:%S") if getattr(obj, "created_at", None) else None

    def get_updated_at_time(self, obj):
        return obj.updated_at.strftime("%d/%m/%Y, %H:%M:%S") if getattr(obj, "updated_at", None) else None


# -----------------------------
# Mini shop (inside growtag popup)
# -----------------------------
class ShopMiniSerializer(serializers.ModelSerializer):
    shop_type_display = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = [
            "id",
            "shop_type",
            "shop_type_display",
            "shopname",
            "phone",
            "email",
            "owner",
            "area",
            "pincode",
            "address",
            "state",
            "gst_pin",
            "status",
            "latitude",
            "longitude",
        ]

    def get_shop_type_display(self, obj):
        return dict(Shop.SHOP_TYPE_CHOICES).get(obj.shop_type, obj.shop_type)


# -----------------------------
# Mini growtag (inside shop popup)
# -----------------------------
class GrowtagMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = Growtags
        fields = [
            "id",
            "grow_id",
            "name",
            "phone",
            "email",
            "area",
            "pincode",
            "status",
            "image",
            "latitude",
            "longitude",
        ]


# -----------------------------
# Growtag popup serializer
# GET /api/growtags/<id>/
# -----------------------------
class GrowtagPopupSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    assigned_shop = serializers.SerializerMethodField()
    assigned_complaints_count = serializers.SerializerMethodField()
    assigned_complaints = serializers.SerializerMethodField()

    class Meta:
        model = Growtags
        fields = [
            "id",
            "grow_id",
            "name",
            "phone",
            "email",
            "address",
            
            "state",
            "pincode",
            "area",
            "latitude",
            "longitude",
            "adhar",
            "status",
            "image",
            "assigned_shop",
            "assigned_complaints_count",
            "assigned_complaints",
            "created_by_info",
        ]

    def get_assigned_shop(self, obj):
        # related_name="assignment" (OneToOne)
        assignment = getattr(obj, "assignment", None)
        if not assignment:
            return None
        return ShopMiniSerializer(assignment.shop).data

    def get_assigned_complaints_count(self, obj):
        return Complaint.objects.filter(assigned_Growtags=obj).count()

    def get_assigned_complaints(self, obj):
        qs = Complaint.objects.filter(assigned_Growtags=obj)\
        .select_related("assigned_shop", "assigned_Growtags", "customer", "assigned_Growtags__assignment__shop")\
        .order_by("-id")[:50]
        return PopupComplaintSerializer(qs, many=True).data


# -----------------------------
# Shop popup serializer
# GET /api/shops/<id>/
# -----------------------------
class ShopPopupSerializer(CreatedBySerializerMixin,serializers.ModelSerializer):
    shop_type_display = serializers.SerializerMethodField()

    assigned_growtags_count = serializers.SerializerMethodField()
    assigned_growtags = serializers.SerializerMethodField()

    assigned_complaints_count = serializers.SerializerMethodField()
    assigned_complaints = serializers.SerializerMethodField()

    class Meta:
        model = Shop
        fields = [
            "id",
            "shop_type",
            "shop_type_display",
            "shopname",
            "phone",
            "email",
            "owner",
            "area",
            "pincode",
            "address",
            "state",
            "gst_pin",
            "status",
            "latitude",
            "longitude",
            "assigned_growtags_count",
            "assigned_growtags",
            "assigned_complaints_count",
            "assigned_complaints",
            "created_by_info",
        ]

    def get_shop_type_display(self, obj):
        return dict(Shop.SHOP_TYPE_CHOICES).get(obj.shop_type, obj.shop_type)

    def get_assigned_growtags_count(self, obj):
        return GrowTagAssignment.objects.filter(shop=obj).count()

    def get_assigned_growtags(self, obj):
        qs = GrowTagAssignment.objects.filter(shop=obj).select_related("growtag").order_by("-id")[:50]
        growtags = [x.growtag for x in qs]
        return GrowtagMiniSerializer(growtags, many=True).data

    def get_assigned_complaints_count(self, obj):
        return Complaint.objects.filter(assigned_shop=obj).count()

    def get_assigned_complaints(self, obj):
        qs = Complaint.objects.filter(assigned_shop=obj).order_by("-id")[:50]
        return PopupComplaintSerializer(qs, many=True).data
