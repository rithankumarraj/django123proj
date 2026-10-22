from django.db import migrations


PRODUCT = {
    "name": "J Cola Zero Sugar",
    "description": "Bold cola taste with zero sugar and no artificial sweeteners.",
    "price": "90.00",
    "volume": "330 ml",
    "image": "main/images/j-cola-zero-sugar.png",
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
        ("main", "0008_seed_j_workout_drink"),
    ]

    operations = [
        migrations.RunPython(add_product, migrations.RunPython.noop),
    ]
