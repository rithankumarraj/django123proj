from django.db import migrations


PRODUCT = {
    "name": "J Workout Drink",
    "description": "Zero-sugar workout drink with energy, focus, endurance and hydration.",
    "price": "90.00",
    "volume": "330 ml",
    "image": "main/images/j-workout-drink.png",
    "available": True,
}


def add_product(apps, schema_editor):
    Product = apps.get_model("main", "Product")
    Product.objects.update_or_create(
        name=PRODUCT["name"],
        defaults=PRODUCT,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0007_order_customer"),
    ]

    operations = [
        migrations.RunPython(add_product, migrations.RunPython.noop),
    ]
