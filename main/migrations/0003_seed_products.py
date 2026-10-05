from django.db import migrations


PRODUCTS = [
    {
        "name": "Classic Cola",
        "description": "Deep, familiar cola flavour with a clean, refreshing finish.",
        "image": "main/images/cola.png",
    },
    {
        "name": "Bubblegum",
        "description": "Bright, playful sweetness made for an easy everyday refresh.",
        "image": "main/images/bubblegum.png",
    },
    {
        "name": "Fresh Lime",
        "description": "Crisp lime flavour with a sharp, refreshing lift.",
        "image": "main/images/lime.png",
    },
    {
        "name": "Energy Drink",
        "description": "Bold energy flavour for whenever you want to keep moving.",
        "image": "main/images/energydrink.png",
    },
]


def seed_products(apps, schema_editor):
    Product = apps.get_model("main", "Product")
    for product in PRODUCTS:
        Product.objects.update_or_create(
            name=product["name"],
            defaults={
                **product,
                "price": 90,
                "volume": "330 ml",
                "available": True,
            },
        )


def remove_products(apps, schema_editor):
    Product = apps.get_model("main", "Product")
    Product.objects.filter(name__in=[product["name"] for product in PRODUCTS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0002_alter_product_image_alter_product_price"),
    ]

    operations = [
        migrations.RunPython(seed_products, remove_products),
    ]
