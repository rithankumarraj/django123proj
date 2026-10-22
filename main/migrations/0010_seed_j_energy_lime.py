from django.db import migrations


PRODUCT = {
    "name": "J Energy Lime",
    "description": "Bright lime energy drink with a crisp citrus finish.",
    "price": "90.00",
    "volume": "330 ml",
    "image": "main/images/j-energy-lime.png",
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
        ("main", "0009_seed_j_cola_zero_sugar"),
    ]

    operations = [
        migrations.RunPython(add_product, migrations.RunPython.noop),
    ]
