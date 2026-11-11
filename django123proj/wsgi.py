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
        from main.models import ComboOffer, ComboBundleItem, Product
        combo, _ = ComboOffer.objects.get_or_create(
            name="Cans of Assortment",
            defaults={
                "offer_type": "bundle",
                "discount_type": "percentage",
                "discount_value": Decimal("15.00"),
                "max_discount_cap": Decimal("100.00"),
                "image": "combos/cans_of_assortment.png",
                "description": "Mix & match our 6 handcrafted flavours to unlock the Cans of Assortment combo bundle with 15% instant discount!",
                "is_active": True,
            },
        )
        if combo and not combo.bundle_items.exists():
            for prod in Product.objects.filter(available=True).order_by("id")[:6]:
                ComboBundleItem.objects.get_or_create(combo_offer=combo, product=prod, defaults={"quantity": 1})
    except Exception as exc:
        import logging
        logging.getLogger("django").warning("Vercel auto-migration warning: %s", exc)
