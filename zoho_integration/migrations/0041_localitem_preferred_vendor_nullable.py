from django.db import migrations


# The model and serializer already allow preferred_vendor to be empty.
# An older database column can still be NOT NULL, and migration 0036 does not
# change it because Django already considers the field nullable.
# This only relaxes that database constraint. Request and response stay the same.
DROP_NOT_NULL = """
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'zoho_integration_localitem'
          AND column_name = 'preferred_vendor'
          AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE zoho_integration_localitem
            ALTER COLUMN preferred_vendor DROP NOT NULL;
    END IF;

    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'zoho_integration_localitem'
          AND column_name = 'preferred_vendor_id'
          AND is_nullable = 'NO'
    ) THEN
        ALTER TABLE zoho_integration_localitem
            ALTER COLUMN preferred_vendor_id DROP NOT NULL;
    END IF;
END $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("zoho_integration", "0040_alter_localitem_hsn_or_sac"),
    ]

    operations = [
        migrations.RunSQL(DROP_NOT_NULL, migrations.RunSQL.noop),
    ]
