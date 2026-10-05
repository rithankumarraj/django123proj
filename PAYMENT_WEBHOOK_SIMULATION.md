# Payment webhook simulation

In development (`DEBUG=True`), submit the checkout form with **Pay now (simulate webhook)**. The app creates a pending order and sends a locally signed mock `payment.succeeded` event through the same event processor used by the webhook receiver. The checkout response shows the result and order ID.

The webhook receiver is:

```text
POST /webhooks/payment/
Content-Type: application/json
X-Payment-Signature: <hex HMAC-SHA256 of the exact request body>
```

Event example:

```json
{
  "event_id": "provider-unique-event-id",
  "type": "payment.succeeded",
  "order_id": 1,
  "payment_reference": "the-order-payment-uuid",
  "amount": "270.00",
  "currency": "INR"
}
```

Use an existing pending order to exercise the actual HTTP webhook route through Django's local test client:

```sh
../venv/bin/python manage.py simulate_payment_webhook 1
```

To simulate a declined payment instead:

```sh
../venv/bin/python manage.py simulate_payment_webhook 1 --event-type payment.failed
```

In development, a random process-local webhook secret is generated for simulation. For a real external payment provider, set a high-entropy `PAYMENT_WEBHOOK_SECRET` in the server environment and configure that same secret with the provider. Never use the development simulation as proof that a real payment was collected.
