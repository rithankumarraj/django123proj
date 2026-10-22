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
from .models import DeliveryProfile, Order, OrderItem, Product
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


class CustomerAuthenticationTests(TestCase):
    def test_customer_can_register_and_is_signed_in(self):
        response = self.client.post(
            reverse("customer_register"),
            {
                "username": "newcustomer",
                "email": "newcustomer@example.com",
                "first_name": "New",
                "last_name": "Customer",
                "password1": "secure-customer-password-482!",
                "password2": "secure-customer-password-482!",
                "next": reverse("cart"),
            },
        )

        self.assertRedirects(response, reverse("cart"))
        user = get_user_model().objects.get(username="newcustomer")
        self.assertTrue(user.is_active)
        self.assertFalse(user.is_staff)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_customer_can_sign_in_without_admin_access(self):
        user = get_user_model().objects.create_user(
            username="shopper",
            email="shopper@example.com",
            password="test-password",
        )

        response = self.client.post(
            reverse("customer_login"),
            {"username": "shopper@example.com", "password": "test-password"},
        )

        self.assertRedirects(response, reverse("customer_orders"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        self.client.logout()
        admin_response = self.client.post(
            reverse("admin_login"),
            {"username": "shopper", "password": "test-password"},
        )
        self.assertContains(admin_response, "Admin access is restricted to staff accounts.")

    def test_customer_login_rejects_external_next_url(self):
        get_user_model().objects.create_user(
            username="shopper",
            email="shopper@example.com",
            password="test-password",
        )

        response = self.client.post(
            reverse("customer_login"),
            {
                "username": "shopper",
                "password": "test-password",
                "next": "https://example.com/",
            },
        )

        self.assertRedirects(response, reverse("customer_orders"))


class CustomerOrderHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = get_user_model().objects.create_user(
            username="history-customer",
            email="history@example.com",
            password="test-password",
        )
        cls.other_customer = get_user_model().objects.create_user(
            username="other-history-customer",
            email="other-history@example.com",
            password="test-password",
        )
        cls.product = Product.objects.create(
            name="History Cola",
            description="Order history test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )
        cls.order = Order.objects.create(
            product=cls.product,
            customer=cls.customer,
            customer_name="History Customer",
            delivery_address="15 History Street",
            delivery_city="Pune",
            delivery_state="Maharashtra",
            delivery_postal_code="411001",
            quantity=2,
            status="out_for_delivery",
            payment_status="paid",
            total_amount="180.00",
        )
        OrderItem.objects.create(
            order=cls.order,
            product=cls.product,
            quantity=2,
            unit_price="90.00",
        )
        Order.objects.create(
            product=cls.product,
            customer=cls.other_customer,
            customer_name="Other Customer",
            quantity=1,
            total_amount="90.00",
        )

    def test_order_history_shows_only_signed_in_customers_orders_and_status(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse("customer_orders"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Order #{self.order.pk}")
        self.assertContains(response, "Delivery: Out for delivery")
        self.assertContains(response, "Payment: Paid")
        self.assertContains(response, "History Cola")
        self.assertContains(response, "15 History Street")
        self.assertNotContains(response, f"Order #{self.order.pk + 1}")

    def test_order_history_requires_sign_in(self):
        response = self.client.get(reverse("customer_orders"))

        self.assertRedirects(
            response,
            f"{reverse('customer_login')}?next={reverse('customer_orders')}",
        )

    def test_storefront_shows_my_orders_link_for_signed_in_customer(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse("home"))

        self.assertContains(response, f'href="{reverse("customer_orders")}">My orders</a>')


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
        cls.customer = get_user_model().objects.create_user(
            username="checkout-customer",
            email="checkout@example.com",
            password="test-password",
            first_name="Test",
            last_name="Customer",
        )

    def test_checkout_calculates_total_for_requested_quantity(self):
        self.client.force_login(self.customer)
        response = self.client.get(f"/checkout/{self.product.id}/?qty=3")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "3</strong>")
        self.assertContains(response, "₹270.00")

    def test_checkout_rejects_invalid_quantity(self):
        self.client.force_login(self.customer)
        response = self.client.get(f"/checkout/{self.product.id}/?qty=not-a-number")

        self.assertEqual(response.status_code, 400)

    def test_checkout_requires_customer_login(self):
        response = self.client.get(f"/checkout/{self.product.id}/?qty=3")

        self.assertRedirects(
            response,
            f"{reverse('customer_login')}?next=%2Fcheckout%2F{self.product.id}%2F%3Fqty%3D3",
        )

    def test_product_page_includes_live_quantity_subtotal(self):
        response = self.client.get(f"/product/{self.product.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-quantity-total data-unit-price="90.00"')

    @override_settings(PAYMENT_SIMULATION_ENABLED=True)
    def test_checkout_creates_pending_order_and_opens_payment_page(self):
        self.client.force_login(self.customer)
        response = self.client.post(
            f"/checkout/{self.product.id}/?qty=3",
            {
                "first_name": "Test",
                "last_name": "Customer",
                "email": "customer@example.com",
                "address": "1 Test Street",
                "city": "Mumbai",
                "state": "Maharashtra",
                "postal_code": "400001",
            },
        )

        order = Order.objects.get()
        self.assertEqual(order.customer, self.customer)
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
        self.assertEqual(order.delivery_address, "1 Test Street")
        self.assertEqual(order.delivery_city, "Mumbai")
        self.assertEqual(order.delivery_state, "Maharashtra")
        self.assertEqual(order.delivery_postal_code, "400001")
        self.assertEqual(order.items.count(), 1)

    @override_settings(
        PAYMENT_SIMULATION_ENABLED=True,
        PAYMENT_WEBHOOK_SECRET="test-payment-secret",
    )
    def test_payment_confirmation_processes_success_webhook(self):
        self.client.force_login(self.customer)
        order = Order.objects.create(
            product=self.product,
            customer=self.customer,
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
        self.client.force_login(self.customer)
        order = Order.objects.create(
            product=self.product,
            customer=self.customer,
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
        self.client.force_login(self.customer)
        order = Order.objects.create(
            product=self.product,
            customer=self.customer,
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
        self.client.force_login(self.customer)
        order = Order.objects.create(
            product=self.product,
            customer=self.customer,
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


class HomeAddToCartTests(TestCase):
    def test_selected_product_has_add_to_cart_form(self):
        product = Product.objects.create(
            name="Home Cola",
            description="Test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )

        response = self.client.get(reverse("home"))
        selected_product_id = response.context["products"][0]["id"]

        self.assertContains(
            response,
            f'data-add-to-cart-url="/cart/add/{product.id}/"',
        )
        self.assertContains(
            response,
            f'action="/cart/add/{selected_product_id}/" data-product-add-to-cart',
        )
        self.assertContains(response, "Add to cart")
        self.assertContains(response, f'href="{reverse("about")}">')
        self.assertContains(response, "About us")
        self.assertContains(response, '<footer class="store-footer">')
        self.assertContains(response, 'href="mailto:support@jcsd.com"')
        self.assertContains(response, 'href="tel:+918056838888"')
        self.assertContains(response, 'href="https://wa.me/918056838888"')
        self.assertContains(response, f'href="{reverse("privacy_policy")}">Privacy policy</a>')
        self.assertContains(response, 'class="store-footer-mark"')
        self.assertContains(response, "Double-click a product to add it to your cart")
        self.assertContains(response, "Double-click to add")
        self.assertContains(response, "data-cart-feedback")
        self.assertContains(response, 'name="quantity" value="1"')
        self.assertContains(response, 'class="admin-access-button cart-access-button" data-scroll-cart')
        self.assertContains(response, '<svg class="cart-icon"')
        self.assertContains(response, 'class="cart-count" aria-hidden="true">0</span>')
        self.assertContains(response, "cart-scroll.")
        self.assertLess(
            response.content.index(b'data-scroll-cart'),
            response.content.index(b'href="/customer-login/">Sign in'),
        )

        self.client.post(
            reverse("add_to_cart", kwargs={"product_id": product.id}),
            {"quantity": "2"},
        )
        response = self.client.get(reverse("home"))
        product_response = self.client.get(
            reverse("product_detail", kwargs={"product_id": product.id})
        )

        self.assertContains(response, 'aria-label="Shopping cart, 2 items"')
        self.assertContains(response, 'class="cart-count" aria-hidden="true">2</span>')
        self.assertContains(product_response, 'aria-label="Shopping cart, 2 items"')
        self.assertContains(product_response, 'class="cart-count" aria-hidden="true">2</span>')
        self.assertContains(
            product_response,
            'class="admin-access-button cart-access-button" data-scroll-cart',
        )

    def test_ajax_add_to_cart_returns_updated_count_without_redirecting(self):
        product = Product.objects.create(
            name="Quick Add Cola",
            description="Test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )

        response = self.client.post(
            reverse("add_to_cart", kwargs={"product_id": product.id}),
            {"quantity": "1"},
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"cart_count": 1})
        self.assertEqual(self.client.session["cart"], {str(product.id): 1})


class AboutPageTests(TestCase):
    def test_about_page_has_minimal_brand_content_and_store_link(self):
        response = self.client.get(reverse("about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "About J CSD")
        self.assertContains(response, "Better drinks.")
        self.assertContains(response, 'href="/#shop">Explore the lineup</a>')
        self.assertContains(response, "J CSD. Better drinks. Less noise.")
        self.assertContains(response, '<footer class="about-footer">')


class PrivacyPolicyTests(TestCase):
    def test_privacy_policy_page_explains_store_data_use_and_contact(self):
        response = self.client.get(reverse("privacy_policy"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy policy")
        self.assertContains(response, "delivery address")
        self.assertContains(response, "authorized store staff")
        self.assertContains(response, 'href="mailto:support@jcsd.com"')


class SeededProductTests(TestCase):
    def test_j_workout_drink_is_available_in_the_store(self):
        product = Product.objects.get(name="J Workout Drink")

        self.assertEqual(product.price, Decimal("90.00"))
        self.assertEqual(product.volume, "330 ml")
        self.assertTrue(product.available)
        self.assertEqual(product.image, "main/images/j-workout-drink.png")

        response = self.client.get(reverse("home"))

        self.assertContains(response, "J Workout Drink")
        self.assertContains(response, "j-workout-drink")

    def test_j_cola_zero_sugar_is_available_in_the_store(self):
        product = Product.objects.get(name="J Cola Zero Sugar")

        self.assertEqual(product.price, Decimal("90.00"))
        self.assertEqual(product.volume, "330 ml")
        self.assertTrue(product.available)
        self.assertEqual(product.image, "main/images/j-cola-zero-sugar.png")

        response = self.client.get(reverse("home"))

        self.assertContains(response, "J Cola Zero Sugar")
        self.assertContains(response, "j-cola-zero-sugar")

    def test_j_energy_lime_is_available_in_the_store(self):
        product = Product.objects.get(name="J Energy Lime")

        self.assertEqual(product.price, Decimal("90.00"))
        self.assertEqual(product.volume, "330 ml")
        self.assertTrue(product.available)
        self.assertEqual(product.image, "main/images/j-energy-lime.png")

        response = self.client.get(reverse("home"))

        self.assertContains(response, "J Energy Lime")
        self.assertContains(response, "j-energy-lime")

    def test_j_cyberpunk_energy_is_available_in_the_store(self):
        product = Product.objects.get(name="J Cyberpunk Energy Drink")

        self.assertEqual(product.price, Decimal("90.00"))
        self.assertEqual(product.volume, "330 ml")
        self.assertTrue(product.available)
        self.assertEqual(product.image, "main/images/j-cyberpunk-energy.png")

        response = self.client.get(reverse("home"))

        self.assertContains(response, "J Cyberpunk Energy Drink")
        self.assertContains(response, "j-cyberpunk-energy")


class DeliveryProfileTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(
            username="delivery-admin",
            password="admin-password",
            is_staff=True,
        )
        cls.customer = get_user_model().objects.create_user(
            username="delivery-customer",
            password="customer-password",
        )
        cls.delivery_user = get_user_model().objects.create_user(
            username="delivery-person",
            email="driver@example.com",
            password="delivery-password",
        )
        DeliveryProfile.objects.create(user=cls.delivery_user)
        cls.product = Product.objects.create(
            name="Delivery Cola",
            description="Test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )
        cls.order = Order.objects.create(
            product=cls.product,
            customer=cls.customer,
            customer_name="Delivery Customer",
            delivery_address="12 Example Road",
            delivery_city="Mumbai",
            delivery_state="Maharashtra",
            delivery_postal_code="400001",
            quantity=2,
            total_amount="180.00",
        )

    def test_delivery_login_is_restricted_to_delivery_profiles(self):
        response = self.client.post(
            reverse("delivery_login"),
            {"username": "delivery-person", "password": "delivery-password"},
        )

        self.assertRedirects(response, reverse("delivery_dashboard"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.delivery_user.pk)

        self.client.logout()
        response = self.client.post(
            reverse("delivery_login"),
            {"username": "delivery-customer", "password": "customer-password"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "This account does not have delivery access.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_delivery_dashboard_shows_stock_and_delivery_address(self):
        unavailable = Product.objects.create(
            name="Unavailable Cola",
            description="Not in stock",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
            available=False,
        )
        self.client.force_login(self.delivery_user)

        response = self.client.get(reverse("delivery_dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Delivery Cola")
        self.assertContains(response, "Unavailable Cola")
        self.assertContains(response, "12 Example Road")
        self.assertContains(response, "400001")
        self.assertEqual(
            response.context["available_stock_count"],
            Product.objects.filter(available=True).count(),
        )
        self.assertEqual(response.context["unavailable_stock_count"], 1)
        self.assertEqual(unavailable.available, False)

    def test_delivery_user_can_return_to_dashboard_from_store_pages(self):
        self.client.force_login(self.delivery_user)

        home = self.client.get(reverse("home"))
        product = self.client.get(
            reverse("product_detail", kwargs={"product_id": self.product.pk})
        )

        self.assertContains(home, reverse("delivery_dashboard"))
        self.assertContains(home, "Delivery dashboard")
        self.assertContains(product, reverse("delivery_dashboard"))
        self.assertContains(product, "Delivery dashboard")

    def test_customer_cannot_access_delivery_dashboard_or_change_status(self):
        self.client.force_login(self.customer)

        dashboard = self.client.get(reverse("delivery_dashboard"))
        status = self.client.post(
            reverse("update_delivery_status", kwargs={"order_id": self.order.pk}),
            {"status": "delivered"},
        )

        self.assertEqual(dashboard.status_code, 403)
        self.assertEqual(status.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "pending")

    def test_delivery_user_can_update_order_status(self):
        self.client.force_login(self.delivery_user)

        response = self.client.post(
            reverse("update_delivery_status", kwargs={"order_id": self.order.pk}),
            {"status": "delivered"},
        )

        self.assertRedirects(response, reverse("delivery_dashboard"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "delivered")
        self.assertIsNotNone(self.order.delivered_at)

    def test_delivery_user_cannot_set_an_invalid_order_status(self):
        self.client.force_login(self.delivery_user)

        response = self.client.post(
            reverse("update_delivery_status", kwargs={"order_id": self.order.pk}),
            {"status": "cancelled"},
        )

        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "pending")

    def test_admin_can_create_a_delivery_profile(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("create_delivery_account"),
            {
                "username": "new-driver",
                "email": "new-driver@example.com",
                "first_name": "New",
                "last_name": "Driver",
                "password1": "secure-driver-password-482!",
                "password2": "secure-driver-password-482!",
            },
        )

        self.assertRedirects(response, reverse("admin_dashboard"))
        user = get_user_model().objects.get(username="new-driver")
        self.assertTrue(DeliveryProfile.objects.filter(user=user).exists())
        self.assertFalse(user.is_staff)

    def test_customer_cannot_create_a_delivery_profile(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("create_delivery_account"),
            {
                "username": "fake-driver",
                "email": "fake-driver@example.com",
                "password1": "secure-driver-password-482!",
                "password2": "secure-driver-password-482!",
            },
        )

        self.assertRedirects(
            response,
            f"{reverse('admin_login')}?next={reverse('create_delivery_account')}",
        )
        self.assertFalse(get_user_model().objects.filter(username="fake-driver").exists())


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
        cls.customer = get_user_model().objects.create_user(
            username="cart-customer",
            email="cart@example.com",
            password="test-password",
            first_name="Cart",
            last_name="Customer",
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

        self.assertContains(response, 'data-quantity-step="-1"')
        self.assertContains(response, 'data-quantity-step="1"')
        self.assertContains(
            response,
            f'name="quantity_{self.cola.id}" type="number" min="1" max="1000000" step="1" value="3"',
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

    def test_ajax_cart_quantity_update_returns_live_totals(self):
        self.add_item(self.cola, "1")
        self.add_item(self.lime, "2")

        response = self.client.post(
            reverse("update_cart"),
            {
                "action": "update",
                f"quantity_{self.cola.id}": "4",
                f"quantity_{self.lime.id}": "1",
            },
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "cart_count": 5,
                "cart_total": "470.00",
                "items": [
                    {"product_id": self.cola.id, "quantity": 4, "line_total": "360.00"},
                    {"product_id": self.lime.id, "quantity": 1, "line_total": "110.00"},
                ],
            },
        )

    def test_cart_page_uses_automatic_quantity_updates(self):
        self.add_item(self.cola, "1")

        response = self.client.get(reverse("cart"))

        self.assertContains(response, "data-cart-update-form")
        self.assertContains(response, "data-cart-total")
        self.assertContains(response, "data-cart-save-status")
        self.assertNotContains(response, "Update quantities")

    def test_cart_checkout_creates_one_order_with_all_lines(self):
        self.client.force_login(self.customer)
        self.add_item(self.cola, "2")
        self.add_item(self.lime, "1")

        response = self.client.post(
            reverse("cart_checkout"),
            {
                "first_name": "Cart",
                "last_name": "Customer",
                "email": "cart@example.com",
                "address": "1 Cart Street",
                "city": "Pune",
                "state": "Maharashtra",
                "postal_code": "411001",
            },
        )

        order = Order.objects.get()
        self.assertEqual(order.customer, self.customer)
        self.assertRedirects(
            response,
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
        )
        self.assertEqual(order.total_amount, Decimal("290.00"))
        self.assertEqual(order.quantity, 3)
        self.assertEqual(order.delivery_address, "1 Cart Street")
        self.assertEqual(order.delivery_city, "Pune")
        self.assertEqual(order.delivery_state, "Maharashtra")
        self.assertEqual(order.delivery_postal_code, "411001")
        self.assertEqual(order.items.count(), 2)
        payment_page = self.client.get(response.url)
        self.assertContains(payment_page, "Cart Cola")
        self.assertContains(payment_page, "Cart Lime")
        self.assertContains(payment_page, "₹290.00")
        self.assertEqual(self.client.get(reverse("cart")).context["items"], [])

    def test_cart_checkout_requires_customer_login_and_keeps_cart(self):
        self.add_item(self.cola, "2")

        response = self.client.post(
            reverse("cart_checkout"),
            {"first_name": "Cart", "last_name": "Customer"},
        )

        self.assertRedirects(
            response,
            f"{reverse('customer_login')}?next=%2Fcart%2F",
        )
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.client.get(reverse("cart")).context["cart_count"], 2)

    def test_cart_rejects_invalid_quantity(self):
        response = self.add_item(self.cola, "0")

        self.assertEqual(response.status_code, 400)


class CustomerOrderAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Owned Cola",
            description="Test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )
        cls.customer = get_user_model().objects.create_user(
            username="order-owner",
            password="test-password",
        )
        cls.other_customer = get_user_model().objects.create_user(
            username="other-customer",
            password="test-password",
        )
        cls.order = Order.objects.create(
            product=cls.product,
            customer=cls.customer,
            customer_name="Order Owner",
            quantity=1,
            total_amount="90.00",
        )

    def test_payment_page_requires_customer_login(self):
        response = self.client.get(
            reverse("payment_page", kwargs={"payment_reference": self.order.payment_reference})
        )

        self.assertRedirects(
            response,
            f"{reverse('customer_login')}?next=%2Fpayment%2F{self.order.payment_reference}%2F",
        )

    def test_payment_page_is_private_to_the_order_owner(self):
        self.client.force_login(self.other_customer)

        response = self.client.get(
            reverse("payment_page", kwargs={"payment_reference": self.order.payment_reference})
        )

        self.assertEqual(response.status_code, 404)


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
