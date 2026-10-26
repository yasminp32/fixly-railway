# core/audit.py
from typing import Optional
from core.models import Complaint


def admin_label(user) -> str:
    name = (
        getattr(user, "get_full_name", lambda: "")()
        or getattr(user, "username", "")
        or str(user)
    ).strip()
    return f"Admin - {name}" if name else "Admin"


def created_by_display(obj) -> Optional[str]:
    """
    Generic display helper for models that use AuditModel.created_by.
    Works only for admin/staff creators.
    """
    user = getattr(obj, "created_by", None)
    if user and (getattr(user, "is_staff", False) or getattr(user, "is_superuser", False)):
        return admin_label(user)
    return None


def complaint_created_by_display(obj: Complaint) -> Optional[str]:
    """
    Complaint-specific created_by display.
    Uses created_by_type because Complaint can be created by:
    admin / customer / franchise / othershop / growtag
    """
    created_by_type = getattr(obj, "created_by_type", None)

    if created_by_type == "admin":
        user = getattr(obj, "created_by", None)
        if user:
            return admin_label(user)
        return "Admin"

    if created_by_type == "customer":
        customer = getattr(obj, "customer", None)
        if customer:
            return f"Customer - {customer.customer_name}"
        if getattr(obj, "customer_name", None):
            return f"Customer - {obj.customer_name}"
        return "Customer"

    if created_by_type == "franchise":
        shop = getattr(obj, "assigned_shop", None)
        if shop:
            return f"Franchise - {shop.shopname}"
        return "Franchise"

    if created_by_type == "othershop":
        shop = getattr(obj, "assigned_shop", None)
        if shop:
            return f"Other Shop - {shop.shopname}"
        return "Other Shop"

    if created_by_type == "growtag":
        growtag = getattr(obj, "assigned_Growtags", None)
        if growtag:
            return f"Growtag - {growtag.name}"
        return "Growtag"

    return None


def get_actor(request):
    u = getattr(request, "user", None)
    if u and getattr(u, "is_authenticated", False) and getattr(u, "is_staff", False):
        return ("admin", u)

    if getattr(request, "shop", None):
        shop = request.shop
        return (shop.shop_type, shop)   # franchise / othershop

    if getattr(request, "growtag", None):
        return ("growtag", request.growtag)

    if getattr(request, "customer", None):
        return ("customer", request.customer)

    return (None, None)