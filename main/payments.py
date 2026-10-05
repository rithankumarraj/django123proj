import hashlib
import hmac
import json
import secrets
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction

from .models import Order

_DEV_WEBHOOK_SECRET = secrets.token_urlsafe(32)


def get_payment_webhook_secret():
    secret = getattr(settings, "PAYMENT_WEBHOOK_SECRET", "")
    if not secret and settings.PAYMENT_SIMULATION_ENABLED:
        return _DEV_WEBHOOK_SECRET
    return secret


def sign_webhook_payload(raw_body):
    secret = get_payment_webhook_secret()
    if not secret:
        raise RuntimeError("PAYMENT_WEBHOOK_SECRET must be configured.")
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def process_payment_webhook(raw_body, signature):
    secret = get_payment_webhook_secret()
    if not secret:
        return 503, {"error": "Payment webhook secret is not configured."}

    expected_signature = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_signature, signature or ""):
        return 401, {"error": "Invalid webhook signature."}

    try:
        event = json.loads(raw_body)
        if not isinstance(event, dict):
            raise ValueError
        event_id = event["event_id"]
        event_type = event["type"]
        order_id = event["order_id"]
        payment_reference = str(UUID(event["payment_reference"]))
        amount = Decimal(event["amount"])
        currency = event["currency"]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation):
        return 400, {"error": "Malformed payment event."}

    if (
        not isinstance(event_id, str)
        or not event_id
        or len(event_id) > 100
        or not isinstance(event_type, str)
        or type(order_id) is not int
        or order_id < 1
        or not amount.is_finite()
        or amount < 0
        or not isinstance(currency, str)
    ):
        return 400, {"error": "Invalid payment event fields."}
    if event_type not in {"payment.succeeded", "payment.failed"}:
        return 400, {"error": "Unsupported payment event type."}
    if currency != "INR":
        return 400, {"error": "Unsupported payment currency."}

    try:
        with transaction.atomic():
            previous_event = Order.objects.filter(payment_event_id=event_id).first()
            if previous_event:
                if (
                    previous_event.pk == order_id
                    and str(previous_event.payment_reference) == payment_reference
                ):
                    return 200, {
                        "status": previous_event.payment_status,
                        "duplicate": True,
                    }
                return 409, {"error": "Event ID has already been used."}

            order = Order.objects.select_for_update().get(
                pk=order_id, payment_reference=payment_reference
            )
            if order.total_amount != amount:
                return 400, {"error": "Payment amount does not match the order."}
            if order.payment_status != "pending":
                return 409, {"error": "Order already has a final payment status."}

            order.payment_status = (
                "paid" if event_type == "payment.succeeded" else "failed"
            )
            order.payment_event_id = event_id
            order.save(update_fields=["payment_status", "payment_event_id"])
    except Order.DoesNotExist:
        return 404, {"error": "Order not found."}
    except IntegrityError:
        return 409, {"error": "Event ID has already been used."}

    return 200, {"status": order.payment_status, "duplicate": False}
