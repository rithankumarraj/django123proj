"""
WSGI config for django123proj project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django123proj.settings')

application = get_wsgi_application()

if os.environ.get("VERCEL") == "1":
    try:
        from django.core.management import call_command
        call_command("migrate", interactive=False)
        from decimal import Decimal
        from main.models import ComboOffer
        ComboOffer.objects.get_or_create(
            name="Cans of Assortment",
            defaults={
                "offer_type": "multiple_products",
                "discount_type": "percentage",
                "discount_value": Decimal("15.00"),
                "max_discount_cap": Decimal("100.00"),
                "min_order_amount": Decimal("6.00"),
                "min_quantity": 6,
                "min_distinct_products": 6,
                "badge_text": "Cans of Assortment",
                "image": "combos/cans_of_assortment.jpg",
                "description": "Mix & match any 6 different cans to unlock the Cans of Assortment combo offer with 15% instant discount!",
                "is_active": True,
            },
        )
    except Exception as exc:
        import logging
        logging.getLogger("django").warning("Vercel auto-migration warning: %s", exc)
