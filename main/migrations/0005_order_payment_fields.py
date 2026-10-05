import uuid

from django.db import migrations, models


def populate_payment_references(apps, schema_editor):
    Order = apps.get_model("main", "Order")
    for order in Order.objects.filter(payment_reference__isnull=True).iterator():
        order.payment_reference = uuid.uuid4()
        order.save(update_fields=["payment_reference"])


class Migration(migrations.Migration):
    dependencies = [
        ("main", "0004_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="payment_status",
            field=models.CharField(
                choices=[
                    ("pending", "Payment pending"),
                    ("paid", "Paid"),
                    ("failed", "Payment failed"),
                ],
                default="pending",
                max_length=12,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="total_amount",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=10),
        ),
        migrations.AddField(
            model_name="order",
            name="payment_reference",
            field=models.UUIDField(null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="payment_event_id",
            field=models.CharField(blank=True, max_length=100, null=True, unique=True),
        ),
        migrations.RunPython(populate_payment_references, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="order",
            name="payment_reference",
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
