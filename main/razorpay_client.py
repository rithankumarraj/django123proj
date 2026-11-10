import hashlib
import hmac
import logging
from decimal import Decimal
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

RAZORPAY_API_URL = "https://api.razorpay.com/v1"


def get_razorpay_auth():
    return (
        getattr(settings, "RAZORPAY_KEY_ID", ""),
        getattr(settings, "RAZORPAY_KEY_SECRET", ""),
    )


def create_razorpay_order(order):
    """
    Creates a Razorpay order via the Razorpay Orders API.
    Amount must be an integer in paise (1 INR = 100 paise).
    """
    key_id, key_secret = get_razorpay_auth()
    if not key_id or not key_secret:
        return False, {"error": "Razorpay credentials are not configured."}

    # Minimum order in Razorpay is ₹1.00 (100 paise)
    amount_in_paise = max(100, int(round(float(order.total_amount) * 100)))
    receipt = f"order_{order.id}_{order.payment_reference.hex[:8]}"

    payload = {
        "amount": amount_in_paise,
        "currency": "INR",
        "receipt": receipt,
        "notes": {
            "order_id": str(order.id),
            "payment_reference": str(order.payment_reference),
            "customer_name": order.customer_name or "",
            "customer_phone": order.customer_phone or "",
        },
    }

    url = f"{RAZORPAY_API_URL}/orders"
    try:
        resp = requests.post(
            url,
            auth=(key_id, key_secret),
            json=payload,
            timeout=15,
        )
        data = resp.json()
        if resp.status_code in (200, 201) and "id" in data:
            order.razorpay_order_id = data["id"]
            order.save(update_fields=["razorpay_order_id"])
            return True, data
        else:
            err_msg = data.get("error", {}).get("description", "Failed to create Razorpay order.")
            logger.error("Razorpay order creation error: %s (%s)", err_msg, resp.text)
            return False, {"error": err_msg, "raw": data}
    except Exception as exc:
        logger.exception("Razorpay connection exception during order creation: %s", exc)
        return False, {"error": str(exc)}


def verify_razorpay_signature(razorpay_order_id, razorpay_payment_id, razorpay_signature):
    """
    Verifies Razorpay payment signature using HMAC SHA256:
    signature = hmac_sha256(order_id + "|" + payment_id, secret)
    """
    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        return False

    _, key_secret = get_razorpay_auth()
    if not key_secret:
        return False

    message = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    expected_signature = hmac.new(
        key_secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, razorpay_signature.strip())


def get_razorpay_payment(payment_id):
    """
    Fetches payment details for a given razorpay_payment_id.
    """
    key_id, key_secret = get_razorpay_auth()
    if not key_id or not key_secret:
        return False, {"error": "Razorpay credentials are not configured."}

    url = f"{RAZORPAY_API_URL}/payments/{payment_id}"
    try:
        resp = requests.get(url, auth=(key_id, key_secret), timeout=15)
        data = resp.json()
        if resp.status_code == 200:
            return True, data
        return False, {"error": data.get("error", {}).get("description", "Could not fetch payment."), "raw": data}
    except Exception as exc:
        return False, {"error": str(exc)}


def verify_razorpay_webhook_signature(raw_body, signature, webhook_secret=None):
    """
    Validates Razorpay webhook signature header.
    """
    secret = webhook_secret or getattr(settings, "RAZORPAY_WEBHOOK_SECRET", None) or getattr(settings, "RAZORPAY_KEY_SECRET", "")
    if not secret:
        return False, "Webhook secret not configured."

    if not signature:
        return False, "Missing Razorpay webhook signature."

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, signature.strip()):
        return True, "Valid"
    return False, "Signature mismatch"

