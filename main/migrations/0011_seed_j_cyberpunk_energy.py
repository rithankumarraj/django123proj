from django.db import migrations


PRODUCT = {
    "name": "J Cyberpunk Energy Drink",
    "description": "Bold cyberpunk-inspired energy drink with a bright, refreshing taste.",
    "price": "90.00",
    "volume": "330 ml",
    "image": "main/images/j-cyberpunk-energy.png",
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
        ("main", "0010_seed_j_energy_lime"),
    ]

    operations = [
        migrations.RunPython(add_product, migrations.RunPython.noop),
    ]
