import base64
import hashlib
import hmac
import logging
import re
import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def get_cashfree_base_url():
    env = getattr(settings, "CASHFREE_ENV", "TEST").upper()
    if env in ("PROD", "PRODUCTION"):
        return "https://api.cashfree.com/pg"
    return "https://sandbox.cashfree.com/pg"


def get_cashfree_headers():
    return {
        "Content-Type": "application/json",
        "accept": "application/json",
        "x-api-version": getattr(settings, "CASHFREE_API_VERSION", "2023-08-01"),
        "x-client-id": getattr(settings, "CASHFREE_APP_ID", ""),
        "x-client-secret": getattr(settings, "CASHFREE_SECRET_KEY", ""),
    }


def clean_phone_number(raw_phone):
    digits = re.sub(r"\D", "", raw_phone or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    elif len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 else "9999999999"


def create_cashfree_order(order, return_url=None, notify_url=None):
    """
    Creates an order on Cashfree Payment Gateway and stores session details on the order.
    Returns (success: bool, data_or_error: dict).
    """
    app_id = getattr(settings, "CASHFREE_APP_ID", "")
    secret_key = getattr(settings, "CASHFREE_SECRET_KEY", "")
    if not app_id or not secret_key:
        return False, {"error": "Cashfree API credentials are not configured."}

    base_url = get_cashfree_base_url()
    url = f"{base_url}/orders"
    headers = get_cashfree_headers()

    cf_order_id = order.cashfree_order_id or f"ORDER_{order.id}_{order.payment_reference.hex[:8]}"

    customer_phone = clean_phone_number(order.customer_phone)
    customer_email = ""
    if order.customer and getattr(order.customer, "email", None):
        customer_email = order.customer.email.strip()
    if not customer_email:
        customer_email = "customer@example.com"

    customer_name = (order.customer_name or "").strip() or "Valued Customer"
    customer_id = f"cust_{order.customer_id or order.id}_{order.payment_reference.hex[:6]}"

    amount = float(order.total_amount)
    if amount <= 0:
        amount = 1.00

    order_meta = {}
    if return_url:
        order_meta["return_url"] = return_url
    if notify_url:
        order_meta["notify_url"] = notify_url

    payload = {
        "order_id": cf_order_id,
        "order_amount": round(amount, 2),
        "order_currency": "INR",
        "customer_details": {
            "customer_id": customer_id,
            "customer_phone": customer_phone,
            "customer_name": customer_name,
            "customer_email": customer_email,
        },
        "order_meta": order_meta,
        "order_note": f"Payment for Order #{order.id}",
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        resp_data = resp.json()
        if resp.status_code in (200, 201):
            payment_session_id = resp_data.get("payment_session_id") or ""
            order.cashfree_order_id = cf_order_id
            order.cashfree_payment_session_id = payment_session_id
            order.save(update_fields=["cashfree_order_id", "cashfree_payment_session_id"])
            return True, resp_data
        else:
            err_msg = resp_data.get("message") or resp_data.get("error") or str(resp_data)
            logger.error("Cashfree create order error (%s): %s", resp.status_code, err_msg)
            return False, {"error": err_msg, "status_code": resp.status_code, "data": resp_data}
    except Exception as exc:
        logger.exception("Cashfree create order request failed")
        return False, {"error": str(exc)}


def get_cashfree_order(cf_order_id):
    """
    Fetches order details from Cashfree: GET /pg/orders/{order_id}.
    Returns (success: bool, data_or_error: dict).
    """
    base_url = get_cashfree_base_url()
    url = f"{base_url}/orders/{cf_order_id}"
    headers = get_cashfree_headers()

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        if resp.status_code == 200:
            return True, resp.json()
        return False, resp.json()
    except Exception as exc:
        logger.exception("Cashfree get order failed")
        return False, {"error": str(exc)}


def verify_cashfree_webhook(headers, raw_body):
    """
    Verifies Cashfree webhook signature using HMAC-SHA256 (timestamp + raw_body).
    """
    secret = getattr(settings, "CASHFREE_SECRET_KEY", "")
    if not secret:
        return False, "Secret key not configured"

    received_sig = headers.get("x-webhook-signature") or headers.get("X-Webhook-Signature")
    timestamp = headers.get("x-webhook-timestamp") or headers.get("X-Webhook-Timestamp")
    if not received_sig or not timestamp:
        return False, "Missing webhook signature or timestamp headers"

    if isinstance(raw_body, str):
        raw_body = raw_body.encode("utf-8")

    signed_payload = str(timestamp).encode("utf-8") + raw_body
    computed = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).digest()
    expected_sig = base64.b64encode(computed).decode("utf-8")

    if hmac.compare_digest(expected_sig, received_sig):
        return True, "Valid"
    return False, "Signature mismatch"

