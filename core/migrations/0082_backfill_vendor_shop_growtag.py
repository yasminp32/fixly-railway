# Generated manually — ties legacy vendors to the shop/growtag that created them
from django.db import migrations
from django.db.models import F


def backfill_vendor_owners(apps, schema_editor):
    Vendor = apps.get_model("core", "Vendor")
    Vendor.objects.filter(shop__isnull=True, created_by_shop_id__isnull=False).update(
        shop_id=F("created_by_shop_id")
    )
    Vendor.objects.filter(growtag__isnull=True, created_by_growtag_id__isnull=False).update(
        growtag_id=F("created_by_growtag_id")
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0081_auto_20260330_0339"),
    ]

    operations = [
        migrations.RunPython(backfill_vendor_owners, noop_reverse),
    ]
