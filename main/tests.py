from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import override_settings
from types import SimpleNamespace
from unittest.mock import Mock
import json
from decimal import Decimal

from allauth.core.exceptions import ImmediateHttpResponse

from .adapters import AdminGoogleAccountAdapter
from .models import Order, Product
from .payments import sign_webhook_payload


class AdminGoogleAccountAdapterTests(TestCase):
    def setUp(self):
        self.adapter = AdminGoogleAccountAdapter()

    @override_settings(GOOGLE_ADMIN_EMAIL="admin@gmail.com")
    def test_only_configured_verified_google_email_is_authorized(self):
        account = SimpleNamespace(
            extra_data={"email": "ADMIN@gmail.com", "email_verified": True}
        )
        sociallogin = SimpleNamespace(account=account)

        self.assertTrue(self.adapter.is_open_for_signup(None, sociallogin))

    @override_settings(GOOGLE_ADMIN_EMAIL="admin@gmail.com")
    def test_unverified_or_non_allowlisted_google_email_is_rejected(self):
        for extra_data in (
            {"email": "admin@gmail.com", "email_verified": False},
            {"email": "someone-else@gmail.com", "email_verified": True},
        ):
            with self.subTest(extra_data=extra_data):
                sociallogin = SimpleNamespace(account=SimpleNamespace(extra_data=extra_data))
                self.assertFalse(self.adapter.is_open_for_signup(None, sociallogin))

    @override_settings(GOOGLE_ADMIN_EMAIL="")
    def test_google_signup_is_disabled_without_an_allowlisted_email(self):
        sociallogin = SimpleNamespace(
            account=SimpleNamespace(
                extra_data={"email": "admin@gmail.com", "email_verified": True}
            )
        )

        self.assertFalse(self.adapter.is_open_for_signup(None, sociallogin))

    @override_settings(GOOGLE_ADMIN_EMAIL="admin@gmail.com")
    def test_allowlisted_verified_google_account_gains_staff_access(self):
        user = SimpleNamespace(is_staff=False, save=Mock())
        sociallogin = SimpleNamespace(
            account=SimpleNamespace(
                extra_data={"email": "admin@gmail.com", "email_verified": True}
            ),
            is_existing=True,
            user=user,
        )

        self.adapter.pre_social_login(None, sociallogin)

        self.assertTrue(user.is_staff)
        user.save.assert_called_once_with(update_fields=["is_staff"])

    @override_settings(GOOGLE_ADMIN_EMAIL="admin@gmail.com")
    def test_other_google_accounts_are_forbidden(self):
        sociallogin = SimpleNamespace(
            account=SimpleNamespace(
                extra_data={"email": "other@gmail.com", "email_verified": True}
            )
        )

        with self.assertRaises(ImmediateHttpResponse) as raised:
            self.adapter.pre_social_login(None, sociallogin)

        self.assertEqual(raised.exception.response.status_code, 403)


class AdminLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff_user = get_user_model().objects.create_user(
            username="storeadmin",
            email="admin@example.com",
            password="test-password",
            is_staff=True,
        )
        cls.regular_user = get_user_model().objects.create_user(
            username="customer",
            email="customer@example.com",
            password="test-password",
        )

    def test_staff_can_sign_in_with_username(self):
        response = self.client.post(
            reverse("admin_login"),
            {"username": "storeadmin", "password": "test-password"},
        )

        self.assertRedirects(response, reverse("admin_dashboard"))

    def test_staff_can_sign_in_with_email(self):
        response = self.client.post(
            reverse("admin_login"),
            {"username": "ADMIN@example.com", "password": "test-password"},
        )

        self.assertRedirects(response, reverse("admin_dashboard"))

    def test_non_staff_cannot_sign_in_to_admin(self):
        response = self.client.post(
            reverse("admin_login"),
            {"username": "customer@example.com", "password": "test-password"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertContains(response, "Admin access is restricted to staff accounts.")

    def test_dashboard_redirects_anonymous_user_to_login(self):
        response = self.client.get(reverse("admin_dashboard"))

        self.assertRedirects(response, f"{reverse('admin_login')}?next={reverse('admin_dashboard')}")

    @override_settings(
        GOOGLE_CLIENT_ID="test-client-id",
        GOOGLE_CLIENT_SECRET="test-client-secret",
        GOOGLE_ADMIN_EMAIL="admin@gmail.com",
        GOOGLE_SIGN_IN_ENABLED=True,
        SOCIALACCOUNT_PROVIDERS={
            "google": {
                "APP": {
                    "client_id": "test-client-id",
                    "secret": "test-client-secret",
                    "key": "",
                },
                "SCOPE": ["profile", "email"],
            }
        },
    )
    def test_google_sign_in_redirects_to_google(self):
        response = self.client.get("/accounts/google/login/")

        self.assertEqual(response.status_code, 302)
        self.assertIn("accounts.google.com", response["Location"])

    def test_google_button_is_hidden_until_oauth_is_configured(self):
        response = self.client.get(reverse("admin_login"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Continue with Google")


class CheckoutQuantityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Test Cola",
            description="Test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )

    def test_checkout_calculates_total_for_requested_quantity(self):
        response = self.client.get(f"/checkout/{self.product.id}/?qty=3")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3</strong>")
        self.assertContains(response, "₹270.00")

    def test_checkout_rejects_invalid_quantity(self):
        response = self.client.get(f"/checkout/{self.product.id}/?qty=not-a-number")

        self.assertEqual(response.status_code, 400)

    def test_product_page_includes_live_quantity_subtotal(self):
        response = self.client.get(f"/product/{self.product.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-quantity-total data-unit-price="90.00"')

    @override_settings(PAYMENT_SIMULATION_ENABLED=True)
    def test_checkout_creates_pending_order_and_opens_payment_page(self):
        response = self.client.post(
            f"/checkout/{self.product.id}/?qty=3",
            {
                "first_name": "Test",
                "last_name": "Customer",
                "email": "customer@example.com",
                "address": "1 Test Street",
                "city": "Mumbai",
                "state": "Maharashtra",
                "zip": "400001",
            },
        )

        order = Order.objects.get()
        self.assertRedirects(
            response,
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
        )
        payment_page = self.client.get(response.url)
        self.assertEqual(payment_page.status_code, 200)
        self.assertContains(payment_page, "Confirm demo payment")
        self.assertContains(payment_page, "₹270.00")
        self.assertContains(payment_page, "No card, bank, or UPI payment is made.")
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "pending")
        self.assertEqual(order.quantity, 3)
        self.assertEqual(str(order.total_amount), "270.00")
        self.assertEqual(order.items.count(), 1)

    @override_settings(
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMENT_WEBHOOK_SECRET="test-payment-secret",
    )
    def test_payment_confirmation_processes_success_webhook(self):
        order = Order.objects.create(
            product=self.product,
            customer_name="Test Customer",
            quantity=3,
            total_amount="270.00",
        )

        response = self.client.post(
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
            {"action": "confirm"},
        )

        self.assertRedirects(
            response,
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
        )
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "paid")
        confirmation = self.client.get(response.url)
        self.assertContains(confirmation, "Payment status")
        self.assertContains(confirmation, "Paid")

    @override_settings(
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMENT_WEBHOOK_SECRET="test-payment-secret",
    )
    def test_payment_cancellation_processes_failed_webhook(self):
        order = Order.objects.create(
            product=self.product,
            customer_name="Test Customer",
            quantity=1,
            total_amount="90.00",
        )

        response = self.client.post(
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
            {"action": "cancel"},
        )

        self.assertRedirects(
            response,
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
        )
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "failed")

    @override_settings(PAYMENT_SIMULATION_ENABLED=False)
    def test_payment_page_does_not_claim_payment_when_simulation_disabled(self):
        order = Order.objects.create(
            product=self.product,
            customer_name="Test Customer",
            quantity=1,
            total_amount="90.00",
        )

        response = self.client.get(
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference})
        )

        self.assertContains(response, "No payment provider is connected")
        self.assertNotContains(response, "Confirm demo payment")
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "pending")

    @override_settings(
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMENT_WEBHOOK_SECRET="test-payment-secret",
    )
    def test_payment_page_rejects_invalid_action(self):
        order = Order.objects.create(
            product=self.product,
            customer_name="Test Customer",
            quantity=1,
            total_amount="90.00",
        )

        response = self.client.post(
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
            {"action": "unexpected"},
        )

        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "pending")


class CartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.cola = Product.objects.create(
            name="Cart Cola",
            description="Cola",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )
        cls.lime = Product.objects.create(
            name="Cart Lime",
            description="Lime",
            price="110.00",
            volume="330 ml",
            image="main/images/lime.png",
        )

    def add_item(self, product, quantity):
        return self.client.post(
            reverse("add_to_cart", kwargs={"product_id": product.id}),
            {"quantity": quantity},
        )

    def test_cart_accumulates_multiple_products(self):
        self.assertRedirects(self.add_item(self.cola, "2"), reverse("cart"))
        self.assertRedirects(self.add_item(self.lime, "3"), reverse("cart"))

        response = self.client.get(reverse("cart"))

        self.assertContains(response, "Cart Cola")
        self.assertContains(response, "Cart Lime")
        self.assertContains(response, "5 items")
        self.assertContains(response, "₹510.00")

    def test_readding_same_product_increases_quantity(self):
        self.add_item(self.cola, "2")
        self.add_item(self.cola, "1")

        response = self.client.get(reverse("cart"))

        self.assertContains(
            response,
            f'name="quantity_{self.cola.id}" type="number" min="1" max="1000000" value="3"',
        )
        self.assertContains(response, "₹270.00")

    def test_cart_quantities_can_be_updated_and_items_removed(self):
        self.add_item(self.cola, "1")
        self.add_item(self.lime, "2")

        response = self.client.post(
            reverse("update_cart"),
            {
                "action": "update",
                f"quantity_{self.cola.id}": "4",
                f"quantity_{self.lime.id}": "1",
            },
        )
        self.assertRedirects(response, reverse("cart"))
        self.assertContains(self.client.get(reverse("cart")), "₹470.00")

        response = self.client.post(
            reverse("update_cart"),
            {"action": "remove", "product_id": str(self.cola.id)},
        )
        self.assertRedirects(response, reverse("cart"))
        cart_page = self.client.get(reverse("cart"))
        self.assertNotContains(cart_page, "Cart Cola")
        self.assertContains(cart_page, "Cart Lime")

    def test_cart_checkout_creates_one_order_with_all_lines(self):
        self.add_item(self.cola, "2")
        self.add_item(self.lime, "1")

        response = self.client.post(
            reverse("cart_checkout"),
            {
                "first_name": "Cart",
                "last_name": "Customer",
                "email": "cart@example.com",
            },
        )

        order = Order.objects.get()
        self.assertRedirects(
            response,
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
        )
        self.assertEqual(order.total_amount, Decimal("290.00"))
        self.assertEqual(order.quantity, 3)
        self.assertEqual(order.items.count(), 2)
        payment_page = self.client.get(response.url)
        self.assertContains(payment_page, "Cart Cola")
        self.assertContains(payment_page, "Cart Lime")
        self.assertContains(payment_page, "₹290.00")
        self.assertEqual(self.client.get(reverse("cart")).context["items"], [])

    def test_cart_rejects_invalid_quantity(self):
        response = self.add_item(self.cola, "0")

        self.assertEqual(response.status_code, 400)


@override_settings(PAYMENT_WEBHOOK_SECRET="test-payment-secret")
class PaymentWebhookTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        product = Product.objects.create(
            name="Webhook Cola",
            description="Test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )
        cls.order = Order.objects.create(
            product=product,
            customer_name="Webhook Customer",
            quantity=2,
            total_amount="180.00",
        )

    def make_event(self, **overrides):
        event = {
            "event_id": "evt-test-1",
            "type": "payment.succeeded",
            "order_id": self.order.id,
            "payment_reference": str(self.order.payment_reference),
            "amount": "180.00",
            "currency": "INR",
        }
        event.update(overrides)
        body = json.dumps(event, separators=(",", ":")).encode()
        return body, sign_webhook_payload(body)

    def test_valid_signed_webhook_marks_order_paid(self):
        body, signature = self.make_event()

        response = self.client.post(
            reverse("payment_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "paid")
        self.assertEqual(self.order.payment_event_id, "evt-test-1")

    def test_duplicate_event_is_idempotent(self):
        body, signature = self.make_event()
        for _ in range(2):
            response = self.client.post(
                reverse("payment_webhook"),
                data=body,
                content_type="application/json",
                HTTP_X_PAYMENT_SIGNATURE=signature,
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["duplicate"])
        self.assertEqual(Order.objects.count(), 1)

    def test_invalid_signature_does_not_change_order(self):
        body, _ = self.make_event()

        response = self.client.post(
            reverse("payment_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE="invalid",
        )

        self.assertEqual(response.status_code, 401)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "pending")

    def test_amount_mismatch_does_not_change_order(self):
        body, signature = self.make_event(amount="1.00")

        response = self.client.post(
            reverse("payment_webhook"),
            data=body,
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "pending")

    def test_webhook_rejects_invalid_json(self):
        response = self.client.post(
            reverse("payment_webhook"),
            data=b"{not-json",
            content_type="application/json",
            HTTP_X_PAYMENT_SIGNATURE=sign_webhook_payload(b"{not-json"),
        )

        self.assertEqual(response.status_code, 400)

    def test_webhook_rejects_get_requests(self):
        response = self.client.get(reverse("payment_webhook"))

        self.assertEqual(response.status_code, 405)

    def test_simulation_command_posts_a_signed_webhook(self):
        from django.core.management import call_command

        call_command("simulate_payment_webhook", str(self.order.pk))
        self.order.refresh_from_db()

        self.assertEqual(self.order.payment_status, "paid")
