import json
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.test import Client

from main.models import Order
from main.payments import sign_webhook_payload


class Command(BaseCommand):
    help = "Send a signed mock payment webhook for a pending order."

    def add_arguments(self, parser):
        parser.add_argument("order_id", type=int)
        parser.add_argument(
            "--event-type",
            choices=["payment.succeeded", "payment.failed"],
            default="payment.succeeded",
        )

    def handle(self, *args, **options):
        try:
            order = Order.objects.get(pk=options["order_id"])
        except Order.DoesNotExist as error:
            raise CommandError(f"Order {options['order_id']} does not exist.") from error

        if order.payment_status != "pending":
            raise CommandError(
                f"Order {order.pk} is already {order.get_payment_status_display().lower()}."
            )

        event = {
            "event_id": str(uuid.uuid4()),
            "type": options["event_type"],
            "order_id": order.pk,
            "payment_reference": str(order.payment_reference),
            "amount": str(order.total_amount),
            "currency": "INR",
        }
        body = json.dumps(event, separators=(",", ":")).encode()
        try:
            signature = sign_webhook_payload(body)
        except RuntimeError as error:
            raise CommandError(str(error)) from error

        response = Client().post(
            "/webhooks/payment/",
            data=body,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE=signature,
        )
        if response.status_code != 200:
            raise CommandError(
                f"Webhook failed with HTTP {response.status_code}: {response.content.decode()}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Webhook delivered for order {order.pk}: {response.json()['status']}."
            )
        )
