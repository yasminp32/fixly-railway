import logging
import requests

from celery import shared_task
from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail

from .models import Shop

logger = logging.getLogger(__name__)


@shared_task
def send_shop_created_email_task(shop_id, raw_password):
    try:
        shop = Shop.objects.get(id=shop_id)

        admin_emails = list(
            User.objects.filter(is_superuser=True)
            .exclude(email__isnull=True)
            .exclude(email="")
            .values_list("email", flat=True)
        )

        recipients = admin_emails
        if shop.email:
            recipients = [shop.email] + recipients

        recipients = list(dict.fromkeys(recipients))

        logger.info("EMAIL TASK STARTED for shop_id=%s", shop_id)
        logger.info("EMAIL RECIPIENTS for shop_id=%s: %s", shop_id, recipients)

        if not recipients:
            logger.warning("EMAIL TASK STOPPED: no recipients for shop_id=%s", shop_id)
            return "no recipients"

        send_mail(
            subject="New Shop Created",
            message=(
                "A new shop has been created.\n\n"
                f"Shop Name: {shop.shopname}\n"
                f"Owner: {shop.owner}\n"
                f"Phone: {shop.phone}\n"
                f"Login Password: {raw_password}\n\n"
                "Please change your password after first login."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            fail_silently=False,
        )

        logger.info("EMAIL SENT SUCCESSFULLY for shop_id=%s", shop_id)
        return "email sent"

    except Shop.DoesNotExist:
        logger.error("EMAIL TASK SHOP NOT FOUND: shop_id=%s", shop_id)
        return "shop not found"

    except Exception as e:
        logger.exception("EMAIL TASK ERROR for shop_id=%s: %s", shop_id, str(e))
        return f"error: {str(e)}"


@shared_task
def geocode_shop_task(shop_id):
    try:
        shop = Shop.objects.get(id=shop_id)

        query = ", ".join(
            [x for x in [shop.area, shop.state, shop.pincode, "India"] if x]
        )

        logger.info("GEOCODE TASK STARTED for shop_id=%s", shop_id)
        logger.info("GEOCODE QUERY for shop_id=%s: %s", shop_id, query)

        if not query:
            logger.warning("GEOCODE TASK STOPPED: empty query for shop_id=%s", shop_id)
            return "query empty"

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

        logger.info("GEOCODE STATUS CODE for shop_id=%s: %s", shop_id, response.status_code)
        response.raise_for_status()

        data = response.json()
        logger.info("GEOCODE RESPONSE for shop_id=%s: %s", shop_id, data)

        if data:
            shop.latitude = float(data[0]["lat"])
            shop.longitude = float(data[0]["lon"])
            shop.save(update_fields=["latitude", "longitude"])

            logger.info(
                "GEOCODE UPDATED shop_id=%s with lat=%s lon=%s",
                shop_id,
                shop.latitude,
                shop.longitude,
            )
            return "updated"

        logger.warning("GEOCODE NO RESULT for shop_id=%s", shop_id)
        return "no result"

    except Shop.DoesNotExist:
        logger.error("GEOCODE TASK SHOP NOT FOUND: shop_id=%s", shop_id)
        return "shop not found"

    except Exception as e:
        logger.exception("GEOCODE TASK ERROR for shop_id=%s: %s", shop_id, str(e))
        return f"error: {str(e)}"