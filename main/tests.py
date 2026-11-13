from django.test import TestCase
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.test import override_settings
from types import SimpleNamespace
from unittest.mock import Mock, patch
import json
from decimal import Decimal
from django.utils import timezone

from allauth.core.exceptions import ImmediateHttpResponse

from .adapters import AdminGoogleAccountAdapter
from .models import (
    ComboOffer,
    ContactMessage,
    Coupon,
    CustomerAddress,
    CustomerProfile,
    DeliveryProfile,
    Order,
    OrderItem,
    Product,
    ProductCategory,
    SiteDetails,
    WebsiteView,
)
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


class CustomerProfileTests(TestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(
            username="profile-customer",
            password="old-profile-password",
            first_name="Profile",
            last_name="Customer",
        )

    def test_profile_page_requires_sign_in(self):
        response = self.client.get(reverse("customer_profile"))

        self.assertRedirects(
            response,
            f"{reverse('customer_login')}?next={reverse('customer_profile')}",
        )

    def test_profile_page_shows_password_change_for_signed_in_customer(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse("customer_profile"))

        self.assertContains(response, "Change password")
        self.assertContains(response, "Enter it below to set a new password.")

    def test_profile_updates_username_and_saved_delivery_details(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("customer_profile"),
            {
                "action": "save_profile",
                "username": "updated-profile",
                "first_name": "Profile",
                "last_name": "Customer",
                "phone": "+91 98765 43210",
                "address": "10 Profile Road",
                "city": "Pune",
                "state": "Maharashtra",
                "postal_code": "411001",
            },
        )

        self.assertRedirects(response, reverse("customer_profile"))
        self.customer.refresh_from_db()
        profile = CustomerProfile.objects.get(user=self.customer)
        self.assertEqual(self.customer.username, "updated-profile")
        self.assertEqual(profile.phone, "+91 98765 43210")
        self.assertEqual(profile.address, "10 Profile Road")
        self.assertEqual(profile.city, "Pune")
        self.assertEqual(profile.state, "Maharashtra")
        self.assertEqual(profile.postal_code, "411001")

    def test_profile_changes_password_and_keeps_customer_signed_in(self):
        self.client.force_login(self.customer)

        response = self.client.post(
            reverse("customer_profile"),
            {
                "action": "change_password",
                "old_password": "old-profile-password",
                "new_password1": "new-secure-profile-password-927!",
                "new_password2": "new-secure-profile-password-927!",
            },
        )

        self.assertRedirects(response, reverse("customer_profile"))
        self.customer.refresh_from_db()
        self.assertTrue(
            self.customer.check_password("new-secure-profile-password-927!")
        )
        self.assertEqual(response.wsgi_request.user, self.customer)


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
            customer_phone="+91 98765 43210",
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
        self.assertContains(response, f"Order #{self.order.order_number or self.order.pk}")
        self.assertContains(response, "Delivery: Out for delivery")
        self.assertContains(response, "Payment: Paid")
        self.assertContains(response, "History Cola")
        self.assertContains(response, "15 History Street")
        self.assertContains(response, "+91 98765 43210")
        self.assertNotContains(response, f"Order #{self.order.pk + 9999}")

    def test_order_history_requires_sign_in(self):
        response = self.client.get(reverse("customer_orders"))

        self.assertRedirects(
            response,
            f"{reverse('customer_login')}?next={reverse('customer_orders')}",
        )

    def test_order_history_searches_order_number_product_and_delivery_address(self):
        second_order = Order.objects.create(
            product=self.product,
            customer=self.customer,
            customer_name="History Customer",
            delivery_address="88 Lime Avenue",
            delivery_city="Mumbai",
            delivery_state="Maharashtra",
            delivery_postal_code="400001",
            quantity=1,
            total_amount="90.00",
        )
        lime = Product.objects.create(
            name="Searchable Lime",
            description="Search test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )
        OrderItem.objects.create(
            order=second_order,
            product=lime,
            quantity=1,
            unit_price="90.00",
        )
        self.client.force_login(self.customer)

        for query, expected in (
            (str(self.order.order_number or self.order.pk), self.order),
            ("Searchable Lime", second_order),
            ("Lime Avenue", second_order),
        ):
            with self.subTest(query=query):
                response = self.client.get(reverse("customer_orders"), {"q": query})
                self.assertEqual(list(response.context["orders"]), [expected])
                self.assertContains(response, f"Order #{expected.order_number or expected.pk}")

    def test_order_history_sorts_by_date_and_total(self):
        lower_total_order = Order.objects.create(
            product=self.product,
            customer=self.customer,
            customer_name="History Customer",
            quantity=1,
            total_amount="45.00",
        )
        higher_total_order = Order.objects.create(
            product=self.product,
            customer=self.customer,
            customer_name="History Customer",
            quantity=1,
            total_amount="250.00",
        )
        self.client.force_login(self.customer)

        expected_orders = {
            "newest": [higher_total_order, lower_total_order, self.order],
            "oldest": [self.order, lower_total_order, higher_total_order],
            "total_high": [higher_total_order, self.order, lower_total_order],
            "total_low": [lower_total_order, self.order, higher_total_order],
        }
        for sort_order, expected in expected_orders.items():
            with self.subTest(sort=sort_order):
                response = self.client.get(
                    reverse("customer_orders"), {"sort": sort_order}
                )
                self.assertEqual(list(response.context["orders"]), expected)
                self.assertEqual(response.context["sort_order"], sort_order)

    def test_order_history_ignores_unknown_sort_option(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse("customer_orders"), {"sort": "random"})

        self.assertEqual(response.context["sort_order"], "newest")
        self.assertEqual(list(response.context["orders"]), [self.order])

    def test_storefront_shows_my_orders_link_for_signed_in_customer(self):
        self.client.force_login(self.customer)

        response = self.client.get(reverse("home"))

        self.assertContains(response, f'href="{reverse("customer_orders")}">My orders</a>')
        self.assertContains(
            response,
            '<summary class="admin-access-button">history-customer</summary>',
        )
        self.assertContains(response, f'href="{reverse("customer_profile")}">My profile</a>')


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

    def test_checkout_is_available_without_customer_login(self):
        response = self.client.get(f"/checkout/{self.product.id}/?qty=3")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="phone"')

    def test_checkout_prefills_saved_profile_details(self):
        self.client.force_login(self.customer)
        CustomerProfile.objects.create(
            user=self.customer,
            phone="+91 98765 43210",
            address="10 Profile Road",
            city="Pune",
            state="Maharashtra",
            postal_code="411001",
        )

        response = self.client.get(f"/checkout/{self.product.id}/?qty=1")

        self.assertContains(
            response,
            'id="phone" name="phone" type="tel"',
        )
        self.assertContains(
            response,
            'value="9876543210"',
        )
        self.assertContains(
            response,
            'id="address" name="address" type="text" value="10 Profile Road"',
        )

    def test_guest_checkout_creates_account_and_signs_customer_in(self):
        response = self.client.post(
            f"/checkout/{self.product.id}/?qty=2",
            {
                "first_name": "Guest",
                "last_name": "Shopper",
                "email": "guest@example.com",
                "phone": "+91 98765 43210",
                "address": "2 Guest Street",
                "city": "Mumbai",
                "state": "Maharashtra",
                "postal_code": "400001",
            },
        )

        order = Order.objects.get()
        self.assertIsNotNone(order.customer)
        self.assertEqual(order.customer_name, "Guest Shopper")
        self.assertEqual(order.customer_phone, "+91 98765 43210")
        self.assertEqual(order.customer.username, "guest")
        self.assertEqual(order.customer.email, "guest@example.com")
        self.assertEqual(order.customer.first_name, "Guest")
        self.assertTrue(order.customer.has_usable_password())
        self.assertTrue(order.customer.check_password("+91 98765 43210"))
        self.assertTrue(
            CustomerProfile.objects.filter(
                user=order.customer,
                phone="+91 98765 43210",
                address="2 Guest Street",
            ).exists()
        )
        self.assertEqual(order.quantity, 2)
        self.assertRedirects(
            response,
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
        )
        payment_page = self.client.get(response.url)
        self.assertEqual(payment_page.status_code, 200)
        self.assertContains(payment_page, "Delivery status")
        self.assertContains(payment_page, "+91 98765 43210")
        self.assertContains(payment_page, "Your account username is")
        self.assertContains(payment_page, "set a custom password in your profile")
        profile_page = self.client.get(reverse("customer_profile"))
        self.assertContains(profile_page, "Set a password")
        set_password_response = self.client.post(
            reverse("customer_profile"),
            {
                "action": "set_password",
                "new_password1": "NewSecurePass!358",
                "new_password2": "NewSecurePass!358",
            },
        )
        self.assertRedirects(set_password_response, reverse("customer_profile"))
        self.client.logout()
        self.assertTrue(
            self.client.login(
                username=order.customer.username,
                password="NewSecurePass!358",
            )
        )

    def test_guest_logout_without_setting_password_can_login_with_phone(self):
        response = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            {
                "first_name": "Rohan",
                "last_name": "Kumar",
                "email": "rohan@example.com",
                "phone": "+91 91234 56789",
                "address": "42 High Road",
                "city": "Bengaluru",
                "state": "Karnataka",
                "postal_code": "560001",
            },
        )
        order = Order.objects.get()
        # Guest is logged in now; post to customer_logout without setting password
        logout_response = self.client.post(reverse("customer_logout"))
        self.assertRedirects(logout_response, reverse("home"))

        # User should be able to log in using email and phone number as password
        login_response = self.client.post(
            reverse("customer_login"),
            {"username": "rohan@example.com", "password": "+91 91234 56789"},
        )
        self.assertRedirects(login_response, reverse("customer_orders"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), order.customer.pk)

    def test_guest_checkout_adds_suffix_when_first_name_username_exists(self):
        get_user_model().objects.create_user(username="guest", password="ExistingPass!123")

        response = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            {
                "first_name": "Guest",
                "last_name": "Shopper",
                "email": "guest2@example.com",
                "phone": "+91 98765 43210",
                "address": "2 Guest Street",
                "city": "Mumbai",
                "state": "Maharashtra",
                "postal_code": "400001",
            },
        )

        order = Order.objects.get()
        self.assertEqual(order.customer.username, "guest1")
        self.assertRedirects(
            response,
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
        )

    def test_guest_ordering_twice_with_same_email_and_phone_uses_same_user(self):
        user_model = get_user_model()
        initial_user_count = user_model.objects.count()

        # First order as guest
        res1 = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            {
                "first_name": "Sanjeev",
                "last_name": "Kanth",
                "email": "sanjeev_test@example.com",
                "phone": "+91 98798 79879",
                "address": "No. 326 Main Road",
                "city": "Madurai",
                "state": "Tamil Nadu",
                "postal_code": "625018",
            },
        )
        self.assertEqual(res1.status_code, 302)
        self.assertEqual(user_model.objects.count(), initial_user_count + 1)
        created_user = user_model.objects.get(email="sanjeev_test@example.com")
        order1 = Order.objects.filter(customer=created_user).first()
        self.assertIsNotNone(order1)

        # Log out simulating a returning guest or new session
        self.client.logout()

        # Second order as guest with same email and phone
        res2 = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            {
                "first_name": "Sanjeev",
                "last_name": "Kanth",
                "email": "sanjeev_test@example.com",
                "phone": "+91 98798 79879",
                "address": "No. 326 Main Road",
                "city": "Madurai",
                "state": "Tamil Nadu",
                "postal_code": "625018",
            },
        )
        self.assertEqual(res2.status_code, 302)
        # Verify no second user was created
        self.assertEqual(user_model.objects.count(), initial_user_count + 1)

        # Both orders belong to the same user
        orders = list(Order.objects.filter(customer=created_user).order_by("id"))
        self.assertEqual(len(orders), 2)

        # In "My Orders", customer sees both orders
        orders_page = self.client.get(reverse("customer_orders"))
        self.assertEqual(orders_page.status_code, 200)
        self.assertContains(orders_page, f"Order #{orders[0].order_number or orders[0].id}")
        self.assertContains(orders_page, f"Order #{orders[1].order_number or orders[1].id}")

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
                "phone": "+91 98765 43210",
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
        self.assertContains(payment_page, "₹41.19")
        self.assertContains(payment_page, "₹370.00")
        self.assertContains(payment_page, "No card, bank, or UPI payment is made.")
        self.assertContains(payment_page, "payment-card--pending")
        self.assertContains(payment_page, "payment-status-hero--unpaid")
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "pending")
        self.assertEqual(order.quantity, 3)
        self.assertEqual(str(order.total_amount), "370.00")
        self.assertEqual(str(order.gst_amount), "41.19")
        self.assertEqual(str(order.shipping_fee), "100.00")
        self.assertEqual(order.delivery_address, "1 Test Street")
        self.assertEqual(order.customer_phone, "+91 98765 43210")
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
        self.assertContains(confirmation, "payment-card--paid")
        self.assertContains(confirmation, "payment-status-hero--paid")
        self.assertContains(confirmation, "Total paid")

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
        result = self.client.get(response.url)
        self.assertContains(result, "payment-card--failed")
        self.assertContains(result, "payment-status-hero--unpaid")

    @override_settings(
        PAYMENT_SIMULATION_ENABLED=False,
        RAZORPAY_ENABLED=False,
        RAZORPAY_KEY_ID="",
        RAZORPAY_KEY_SECRET="",
    )
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
        self.assertContains(response, 'data-product-image-link')
        self.assertContains(
            response,
            f'href="{reverse("product_detail", kwargs={"product_id": selected_product_id})}"',
        )
        self.assertContains(response, f'href="{reverse("about")}">')
        self.assertContains(response, "About us")
        self.assertContains(response, '<footer class="store-footer">')
        self.assertContains(response, 'href="mailto:support@jcsd.com"')
        self.assertContains(response, 'href="tel:+918056838888"')
        self.assertContains(response, 'href="https://wa.me/918056838888"')
        self.assertContains(response, f'href="{reverse("privacy_policy")}">Privacy policy</a>')
        self.assertContains(response, 'class="store-footer-mark"')
        self.assertNotContains(response, 'href="/customer-register/">Create account</a>')
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
        self.assertContains(product_response, 'class="back-link">← Back</a>')
        self.assertNotContains(product_response, 'data-scroll-cart')
        self.assertContains(product_response, "wishlist-access-button")
        self.assertContains(product_response, "Sign in")

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
        self.assertContains(response, '<footer class="store-footer">')


class ProductCategoryTests(TestCase):
    def test_product_category_assignment_and_display(self):
        cola = Product.objects.create(name="J Test Cola", price=90, image="main/images/cola.png")
        energy = Product.objects.create(name="J Energy Burst", price=95, image="main/images/energy.png")
        other = Product.objects.create(name="J Berry Punch", price=85, image="main/images/berry.png")

        self.assertEqual(cola.category_slug, "cola")
        self.assertEqual(cola.category_display, "Cola")
        self.assertEqual(energy.category_slug, "energy_drink")
        self.assertEqual(energy.category_display, "Energy Drink")
        self.assertEqual(other.category_slug, "others")
        self.assertEqual(other.category_display, "Others")

    def test_home_page_renders_category_filters(self):
        Product.objects.create(name="Super Cola", price=90, image="main/images/cola.png")
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-filter-category="all"')
        self.assertContains(response, 'data-filter-category="cola"')
        self.assertContains(response, 'data-filter-category="energy_drink"')
        self.assertContains(response, 'data-filter-category="others"')
        self.assertContains(response, "Cola")
        self.assertContains(response, "Energy Drink")
        self.assertContains(response, "Others")

    def test_product_detail_renders_category(self):
        product = Product.objects.create(name="Zap Energy Drink", price=100, image="main/images/cola.png")
        response = self.client.get(reverse("product_detail", kwargs={"product_id": product.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Energy Drink")


class PrivacyPolicyTests(TestCase):
    def test_privacy_policy_page_explains_store_data_use_and_contact(self):
        response = self.client.get(reverse("privacy_policy"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Privacy policy")
        self.assertContains(response, "delivery address")
        self.assertContains(response, "authorized store staff")
        self.assertContains(response, 'href="mailto:support@jcsd.com"')


class ContactPageTests(TestCase):
    def test_contact_page_renders_with_channels_form_and_nav(self):
        response = self.client.get(reverse("contact"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Contact us | J CSD")
        self.assertContains(response, "Let's connect.")
        self.assertContains(response, "support@jcsd.com")
        self.assertContains(response, "+91 80568 38888")
        self.assertContains(response, "Send a message")
        self.assertContains(response, 'action="/contact/"')

    def test_contact_form_submission_success(self):
        session = self.client.session
        session["contact_captcha"] = "TEST5"
        session.save()
        response = self.client.post(
            reverse("contact"),
            {
                "name": "Martin Benati",
                "email": "martin@example.com",
                "subject": "General inquiry",
                "message": "Love your drinks!",
                "captcha": "TEST5",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your message has been sent.")

    def test_contact_form_submission_fails_without_captcha(self):
        response = self.client.post(
            reverse("contact"),
            {
                "name": "Martin Benati",
                "email": "martin@example.com",
                "subject": "General inquiry",
                "message": "Love your drinks!",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incorrect security verification (CAPTCHA) code")

    def test_contact_form_submission_fails_with_wrong_captcha(self):
        session = self.client.session
        session["contact_captcha"] = "VALID"
        session.save()
        response = self.client.post(
            reverse("contact"),
            {
                "name": "Martin Benati",
                "email": "martin@example.com",
                "subject": "General inquiry",
                "message": "Love your drinks!",
                "captcha": "WRONG",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incorrect security verification (CAPTCHA) code")

    def test_captcha_image_generates_valid_png_and_stores_session(self):
        response = self.client.get(reverse("captcha_image"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertIn("contact_captcha", self.client.session)
        self.assertEqual(len(self.client.session["contact_captcha"]), 5)

    def test_captcha_is_consumed_each_time_preventing_replay(self):
        session = self.client.session
        session["contact_captcha"] = "CODE1"
        session.save()

        # First submit: valid
        res1 = self.client.post(
            reverse("contact"),
            {
                "name": "Martin Benati",
                "email": "martin@example.com",
                "subject": "General inquiry",
                "message": "First message",
                "captcha": "CODE1",
            },
        )
        self.assertEqual(res1.status_code, 200)
        self.assertContains(res1, "Your message has been sent.")

        # Second submit with the same captcha must fail
        res2 = self.client.post(
            reverse("contact"),
            {
                "name": "Martin Benati",
                "email": "martin@example.com",
                "subject": "General inquiry",
                "message": "Second message replay",
                "captcha": "CODE1",
            },
        )
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, "Incorrect security verification (CAPTCHA) code")

    def test_home_page_has_contact_us_button(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Contact us")
        self.assertContains(response, reverse("contact"))


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
            status="shipped",
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
        self.client.force_login(self.delivery_user)

        # Default landing page: Picked orders (first page)
        response_default = self.client.get(reverse("delivery_dashboard"))
        self.assertEqual(response_default.status_code, 200)
        self.assertEqual(response_default.context["active_tab"], "picked")
        self.assertContains(response_default, "Picked Orders")
        self.assertNotContains(response_default, "Stock Availability")

        # Tab: Orders which can be picked (shows pending and packed)
        response_available = self.client.get(f"{reverse('delivery_dashboard')}?tab=available")
        self.assertEqual(response_available.status_code, 200)
        self.assertEqual(response_available.context["active_tab"], "available")
        self.assertContains(response_available, "Delivery Cola")
        self.assertContains(response_available, "12 Example Road")
        self.assertContains(response_available, "400001")
        self.assertContains(response_available, "Orders to Pick")
        self.assertNotContains(response_available, "Stock Availability")

        # Stock availability is removed for delivery partners; tab=stock defaults to picked
        response_stock = self.client.get(f"{reverse('delivery_dashboard')}?tab=stock")
        self.assertEqual(response_stock.status_code, 200)
        self.assertEqual(response_stock.context["active_tab"], "picked")
        self.assertNotContains(response_stock, "Stock Availability")

    def test_delivery_user_can_return_to_dashboard_from_store_pages(self):
        self.client.force_login(self.delivery_user)

        home = self.client.get(reverse("home"))
        product = self.client.get(
            reverse("product_detail", kwargs={"product_id": self.product.pk})
        )

        self.assertContains(home, reverse("delivery_dashboard"))
        self.assertContains(home, "Delivery dashboard")
        self.assertContains(product, 'class="back-link">← Back</a>')
        self.assertContains(product, reverse("delivery_dashboard"))

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
        self.assertEqual(self.order.status, "shipped")

    def test_picking_order_automatically_marks_out_for_delivery_and_hides_from_others(self):
        other_driver_user = get_user_model().objects.create_user(
            username="other-driver",
            email="other@example.com",
            password="driver-password",
        )
        DeliveryProfile.objects.create(user=other_driver_user)

        # 1. First driver views available orders and sees self.order
        self.client.force_login(self.delivery_user)
        resp1 = self.client.get(f"{reverse('delivery_dashboard')}?tab=available")
        self.assertContains(resp1, f"Order #{self.order.order_number or self.order.pk}")

        # 2. First driver picks the order
        pick_resp = self.client.post(
            reverse("pick_delivery_order", kwargs={"order_id": self.order.pk})
        )
        self.assertRedirects(pick_resp, f"{reverse('delivery_dashboard')}?tab=picked")

        # Verify order state: assigned to delivery_user and status is out_for_delivery
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_user, self.delivery_user)
        self.assertEqual(self.order.status, "out_for_delivery")

        # 3. Second driver logs in: order must NOT be visible in Orders to Pick
        self.client.force_login(other_driver_user)
        resp2 = self.client.get(f"{reverse('delivery_dashboard')}?tab=available")
        self.assertNotContains(resp2, f"Order #{self.order.order_number or self.order.pk} ·")

        # 4. Second driver tries to pick the already-picked order: rejected
        double_pick = self.client.post(
            reverse("pick_delivery_order", kwargs={"order_id": self.order.pk})
        )
        self.assertRedirects(double_pick, f"{reverse('delivery_dashboard')}?tab=available")
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_user, self.delivery_user)

    def test_delivery_user_can_update_order_to_delivered_or_returned(self):
        self.order.delivery_user = self.delivery_user
        self.order.status = "out_for_delivery"
        self.order.save(update_fields=["delivery_user", "status"])

        self.client.force_login(self.delivery_user)

        # Mark Delivered
        response = self.client.post(
            reverse("update_delivery_status", kwargs={"order_id": self.order.pk}),
            {"status": "delivered"},
        )
        self.assertRedirects(response, f"{reverse('delivery_dashboard')}?tab=picked")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "delivered")
        self.assertIsNotNone(self.order.delivered_at)

        # Mark Returned / Cancelled
        response_return = self.client.post(
            reverse("update_delivery_status", kwargs={"order_id": self.order.pk}),
            {"status": "cancelled"},
        )
        self.assertRedirects(response_return, f"{reverse('delivery_dashboard')}?tab=picked")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "cancelled")
        self.assertIsNone(self.order.delivered_at)

    def test_delivery_user_cannot_set_status_to_packed(self):
        self.order.delivery_user = self.delivery_user
        self.order.status = "out_for_delivery"
        self.order.save(update_fields=["delivery_user", "status"])

        self.client.force_login(self.delivery_user)

        # Attempt to set status to packed (only admin can pack)
        response = self.client.post(
            reverse("update_delivery_status", kwargs={"order_id": self.order.pk}),
            {"status": "packed"},
        )
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "out_for_delivery")

    def test_admin_can_update_status_to_packed(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin_update_order_status", kwargs={"order_id": self.order.pk}),
            {"status": "packed"},
        )
        self.assertRedirects(response, reverse("admin_delivery_status"))
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "packed")

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

    def test_cart_item_can_be_moved_to_wishlist(self):
        self.add_item(self.cola, "1")
        self.add_item(self.lime, "2")

        response = self.client.post(
            reverse("update_cart"),
            {"action": "move_to_wishlist", "product_id": str(self.cola.id)},
            follow=True,
        )
        self.assertRedirects(response, reverse("cart"))
        self.assertNotIn(str(self.cola.id), self.client.session.get("cart", {}))
        self.assertIn(str(self.cola.id), self.client.session.get("wishlist", []))
        self.assertNotContains(response, f'id="quantity-{self.cola.id}"')
        self.assertContains(response, f'id="quantity-{self.lime.id}"')
        self.assertContains(response, "Cart Cola added to your wishlist.")

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
        data = response.json()
        self.assertEqual(data["cart_count"], 5)
        self.assertEqual(data["cart_total"], "470.00")
        self.assertEqual(data["gst_amount"], "71.70")
        self.assertEqual(data["packing_fee"], "0.00")
        self.assertEqual(
            data["items"],
            [
                {"product_id": self.cola.id, "quantity": 4, "line_total": "360.00"},
                {"product_id": self.lime.id, "quantity": 1, "line_total": "110.00"},
            ],
        )
        self.assertFalse(data["combo_active"])

    def test_ajax_cart_quantity_update_calculates_packing_fee_dynamically(self):
        self.add_item(self.cola, "1")
        response = self.client.post(
            reverse("update_cart"),
            {
                "action": "update",
                f"quantity_{self.cola.id}": "13",
            },
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["cart_count"], 13)
        self.assertEqual(data["packing_fee"], "40.00")

    def test_cart_page_renders_right_side_checkout_summary(self):
        self.add_item(self.cola, "1")
        response = self.client.get(reverse("cart"))
        self.assertContains(response, "checkout-summary-sticky")
        self.assertContains(response, "cartSubtotalDisplay")
        self.assertContains(response, "cartPackingFeeDisplay")
        self.assertContains(response, "cartShippingFeeDisplay")
        self.assertContains(response, "cartGrandTotalDisplay")
        self.assertContains(response, "data-cart-checkout-total")

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
                "phone": "+91 98765 43210",
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
        self.assertEqual(order.total_amount, Decimal("390.00"))
        self.assertEqual(order.gst_amount, Decimal("44.24"))
        self.assertEqual(order.shipping_fee, Decimal("100.00"))
        self.assertEqual(order.items_subtotal, Decimal("290.00"))
        self.assertEqual(order.quantity, 3)
        self.assertEqual(order.customer_phone, "+91 98765 43210")
        self.assertEqual(order.delivery_address, "1 Cart Street")
        self.assertEqual(order.delivery_city, "Pune")
        self.assertEqual(order.delivery_state, "Maharashtra")
        self.assertEqual(order.delivery_postal_code, "411001")
        self.assertEqual(order.items.count(), 2)
        payment_page = self.client.get(response.url)
        self.assertContains(payment_page, "Cart Cola")
        self.assertContains(payment_page, "Cart Lime")
        self.assertContains(payment_page, "₹290.00")
        self.assertContains(payment_page, "₹390.00")
        self.assertEqual(self.client.get(reverse("cart")).context["items"], [])

    def test_cart_checkout_rejects_missing_delivery_details_and_keeps_cart(self):
        self.add_item(self.cola, "2")

        response = self.client.post(
            reverse("cart_checkout"),
            {"first_name": "Cart", "last_name": "Customer"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.client.get(reverse("cart")).context["cart_count"], 2)

    def test_guest_can_checkout_cart_and_view_payment_by_order_reference(self):
        self.add_item(self.cola, "2")

        response = self.client.post(
            reverse("cart_checkout"),
            {
                "first_name": "Guest",
                "last_name": "Customer",
                "email": "guest.cart@example.com",
                "phone": "+91 98765 43210",
                "address": "1 Guest Street",
                "city": "Pune",
                "state": "Maharashtra",
                "postal_code": "411001",
            },
        )

        order = Order.objects.get()
        self.assertIsNotNone(order.customer)
        self.assertEqual(order.customer.username, "guest")
        self.assertEqual(order.customer_name, "Guest Customer")
        self.assertEqual(order.customer_phone, "+91 98765 43210")
        self.assertRedirects(
            response,
            reverse("payment_page", kwargs={"payment_reference": order.payment_reference}),
        )
        self.assertEqual(self.client.get(response.url).status_code, 200)
        self.assertEqual(self.client.get(reverse("cart")).context["items"], [])

    def test_cart_shows_checkout_form_without_customer_login(self):
        self.add_item(self.cola, "1")

        response = self.client.get(reverse("cart"))

        self.assertContains(response, 'id="cart-checkout"')
        self.assertContains(response, 'name="phone"')
        self.assertNotContains(response, "Sign in to checkout")

    def test_cart_rejects_invalid_quantity(self):
        response = self.add_item(self.cola, "0")

        self.assertEqual(response.status_code, 400)


class WishlistTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = Product.objects.create(
            name="Wishlist Cola",
            description="Wishlist test product",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
        )

    def test_guest_can_save_product_and_view_wishlist(self):
        response = self.client.post(
            reverse("wishlist_toggle", kwargs={"product_id": self.product.pk}),
            {"action": "toggle", "next": reverse("product_detail", kwargs={"product_id": self.product.pk})},
        )

        self.assertRedirects(
            response,
            reverse("product_detail", kwargs={"product_id": self.product.pk}),
        )
        self.assertEqual(self.client.session["wishlist"], [str(self.product.pk)])
        wishlist = self.client.get(reverse("wishlist"))
        self.assertContains(wishlist, "My wishlist")
        self.assertContains(wishlist, "Wishlist Cola")
        self.assertContains(wishlist, "wishlist is saved for this browser session")

    def test_wishlist_toggle_removes_saved_product(self):
        self.client.post(
            reverse("wishlist_toggle", kwargs={"product_id": self.product.pk}),
            {"action": "add"},
        )

        response = self.client.post(
            reverse("wishlist_toggle", kwargs={"product_id": self.product.pk}),
            {"action": "toggle", "next": reverse("wishlist")},
        )

        self.assertRedirects(response, reverse("wishlist"))
        self.assertEqual(self.client.session["wishlist"], [])
        self.assertContains(self.client.get(response.url), "Your wishlist is empty")

    def test_wishlist_remove_and_invalid_action(self):
        self.client.post(
            reverse("wishlist_toggle", kwargs={"product_id": self.product.pk}),
            {"action": "add"},
        )
        remove_response = self.client.post(
            reverse("wishlist_toggle", kwargs={"product_id": self.product.pk}),
            {"action": "remove", "next": reverse("wishlist")},
        )
        self.assertRedirects(remove_response, reverse("wishlist"))
        self.assertEqual(self.client.session["wishlist"], [])

        invalid_response = self.client.post(
            reverse("wishlist_toggle", kwargs={"product_id": self.product.pk}),
            {"action": "unknown"},
        )
        self.assertEqual(invalid_response.status_code, 400)

    def test_home_and_product_page_have_wishlist_controls_and_count(self):
        home = self.client.get(reverse("home"))
        product_page = self.client.get(
            reverse("product_detail", kwargs={"product_id": self.product.pk})
        )

        self.assertContains(home, 'aria-label="Wishlist, 0 saved items"')
        self.assertContains(home, "♡ Wishlist")
        self.assertContains(home, reverse("wishlist_toggle", kwargs={"product_id": self.product.pk}))
        self.assertContains(product_page, "♡ Add to wishlist")
        self.assertContains(product_page, 'aria-label="Wishlist, 0 saved items"')
        self.assertContains(product_page, 'class="back-link">← Back</a>')

    def test_wishlist_discards_unavailable_products(self):
        unavailable = Product.objects.create(
            name="Unavailable wishlist drink",
            description="Not available",
            price="90.00",
            volume="330 ml",
            image="main/images/cola.png",
            available=False,
        )
        self.client.post(
            reverse("wishlist_toggle", kwargs={"product_id": self.product.pk}),
            {"action": "add"},
        )
        session = self.client.session
        session["wishlist"] = [str(unavailable.pk), str(self.product.pk)]
        session.save()

        response = self.client.get(reverse("wishlist"))

        self.assertContains(response, "Wishlist Cola")
        self.assertNotContains(response, "Unavailable wishlist drink")
        self.assertEqual(self.client.session["wishlist"], [str(self.product.pk)])


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


class AddressButtonTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="testuser",
            email="testuser@example.com",
            password="password123",
            first_name="Test",
            last_name="Customer",
        )
        self.product = Product.objects.create(
            name="Classic Lemonade",
            description="Freshly squeezed lemonade.",
            price=Decimal("90.00"),
            volume="330 ml",
            image="main/images/cola.png",
            available=True,
        )

    def test_cart_page_renders_add_address_button(self):
        session = self.client.session
        session["cart"] = {str(self.product.id): 1}
        session.save()

        response = self.client.get(reverse("cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "+ Add address")
        self.assertContains(response, 'id="btn-add-address"')

    def test_checkout_page_renders_add_address_button(self):
        response = self.client.get(reverse("checkout", kwargs={"product_id": self.product.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "+ Add address")
        self.assertContains(response, 'id="btn-add-address"')

    def test_saved_address_shown_for_profile_user(self):
        CustomerProfile.objects.create(
            user=self.user,
            phone="9876543210",
            address="123 Palm Street",
            city="Chennai",
            state="TN",
            postal_code="600001",
        )
        self.client.force_login(self.user)
        session = self.client.session
        session["cart"] = {str(self.product.id): 1}
        session.save()

        response = self.client.get(reverse("cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Default saved address")
        self.assertContains(response, "123 Palm Street")
        self.assertContains(response, "Use saved address")

    def test_checkout_saves_address_to_profile_when_requested(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["cart"] = {str(self.product.id): 1}
        session.save()

        response = self.client.post(
            reverse("cart_checkout"),
            data={
                "first_name": "Test",
                "last_name": "Customer",
                "email": "testuser@example.com",
                "phone": "9998887776",
                "address": "456 New Lane",
                "city": "Bengaluru",
                "state": "KA",
                "postal_code": "560001",
                "save_address_to_profile": "1",
            },
        )
        self.assertEqual(response.status_code, 302)
        profile = CustomerProfile.objects.get(user=self.user)
        self.assertEqual(profile.address, "456 New Lane")
        self.assertEqual(profile.city, "Bengaluru")
        self.assertEqual(profile.state, "KA")
        self.assertEqual(profile.postal_code, "560001")


class SavedAddressTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="addressuser",
            email="addressuser@example.com",
            password="testpassword123",
            first_name="Address",
            last_name="Tester",
        )
        self.product = Product.objects.create(
            name="Glow Serum",
            description="Hydrating skincare",
            price=Decimal("49.99"),
            volume="50ml",
            image="main/images/cola.png",
            available=True,
        )

    def test_view_saved_addresses_in_profile(self):
        self.client.force_login(self.user)
        CustomerAddress.objects.create(
            user=self.user,
            full_name="Home",
            phone="9876543210",
            address="101 Ocean Drive",
            city="Mumbai",
            state="MH",
            postal_code="400001",
            is_default=True,
        )
        CustomerAddress.objects.create(
            user=self.user,
            full_name="Office",
            phone="9876543211",
            address="202 Tech Park",
            city="Pune",
            state="MH",
            postal_code="411001",
            is_default=False,
        )

        response = self.client.get(reverse("customer_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Saved Delivery Addresses (2/5)")
        self.assertContains(response, "101 Ocean Drive")
        self.assertContains(response, "202 Tech Park")
        self.assertContains(response, "Default")

    def test_add_address_via_profile_up_to_five(self):
        self.client.force_login(self.user)
        # Add 5 addresses
        for i in range(1, 6):
            res = self.client.post(
                reverse("customer_profile"),
                data={
                    "action": "add_address",
                    "full_name": f"Address {i}",
                    "phone": f"900000000{i}",
                    "address": f"{i} Street",
                    "city": "City",
                    "state": "State",
                    "postal_code": f"11000{i}",
                    "is_default": "on" if i == 1 else "",
                },
            )
            self.assertEqual(res.status_code, 302)

        self.assertEqual(CustomerAddress.objects.filter(user=self.user).count(), 5)

        # Attempt to add 6th address
        res6 = self.client.post(
            reverse("customer_profile"),
            data={
                "action": "add_address",
                "full_name": "Address 6",
                "phone": "9000000006",
                "address": "6 Street",
                "city": "City",
                "state": "State",
                "postal_code": "110006",
            },
        )
        self.assertEqual(res6.status_code, 302)
        # Count should still be capped at 5
        self.assertEqual(CustomerAddress.objects.filter(user=self.user).count(), 5)

    def test_set_default_address(self):
        self.client.force_login(self.user)
        addr1 = CustomerAddress.objects.create(
            user=self.user,
            address="First Address",
            city="City A",
            state="State A",
            postal_code="100001",
            is_default=True,
        )
        addr2 = CustomerAddress.objects.create(
            user=self.user,
            address="Second Address",
            city="City B",
            state="State B",
            postal_code="200002",
            is_default=False,
        )

        res = self.client.post(
            reverse("customer_profile"),
            data={"action": "set_default_address", "address_id": addr2.id},
        )
        self.assertEqual(res.status_code, 302)
        addr1.refresh_from_db()
        addr2.refresh_from_db()
        self.assertFalse(addr1.is_default)
        self.assertTrue(addr2.is_default)

        # Check CustomerProfile is synced
        profile = CustomerProfile.objects.get(user=self.user)
        self.assertEqual(profile.address, "Second Address")

    def test_delete_address(self):
        self.client.force_login(self.user)
        addr = CustomerAddress.objects.create(
            user=self.user,
            address="Delete Me Street",
            city="City",
            state="State",
            postal_code="123456",
            is_default=True,
        )

        res = self.client.post(
            reverse("customer_profile"),
            data={"action": "delete_address", "address_id": addr.id},
        )
        self.assertEqual(res.status_code, 302)
        self.assertFalse(CustomerAddress.objects.filter(id=addr.id).exists())

    def test_checkout_and_cart_show_saved_address_options(self):
        self.client.force_login(self.user)
        CustomerAddress.objects.create(
            user=self.user,
            full_name="Home Address",
            phone="9876543210",
            address="77 Marina Way",
            city="Kochi",
            state="KL",
            postal_code="682001",
            is_default=True,
        )
        CustomerAddress.objects.create(
            user=self.user,
            full_name="Office Address",
            phone="9876543211",
            address="88 Infopark",
            city="Kochi",
            state="KL",
            postal_code="682042",
            is_default=False,
        )

        # In Checkout
        checkout_res = self.client.get(
            reverse("checkout", kwargs={"product_id": self.product.id})
        )
        self.assertEqual(checkout_res.status_code, 200)
        self.assertContains(checkout_res, "Choose delivery address (2/5 saved)")
        self.assertContains(checkout_res, "77 Marina Way")
        self.assertContains(checkout_res, "88 Infopark")
        self.assertContains(checkout_res, "+ Add address")

        # In Cart
        session = self.client.session
        session["cart"] = {str(self.product.id): 1}
        session.save()

        cart_res = self.client.get(reverse("cart"))
        self.assertEqual(cart_res.status_code, 200)
        self.assertContains(cart_res, "Choose delivery address (2/5 saved)")
        self.assertContains(cart_res, "77 Marina Way")
        self.assertContains(cart_res, "88 Infopark")
        self.assertContains(cart_res, "+ Add address")

    def test_profile_shows_and_updates_email(self):
        self.client.force_login(self.user)
        res = self.client.get(reverse("customer_profile"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'name="email"')
        self.assertContains(res, "addressuser@example.com")

        update_res = self.client.post(
            reverse("customer_profile"),
            data={
                "action": "save_profile",
                "username": "addressuser",
                "email": "updated_email@example.com",
                "first_name": "Updated",
                "last_name": "Name",
                "phone": "9876543210",
                "address": "123 Street",
                "city": "City",
                "state": "State",
                "postal_code": "123456",
            },
        )
        self.assertEqual(update_res.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "updated_email@example.com")

    def test_profile_photo_upload_and_removal(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.force_login(self.user)
        # Create a small valid 1x1 GIF image bytes
        gif_bytes = (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04"
            b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        avatar_file = SimpleUploadedFile(
            "test_avatar.gif", gif_bytes, content_type="image/gif"
        )

        res = self.client.post(
            reverse("customer_profile"),
            data={
                "action": "save_profile",
                "username": "addressuser",
                "email": "addressuser@example.com",
                "first_name": "Address",
                "last_name": "Tester",
                "avatar": avatar_file,
            },
        )
        self.assertEqual(res.status_code, 302)
        profile = CustomerProfile.objects.get(user=self.user)
        self.assertTrue(bool(profile.avatar))

        # Test remove profile photo
        remove_res = self.client.post(
            reverse("customer_profile"),
            data={
                "action": "save_profile",
                "username": "addressuser",
                "email": "addressuser@example.com",
                "first_name": "Address",
                "last_name": "Tester",
                "remove_avatar": "1",
            },
        )
        self.assertEqual(remove_res.status_code, 302)
        profile.refresh_from_db()
        self.assertFalse(bool(profile.avatar))


class AdminMultipageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff_user = get_user_model().objects.create_user(
            username="adminstaff",
            email="adminstaff@example.com",
            password="staff-password",
            is_staff=True,
        )
        cls.regular_user = get_user_model().objects.create_user(
            username="regularuser",
            email="regular@example.com",
            password="user-password",
            is_staff=False,
        )
        cls.product = Product.objects.create(
            name="Sparkling Fizz",
            category="others",
            description="Crisp and refreshing",
            price=Decimal("85.00"),
            volume="330 ml",
            image="sparkling.png",
            available=True,
        )

    def test_non_staff_redirected_from_admin_pages(self):
        self.client.login(username="regularuser", password="user-password")
        for url_name in ("admin_products", "admin_delivery_users", "admin_delivery_status"):
            with self.subTest(url_name=url_name):
                res = self.client.get(reverse(url_name))
                self.assertEqual(res.status_code, 302)

    def test_staff_can_view_and_add_products(self):
        self.client.login(username="adminstaff", password="staff-password")
        res = self.client.get(reverse("admin_products"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Sparkling Fizz")
        self.assertContains(res, "products-stats-grid")
        self.assertContains(res, "stats-grid-3")

        # Add new product
        post_res = self.client.post(
            reverse("admin_products"),
            data={
                "name": "Berry Blast",
                "category": "energy_drink",
                "description": "Wild berry flavor",
                "price": "95.00",
                "volume": "330 ml",
                "image": "berry.png",
                "available": True,
            },
        )
        self.assertRedirects(post_res, reverse("admin_products"))
        self.assertTrue(Product.objects.filter(name="Berry Blast").exists())

    def test_staff_can_toggle_product_availability(self):
        self.client.login(username="adminstaff", password="staff-password")
        self.assertTrue(self.product.available)

        toggle_res = self.client.post(
            reverse("admin_toggle_product_availability", kwargs={"product_id": self.product.id})
        )
        self.assertRedirects(toggle_res, reverse("admin_products"))
        self.product.refresh_from_db()
        self.assertFalse(self.product.available)

        # Toggle back to True
        toggle_back = self.client.post(
            reverse("admin_toggle_product_availability", kwargs={"product_id": self.product.id})
        )
        self.assertRedirects(toggle_back, reverse("admin_products"))
        self.product.refresh_from_db()
        self.assertTrue(self.product.available)

    def test_staff_can_add_custom_category_and_product(self):
        self.client.login(username="adminstaff", password="staff-password")
        # 1. Quick add category
        cat_res = self.client.post(
            reverse("admin_products"),
            data={"action": "add_category", "new_category_name": "Sparkling Water"},
        )
        self.assertRedirects(cat_res, reverse("admin_products"))
        self.assertTrue(ProductCategory.objects.filter(slug="sparkling_water").exists())

        # 2. Add product with inline new category
        prod_res = self.client.post(
            reverse("admin_products"),
            data={
                "name": "Tropical Punch",
                "category": "__new__",
                "new_category": "Fruit Juice",
                "description": "Exotic fruits",
                "price": "110.00",
                "volume": "330 ml",
                "available": True,
            },
        )
        self.assertRedirects(prod_res, reverse("admin_products"))
        punch = Product.objects.get(name="Tropical Punch")
        self.assertEqual(punch.category, "fruit_juice")
        self.assertEqual(punch.category_display, "Fruit Juice")

        # 3. Storefront displays custom category filter
        home_res = self.client.get(reverse("home"))
        self.assertContains(home_res, 'data-filter-category="sparkling_water"')
        self.assertContains(home_res, 'data-filter-category="fruit_juice"')
        self.assertContains(home_res, "Fruit Juice")

    def test_staff_can_upload_product_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        self.client.login(username="adminstaff", password="staff-password")
        gif_bytes = (
            b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00!\xf9\x04"
            b"\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        )
        drink_img = SimpleUploadedFile("fresh_drink.gif", gif_bytes, content_type="image/gif")

        post_res = self.client.post(
            reverse("admin_products"),
            data={
                "name": "Lime Spritz",
                "category": "others",
                "description": "Zesty and fresh",
                "price": "85.00",
                "volume": "330 ml",
                "image_file": drink_img,
                "available": True,
            },
        )
        self.assertRedirects(post_res, reverse("admin_products"))
        spritz = Product.objects.get(name="Lime Spritz")
        self.assertTrue(spritz.image.startswith("/media/products/fresh_drink"))
        self.assertTrue(spritz.image_url.startswith("/media/products/fresh_drink"))

    def test_staff_can_view_and_add_delivery_users(self):
        self.client.login(username="adminstaff", password="staff-password")
        res = self.client.get(reverse("admin_delivery_users"))
        self.assertEqual(res.status_code, 200)

        post_res = self.client.post(
            reverse("admin_delivery_users"),
            data={
                "username": "deliverydriver1",
                "email": "driver1@example.com",
                "first_name": "Dave",
                "last_name": "Driver",
                "password1": "DriverPass123!",
                "password2": "DriverPass123!",
            },
        )
        self.assertRedirects(post_res, reverse("admin_delivery_users"))
        new_driver = get_user_model().objects.get(username="deliverydriver1")
        self.assertTrue(DeliveryProfile.objects.filter(user=new_driver).exists())

    def test_staff_can_view_and_update_delivery_status(self):
        self.client.login(username="adminstaff", password="staff-password")
        order = Order.objects.create(
            product=self.product,
            customer_name="John Doe",
            customer_phone="9876543210",
            delivery_address="123 Street",
            delivery_city="Bengaluru",
            delivery_state="KA",
            delivery_postal_code="560001",
            quantity=2,
            total_amount=Decimal("170.00"),
            status="pending",
        )

        res = self.client.get(reverse("admin_delivery_status"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, f"#{order.order_number or order.id}")
        self.assertContains(res, "John Doe")

        # Update order status to out_for_delivery
        update_res = self.client.post(
            reverse("admin_update_order_status", kwargs={"order_id": order.id}),
            data={"status": "out_for_delivery"},
        )
        self.assertRedirects(update_res, reverse("admin_delivery_status"))
        order.refresh_from_db()
        self.assertEqual(order.status, "out_for_delivery")
        self.assertIsNone(order.delivered_at)

        # Update to delivered
        deliver_res = self.client.post(
            reverse("admin_update_order_status", kwargs={"order_id": order.id}),
            data={"status": "delivered"},
        )
        self.assertRedirects(deliver_res, reverse("admin_delivery_status"))
        order.refresh_from_db()
        self.assertEqual(order.status, "delivered")
        self.assertIsNotNone(order.delivered_at)

    def test_user_can_submit_contact_message_and_staff_can_view_it(self):
        # 1. Anonymous / regular customer submits contact form
        session = self.client.session
        session["contact_captcha"] = "TEST5"
        session.save()
        contact_res = self.client.post(
            reverse("contact"),
            data={
                "name": "Sarah Connor",
                "email": "sarah@example.com",
                "subject": "Wholesale inquiry",
                "message": "We would like to stock J CSD at our cafe.",
                "captcha": "TEST5",
            },
        )
        self.assertEqual(contact_res.status_code, 200)
        self.assertTrue(
            ContactMessage.objects.filter(email="sarah@example.com", name="Sarah Connor").exists()
        )
        msg = ContactMessage.objects.get(email="sarah@example.com")
        self.assertFalse(msg.is_read)

        # 2. Staff views details & messages page
        self.client.login(username="adminstaff", password="staff-password")
        admin_res = self.client.get(reverse("admin_details") + "?tab=messages")
        self.assertEqual(admin_res.status_code, 200)
        self.assertContains(admin_res, "Sarah Connor")
        self.assertContains(admin_res, "Wholesale inquiry")
        self.assertContains(admin_res, "We would like to stock J CSD at our cafe.")

        # 3. Staff marks message as read
        toggle_res = self.client.post(
            reverse("admin_toggle_message_read", kwargs={"message_id": msg.id})
        )
        self.assertRedirects(toggle_res, reverse("admin_details") + "?tab=messages")
        msg.refresh_from_db()
        self.assertTrue(msg.is_read)

        # 4. Staff deletes message
        delete_res = self.client.post(
            reverse("admin_delete_message", kwargs={"message_id": msg.id})
        )
        self.assertRedirects(delete_res, reverse("admin_details") + "?tab=messages")
        self.assertFalse(ContactMessage.objects.filter(pk=msg.id).exists())

    def test_staff_can_edit_about_us_details(self):
        self.client.login(username="adminstaff", password="staff-password")
        post_res = self.client.post(
            reverse("admin_details") + "?tab=about",
            data={
                "action": "save_about",
                "about_kicker": "Our Story",
                "about_title": "Pure Energy.<br>Pure Vibes.",
                "about_lead": "Crafted with botanical extracts for the modern creator.",
                "about_note": "Every can is a burst of natural energy.",
                "about_action_text": "Check line-up",
                "about_action_url": "/#drinks",
            },
        )
        self.assertRedirects(post_res, reverse("admin_details") + "?tab=about")

        details = SiteDetails.get_solo()
        self.assertEqual(details.about_kicker, "Our Story")
        self.assertEqual(details.about_title, "Pure Energy.<br>Pure Vibes.")

        # Check that about page renders the new values
        about_res = self.client.get(reverse("about"))
        self.assertEqual(about_res.status_code, 200)
        self.assertContains(about_res, "Our Story")
        self.assertContains(about_res, "Pure Energy.<br>Pure Vibes.")
        self.assertContains(about_res, "Crafted with botanical extracts for the modern creator.")

    def test_staff_can_edit_contact_us_details(self):
        self.client.login(username="adminstaff", password="staff-password")
        post_res = self.client.post(
            reverse("admin_details") + "?tab=contact",
            data={
                "action": "save_contact",
                "contact_kicker": "Reach Out",
                "contact_title": "Always Here To Help.",
                "contact_lead": "Get in touch with our beverage care team anytime.",
                "support_email": "help@jcsd-drinks.com",
                "support_phone": "+91 99999 88888",
                "whatsapp_number": "+91 99999 88888",
                "operating_hours": "Mon-Fri: 8am - 10pm",
            },
        )
        self.assertRedirects(post_res, reverse("admin_details") + "?tab=contact")

        details = SiteDetails.get_solo()
        self.assertEqual(details.support_email, "help@jcsd-drinks.com")
        self.assertEqual(details.support_phone, "+91 99999 88888")

        # Check that contact page renders the new values
        contact_res = self.client.get(reverse("contact"))
        self.assertEqual(contact_res.status_code, 200)
        self.assertContains(contact_res, "Always Here To Help.")
        self.assertContains(contact_res, "help@jcsd-drinks.com")
        self.assertContains(contact_res, "+91 99999 88888")


class ShippingFeeAndRegionalRulesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff_user = get_user_model().objects.create_user(
            username="adminstaff_ship",
            email="admin_ship@example.com",
            password="staff-password",
            is_staff=True,
        )
        cls.product = Product.objects.create(
            name="Shipping Test Drink",
            price=Decimal("150.00"),
            volume="330 ml",
            image="main/images/cola.png",
            available=True,
        )

    def test_default_shipping_fees_for_local_and_other_states(self):
        details = SiteDetails.get_solo()
        # Tamil Nadu & Kerala should be ₹50
        self.assertEqual(details.calculate_shipping_fee("Tamil Nadu"), Decimal("50.00"))
        self.assertEqual(details.calculate_shipping_fee("tamil nadu"), Decimal("50.00"))
        self.assertEqual(details.calculate_shipping_fee("Kerala"), Decimal("50.00"))
        self.assertEqual(details.calculate_shipping_fee("kerala"), Decimal("50.00"))

        # Other states should be ₹100
        self.assertEqual(details.calculate_shipping_fee("Karnataka"), Decimal("100.00"))
        self.assertEqual(details.calculate_shipping_fee("Maharashtra"), Decimal("100.00"))
        self.assertEqual(details.calculate_shipping_fee("Delhi"), Decimal("100.00"))

    def test_checkout_applies_correct_shipping_fee_tamil_nadu(self):
        response = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            {
                "first_name": "Radhi",
                "last_name": "Kumar",
                "email": "radhi@example.com",
                "phone": "9842176565",
                "address": "123 Anna Salai",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "postal_code": "600002",
            },
        )
        order = Order.objects.filter(customer_phone="+91 9842176565").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.shipping_fee, Decimal("50.00"))
        self.assertEqual(order.items_subtotal, Decimal("150.00"))
        self.assertEqual(order.gst_amount, Decimal("22.88"))
        self.assertEqual(order.total_amount, Decimal("200.00"))
        self.assertEqual(order.customer_phone, "+91 9842176565")

    def test_checkout_applies_correct_shipping_fee_other_state(self):
        response = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            {
                "first_name": "Rohan",
                "last_name": "Sharma",
                "email": "rohan@example.com",
                "phone": "9876543210",
                "address": "456 MG Road",
                "city": "Bengaluru",
                "state": "Karnataka",
                "postal_code": "560001",
            },
        )
        order = Order.objects.filter(customer_phone="+91 9876543210").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.shipping_fee, Decimal("100.00"))
        self.assertEqual(order.items_subtotal, Decimal("150.00"))
        self.assertEqual(order.gst_amount, Decimal("22.88"))
        self.assertEqual(order.total_amount, Decimal("250.00"))

    def test_admin_can_customize_shipping_rates_and_local_states(self):
        self.client.login(username="adminstaff_ship", password="staff-password")
        post_res = self.client.post(
            reverse("admin_shipping_charges"),
            data={
                "shipping_fee_local": "40.00",
                "shipping_fee_other": "120.00",
                "shipping_local_states": "Tamil Nadu, Kerala, Pondicherry",
            },
        )
        self.assertRedirects(post_res, reverse("admin_shipping_charges"))

        details = SiteDetails.get_solo()
        self.assertEqual(details.shipping_fee_local, Decimal("40.00"))
        self.assertEqual(details.shipping_fee_other, Decimal("120.00"))
        self.assertIn("Pondicherry", details.shipping_local_states)

        # Now Pondicherry gets ₹40, and Karnataka gets ₹120
        self.assertEqual(details.calculate_shipping_fee("Pondicherry"), Decimal("40.00"))
        self.assertEqual(details.calculate_shipping_fee("Karnataka"), Decimal("120.00"))

    def test_packing_cost_calculation_tiers(self):
        details = SiteDetails.get_solo()
        # Default: first 6 cans free, +₹20 per 6 cans thereafter
        self.assertEqual(details.calculate_packing_fee(0), Decimal("0.00"))
        self.assertEqual(details.calculate_packing_fee(1), Decimal("0.00"))
        self.assertEqual(details.calculate_packing_fee(5), Decimal("0.00"))
        self.assertEqual(details.calculate_packing_fee(6), Decimal("0.00"))

        # 7 to 12 cans = 1 additional pack = ₹20
        self.assertEqual(details.calculate_packing_fee(7), Decimal("20.00"))
        self.assertEqual(details.calculate_packing_fee(10), Decimal("20.00"))
        self.assertEqual(details.calculate_packing_fee(12), Decimal("20.00"))

        # 13 to 18 cans = 2 additional packs = ₹40
        self.assertEqual(details.calculate_packing_fee(13), Decimal("40.00"))
        self.assertEqual(details.calculate_packing_fee(18), Decimal("40.00"))

        # 19 cans = 3 additional packs = ₹60
        self.assertEqual(details.calculate_packing_fee(19), Decimal("60.00"))

    def test_checkout_applies_packing_cost_and_no_local_labeling(self):
        # 8 cans = 6 free + 2 extra (1 pack) = ₹20 packing cost
        response = self.client.post(
            f"/checkout/{self.product.id}/?qty=8",
            {
                "first_name": "Radhi",
                "last_name": "Kumar",
                "email": "radhi_packing@example.com",
                "phone": "9842176565",
                "address": "123 Anna Salai",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "postal_code": "600002",
            },
        )
        self.assertEqual(response.status_code, 302)
        order = Order.objects.filter(customer_phone="+91 9842176565").first()
        self.assertIsNotNone(order)
        # 8 items * 150 = 1200
        self.assertEqual(order.items_subtotal, Decimal("1200.00"))
        # Packing fee: ₹20
        self.assertEqual(order.packing_fee, Decimal("20.00"))
        # GST (18% included on 1200): ₹183.04
        self.assertEqual(order.gst_amount, Decimal("183.04"))
        # Shipping fee: ₹50
        self.assertEqual(order.shipping_fee, Decimal("50.00"))
        # Total: 1200 + 20 + 50 = 1270
        self.assertEqual(order.total_amount, Decimal("1270.00"))

        # Check checkout GET page has no '(Local:' label
        checkout_get = self.client.get(f"/checkout/{self.product.id}/?qty=8")
        self.assertEqual(checkout_get.status_code, 200)
        self.assertNotContains(checkout_get, "(Local:")

    def test_admin_can_customize_packing_fee_settings(self):
        self.client.login(username="adminstaff_ship", password="staff-password")
        post_res = self.client.post(
            reverse("admin_packing_charges"),
            data={
                "packing_free_cans": "4",
                "packing_cost_per_batch": "30.00",
                "packing_batch_size": "4",
            },
        )
        self.assertRedirects(post_res, reverse("admin_packing_charges"))

        details = SiteDetails.get_solo()
        self.assertEqual(details.packing_free_cans, 4)
        self.assertEqual(details.packing_cost_per_batch, Decimal("30.00"))
        self.assertEqual(details.packing_batch_size, 4)

        # 4 cans are free
        self.assertEqual(details.calculate_packing_fee(4), Decimal("0.00"))
        # 5 cans = 1 extra = ₹30
        self.assertEqual(details.calculate_packing_fee(5), Decimal("30.00"))

    def test_admin_shipping_url_redirects_to_shipping_charges(self):
        self.client.login(username="adminstaff_ship", password="staff-password")
        res = self.client.get(reverse("admin_shipping_rates"))
        self.assertRedirects(res, reverse("admin_shipping_charges"))

    def test_admin_details_page_does_not_include_shipping_rates_or_rules(self):
        self.client.login(username="adminstaff_ship", password="staff-password")
        res = self.client.get(reverse("admin_details"))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "Shipping Rates &amp; Rules")
        self.assertNotContains(res, "Shipping Rates & Rules")
        self.assertNotContains(res, "id_shipping_fee_local")
        self.assertNotContains(res, "id_packing_free_cans")

    def test_admin_separate_rates_handling_pages(self):
        self.client.login(username="adminstaff_ship", password="staff-password")

        # 1. Shipping Charges page
        ship_res = self.client.get(reverse("admin_shipping_charges"))
        self.assertEqual(ship_res.status_code, 200)
        self.assertContains(ship_res, "Shipping Charges")
        self.assertContains(ship_res, "Selected States Shipping Fee")
        self.assertContains(ship_res, "stateRegionDropdown")
        self.assertContains(ship_res, "Rates Handling")

        # 2. Packing Charges page
        pack_res = self.client.get(reverse("admin_packing_charges"))
        self.assertEqual(pack_res.status_code, 200)
        self.assertContains(pack_res, "Packing Charges")
        self.assertContains(pack_res, "Free Packing Cans Threshold")
        self.assertContains(pack_res, "Packing Cost Per Additional Batch")
        self.assertContains(pack_res, "Rates Handling")

    def test_footer_displays_dynamic_contact_info(self):
        details = SiteDetails.get_solo()
        details.support_email = "custom_care@jcsd-official.com"
        details.support_phone = "+91 91234 56789"
        details.whatsapp_number = "+91 91234 56789"
        details.save()

        # Check on home page footer
        home_res = self.client.get(reverse("home"))
        self.assertEqual(home_res.status_code, 200)
        self.assertContains(home_res, "custom_care@jcsd-official.com")
        self.assertContains(home_res, "+91 91234 56789")
        self.assertContains(home_res, "https://wa.me/919123456789")

        # Check on about page footer
        about_res = self.client.get(reverse("about"))
        self.assertEqual(about_res.status_code, 200)
        self.assertContains(about_res, "custom_care@jcsd-official.com")
        self.assertContains(about_res, "+91 91234 56789")
        self.assertContains(about_res, "https://wa.me/919123456789")


class OrderReceiptTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.customer = user_model.objects.create_user(
            username="testcustomer",
            email="customer@example.com",
            password="testpassword123",
            first_name="Customer",
            last_name="One",
        )
        self.other_customer = user_model.objects.create_user(
            username="othercustomer",
            email="other@example.com",
            password="testpassword123",
            first_name="Other",
            last_name="User",
        )
        self.staff_user = user_model.objects.create_user(
            username="adminuser",
            email="admin@example.com",
            password="adminpassword123",
            is_staff=True,
        )
        self.product = Product.objects.create(
            name="Classic Cola",
            description="Crisp and bold cola.",
            price=Decimal("90.00"),
            volume="330 ml",
            image="main/images/cola.png",
            available=True,
        )
        self.order = Order.objects.create(
            product=self.product,
            customer=self.customer,
            customer_name="Customer One",
            customer_phone="+91 9876543210",
            delivery_address="123 Test Street",
            delivery_city="Chennai",
            delivery_state="Tamil Nadu",
            delivery_postal_code="600001",
            quantity=2,
            total_amount=Decimal("230.00"),
            shipping_fee=Decimal("50.00"),
            packing_fee=Decimal("0.00"),
            payment_status="paid",
            status="pending",
        )
        OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            unit_price=Decimal("90.00"),
        )

    def test_customer_can_view_own_order_receipt(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("order_receipt", kwargs={"order_id": self.order.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Order #{self.order.order_number or self.order.id}")
        self.assertContains(response, "Order Receipt & Tax Invoice")
        self.assertContains(response, "Customer One")
        self.assertContains(response, "123 Test Street")
        self.assertContains(response, "Classic Cola")
        self.assertContains(response, "230.00")
        self.assertContains(response, "Paid in full")
        self.assertContains(response, "Print Slip / Save PDF")

    def test_customer_cannot_view_other_customer_receipt(self):
        self.client.force_login(self.other_customer)
        response = self.client.get(reverse("order_receipt", kwargs={"order_id": self.order.id}))
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_redirected_to_login(self):
        response = self.client.get(reverse("order_receipt", kwargs={"order_id": self.order.id}))
        self.assertEqual(response.status_code, 302)
        self.assertIn("customer-login", response.url)

    def test_staff_can_view_any_order_receipt(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("order_receipt", kwargs={"order_id": self.order.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Order #{self.order.order_number or self.order.id}")
        self.assertContains(response, "Back to Order")

    def test_guest_can_view_receipt_by_payment_reference(self):
        response = self.client.get(
            reverse("order_receipt_by_reference", kwargs={"payment_reference": self.order.payment_reference})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Order #{self.order.order_number or self.order.id}")

    def test_customer_orders_page_contains_print_slip_button(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("customer_orders"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Print Slip")
        self.assertContains(response, reverse("order_receipt", kwargs={"order_id": self.order.id}))

    def test_admin_order_detail_contains_print_slip_link(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("admin_order_detail", kwargs={"order_id": self.order.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Print Order Slip")
        self.assertContains(response, reverse("order_receipt", kwargs={"order_id": self.order.id}))

    def test_admin_delivery_status_modal_contains_print_slip_link(self):
        self.client.force_login(self.staff_user)
        response = self.client.get(reverse("admin_delivery_status"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Print Slip")
        self.assertContains(response, reverse("order_receipt", kwargs={"order_id": self.order.id}))

    def test_checkout_and_receipt_include_gst_18_percent(self):
        res = self.client.get(f"/checkout/{self.product.id}/?qty=1")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "(Inclusive of all taxes)")
        self.assertNotContains(res, "GST (18%)")
        self.assertContains(res, "₹90.00")

        post_res = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            {
                "first_name": "GST",
                "last_name": "Tester",
                "email": "gst@example.com",
                "phone": "+91 9842100000",
                "address": "77 GST Street",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "postal_code": "600001",
            },
        )
        self.assertEqual(post_res.status_code, 302)
        order = Order.objects.filter(customer_phone="+91 9842100000").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.items_subtotal, Decimal("90.00"))
        self.assertEqual(order.gst_amount, Decimal("13.73"))
        self.assertEqual(order.shipping_fee, Decimal("50.00"))
        self.assertEqual(order.packing_fee, Decimal("0.00"))
        self.assertEqual(order.total_amount, Decimal("140.00"))

        receipt_res = self.client.get(reverse("order_receipt", kwargs={"order_id": order.id}))
        self.assertEqual(receipt_res.status_code, 200)
        self.assertContains(receipt_res, "Included GST")
        self.assertContains(receipt_res, "₹13.73")
        self.assertContains(receipt_res, "₹140.00")


class DeliveryPartnerManagementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_user(
            username="partner-admin",
            password="admin-password-123",
            is_staff=True,
        )
        cls.customer = get_user_model().objects.create_user(
            username="test-customer",
            password="customer-password-123",
        )
        cls.cola = Product.objects.create(
            name="Test Cola",
            description="Refreshing beverage",
            price="90.00",
            volume="330 ml",
        )

    def test_apply_page_renders_successfully(self):
        res = self.client.get(reverse("delivery_partner_apply"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Apply as Delivery Partner")
        self.assertContains(res, "Aadhaar Card Number")
        self.assertContains(res, "PIN Codes You Can Deliver To")

    def test_delivery_partner_application_flow_and_approval(self):
        # 1. Partner submits application
        post_data = {
            "first_name": "Ramesh",
            "last_name": "Kumar",
            "username": "ramesh_delivery",
            "email": "ramesh@example.com",
            "phone": "+91 98765 43210",
            "address": "12 Gandhi Nagar, Madurai",
            "aadhar_number": "1234 5678 9012",
            "driving_license": "TN-58-2022-0012345",
            "vehicle_type": "bike",
            "vehicle_number": "TN 58 AB 1234",
            "serviceable_pincodes": "625018, 625001",
            "password": "partner-pass-123",
            "password_confirm": "partner-pass-123",
        }
        res = self.client.post(reverse("delivery_partner_apply"), data=post_data)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Application Submitted!")
        self.assertContains(res, "12 Gandhi Nagar, Madurai")

        user = get_user_model().objects.get(username="ramesh_delivery")
        profile = DeliveryProfile.objects.get(user=user)
        self.assertFalse(profile.is_approved)
        self.assertEqual(profile.status, "pending")
        self.assertEqual(profile.address, "12 Gandhi Nagar, Madurai")
        self.assertEqual(profile.vehicle_type, "bike")
        self.assertEqual(profile.vehicle_number, "TN 58 AB 1234")
        self.assertEqual(profile.get_serviceable_pincodes_list(), ["625001", "625018"])

        # 2. Pending partner cannot log in
        login_res = self.client.post(
            reverse("delivery_login"),
            {"username": "ramesh_delivery", "password": "partner-pass-123"},
        )
        self.assertEqual(login_res.status_code, 200)
        self.assertContains(login_res, "under review")

        # 3. Admin views directory and approves partner
        self.client.force_login(self.admin)
        dir_res = self.client.get(reverse("admin_delivery_users"))
        self.assertEqual(dir_res.status_code, 200)
        self.assertContains(dir_res, "ramesh_delivery")
        self.assertContains(dir_res, "625018")

        approve_res = self.client.post(
            reverse("admin_approve_delivery_partner", kwargs={"profile_id": profile.id})
        )
        self.assertRedirects(approve_res, reverse("admin_delivery_users"))
        profile.refresh_from_db()
        self.assertTrue(profile.is_approved)
        self.assertEqual(profile.status, "approved")

        # 4. Partner can now log in
        self.client.logout()
        login_success = self.client.post(
            reverse("delivery_login"),
            {"username": "ramesh_delivery", "password": "partner-pass-123"},
        )
        self.assertRedirects(login_success, reverse("delivery_dashboard"))

    def test_delivery_partner_pincode_order_filtering_and_picking_restriction(self):
        # Create partner restricted to PIN 625018
        driver_user = get_user_model().objects.create_user(
            username="local_driver",
            email="driver@example.com",
            password="driver-pass-123",
        )
        driver_profile = DeliveryProfile.objects.create(
            user=driver_user,
            serviceable_pincodes="625018",
            is_approved=True,
            status="approved",
        )

        # Order 1: inside driver's PIN 625018
        order_in_zone = Order.objects.create(
            product=self.cola,
            customer=self.customer,
            customer_name="Local Customer",
            delivery_address="10 Madurai Road",
            delivery_city="Madurai",
            delivery_state="Tamil Nadu",
            delivery_postal_code="625018",
            quantity=1,
            total_amount="90.00",
            status="shipped",
        )

        # Order 2: outside driver's PIN (Chennai 600001)
        order_outside_zone = Order.objects.create(
            product=self.cola,
            customer=self.customer,
            customer_name="Out of Zone Customer",
            delivery_address="50 Anna Salai",
            delivery_city="Chennai",
            delivery_state="Tamil Nadu",
            delivery_postal_code="600001",
            quantity=1,
            total_amount="90.00",
            status="shipped",
        )

        self.client.force_login(driver_user)

        # Driver views available orders
        avail_res = self.client.get(f"{reverse('delivery_dashboard')}?tab=available")
        self.assertEqual(avail_res.status_code, 200)
        # Order 1 (625018) should appear
        self.assertContains(avail_res, f"Order #{order_in_zone.order_number or order_in_zone.id}")
        self.assertContains(avail_res, "625018")
        # Order 2 (600001) should NOT appear
        self.assertNotContains(avail_res, f"Order #{order_outside_zone.order_number or order_outside_zone.id}")

        # Attempt to pick out-of-zone order -> blocked!
        pick_outside_res = self.client.post(
            reverse("pick_delivery_order", kwargs={"order_id": order_outside_zone.id})
        )
        self.assertRedirects(pick_outside_res, f"{reverse('delivery_dashboard')}?tab=available")
        order_outside_zone.refresh_from_db()
        self.assertIsNone(order_outside_zone.delivery_user)

        # Pick in-zone order -> allowed!
        pick_inside_res = self.client.post(
            reverse("pick_delivery_order", kwargs={"order_id": order_in_zone.id})
        )
        self.assertRedirects(pick_inside_res, f"{reverse('delivery_dashboard')}?tab=picked")
        order_in_zone.refresh_from_db()
        self.assertEqual(order_in_zone.delivery_user, driver_user)
        self.assertEqual(order_in_zone.status, "out_for_delivery")

    def test_admin_reject_update_and_delete_partner(self):
        driver = get_user_model().objects.create_user(
            username="driver_to_edit",
            password="password",
        )
        dp = DeliveryProfile.objects.create(
            user=driver,
            is_approved=True,
            status="approved",
            serviceable_pincodes="625001",
        )

        self.client.force_login(self.admin)

        # Update PIN codes and Address
        update_res = self.client.post(
            reverse("admin_update_delivery_pincodes", kwargs={"profile_id": dp.id}),
            data={
                "serviceable_pincodes": "625001, 625018, 625020",
                "vehicle_type": "ev",
                "vehicle_number": "TN 58 EV 9999",
                "address": "45 New Lake Road, Madurai",
            },
        )
        self.assertRedirects(update_res, reverse("admin_delivery_users"))
        dp.refresh_from_db()
        self.assertEqual(dp.vehicle_type, "ev")
        self.assertEqual(dp.vehicle_number, "TN 58 EV 9999")
        self.assertEqual(dp.address, "45 New Lake Road, Madurai")
        self.assertIn("625018", dp.get_serviceable_pincodes_list())

        # Reject partner
        reject_res = self.client.post(
            reverse("admin_reject_delivery_partner", kwargs={"profile_id": dp.id}),
            data={"rejection_reason": "Incomplete documentation"},
        )
        self.assertRedirects(reject_res, reverse("admin_delivery_users"))
        dp.refresh_from_db()
        self.assertFalse(dp.is_approved)
        self.assertEqual(dp.status, "rejected")
        self.assertEqual(dp.rejection_reason, "Incomplete documentation")

        # Delete partner
        delete_res = self.client.post(
            reverse("admin_delete_delivery_partner", kwargs={"profile_id": dp.id})
        )
        self.assertRedirects(delete_res, reverse("admin_delivery_users"))
        self.assertFalse(get_user_model().objects.filter(username="driver_to_edit").exists())


class ProductPincodeAvailabilityTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin_pincode",
            email="admin_pincode@example.com",
            password="adminpassword123",
        )
        self.customer = get_user_model().objects.create_user(
            username="pincode_customer",
            email="pin_cust@example.com",
            password="custpassword123",
        )
        self.product_any = Product.objects.create(
            name="Open Drink",
            price=Decimal("100.00"),
            available=True,
            available_pincodes="",
        )
        self.product_restricted = Product.objects.create(
            name="Local Madurai Cola",
            price=Decimal("80.00"),
            available=True,
            available_pincodes="625001, 625018, 625020",
        )

    def test_product_pincode_model_methods(self):
        # Open drink is deliverable anywhere
        self.assertEqual(self.product_any.get_available_pincodes_list(), [])
        self.assertTrue(self.product_any.is_available_for_pincode("625018"))
        self.assertTrue(self.product_any.is_available_for_pincode("110001"))
        self.assertTrue(self.product_any.is_available_for_pincode(""))

        # Restricted product is deliverable only to specified PINs
        self.assertEqual(
            self.product_restricted.get_available_pincodes_list(),
            ["625001", "625018", "625020"],
        )
        self.assertTrue(self.product_restricted.is_available_for_pincode("625018"))
        self.assertTrue(self.product_restricted.is_available_for_pincode("625001"))
        self.assertFalse(self.product_restricted.is_available_for_pincode("110001"))
        self.assertFalse(self.product_restricted.is_available_for_pincode(""))

    def test_admin_update_product_pincodes(self):
        self.client.force_login(self.admin)
        res = self.client.post(
            reverse("admin_update_product_pincodes", kwargs={"product_id": self.product_any.id}),
            data={"available_pincodes": "600001, 600002"},
        )
        self.assertRedirects(res, reverse("admin_products"))
        self.product_any.refresh_from_db()
        self.assertEqual(self.product_any.available_pincodes, "600001, 600002")
        self.assertTrue(self.product_any.is_available_for_pincode("600001"))
        self.assertFalse(self.product_any.is_available_for_pincode("625018"))

    def test_check_pincode_availability_api(self):
        # Available pincode
        res = self.client.get(
            reverse("check_pincode_availability", kwargs={"product_id": self.product_restricted.id})
            + "?pincode=625018"
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["available"])
        self.assertIn("625018", data["message"])

        # Disallowed pincode
        res = self.client.get(
            reverse("check_pincode_availability", kwargs={"product_id": self.product_restricted.id})
            + "?pincode=110001"
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["available"])
        self.assertIn("not deliverable", data["message"])
        self.assertNotIn("Available in", data["message"])

    def test_single_product_checkout_blocks_unsupported_pincode(self):
        self.client.force_login(self.customer)
        # Attempt checkout for restricted product with wrong pincode 110001
        res = self.client.post(
            f"/checkout/{self.product_restricted.id}/?qty=1",
            data={
                "first_name": "Pin",
                "last_name": "Tester",
                "email": "pin@example.com",
                "phone": "+91 9842100000",
                "address": "12 Main St",
                "city": "Delhi",
                "state": "Delhi",
                "postal_code": "110001",
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        # Verify order was NOT created
        self.assertFalse(Order.objects.filter(customer=self.customer).exists())
        self.assertContains(res, "not deliverable to PIN code 110001")

        # Now attempt checkout with supported pincode 625018
        res_ok = self.client.post(
            f"/checkout/{self.product_restricted.id}/?qty=1",
            data={
                "first_name": "Pin",
                "last_name": "Tester",
                "email": "pin@example.com",
                "phone": "+91 9842100000",
                "address": "12 Main St",
                "city": "Madurai",
                "state": "Tamil Nadu",
                "postal_code": "625018",
            },
        )
        self.assertEqual(res_ok.status_code, 302)
        self.assertTrue(Order.objects.filter(customer=self.customer).exists())

    def test_cart_checkout_blocks_unsupported_pincode(self):
        # Add restricted product to cart
        self.client.post(reverse("add_to_cart", kwargs={"product_id": self.product_restricted.id}), data={"quantity": 1})

        # Checkout with disallowed pincode
        res = self.client.post(
            reverse("cart_checkout"),
            data={
                "first_name": "Cart",
                "last_name": "Tester",
                "email": "cart@example.com",
                "phone": "+91 9842100000",
                "address": "12 Main St",
                "city": "Delhi",
                "state": "Delhi",
                "postal_code": "110001",
            },
            follow=True,
        )
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "not available for delivery to PIN code 110001")
        self.assertFalse(Order.objects.filter(customer_phone="+91 9842100000").exists())

    def test_admin_products_renders_full_width_and_modal_button(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse("admin_products"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Add New Product")
        self.assertContains(res, "productFormModal")
        self.assertContains(res, "Available Delivery PINs")
        self.assertContains(res, "productPincodesModal")

    def test_admin_delivery_users_renders_full_width_and_address(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse("admin_delivery_users"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Add Delivery Partner")
        self.assertContains(res, "addPartnerModal")
        self.assertContains(res, "Residential Address")

    def test_checkout_template_contains_pincode_validation_elements(self):
        # GET checkout page for restricted product
        res = self.client.get(f"/checkout/{self.product_restricted.id}/?qty=1")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="continuePaymentBtn"')
        self.assertContains(res, 'id="pincodeDeliveryNotice"')
        self.assertContains(res, 'id="product-pins-data"')
        self.assertContains(res, "625018")
        self.assertContains(res, "625001")
        self.assertContains(res, 'maxlength="6"')
        self.assertContains(res, 'inputmode="numeric"')

    def test_cart_template_contains_pincode_validation_elements(self):
        # Add restricted product to cart
        self.client.post(reverse("add_to_cart", kwargs={"product_id": self.product_restricted.id}), data={"quantity": 1})
        res = self.client.get(reverse("cart"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="cartPincodeNotice"')
        self.assertContains(res, 'id="cart-pin-rules-data"')
        self.assertContains(res, "625018")
        self.assertContains(res, f'data-cart-item-id="{self.product_restricted.id}"')
        self.assertContains(res, f'id="cart-item-pin-badge-{self.product_restricted.id}"')
        self.assertContains(res, f'id="cart-item-pin-notice-{self.product_restricted.id}"')
        self.assertContains(res, 'id="removeConfirmModal"')
        self.assertContains(res, "Add to Wishlist")
        self.assertContains(res, "Remove from Cart")
        self.assertContains(res, 'maxlength="6"')
        self.assertContains(res, 'inputmode="numeric"')

    def test_product_detail_contains_6_digit_pincode_check(self):
        res = self.client.get(reverse("product_detail", kwargs={"product_id": self.product_restricted.id}))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="pincodeCheckInput"')
        self.assertContains(res, 'maxlength="6"')
        self.assertContains(res, 'inputmode="numeric"')


class OrderStatusProgressionTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="admin_progression",
            email="admin_prog@example.com",
            password="adminpassword123",
        )
        self.driver_user = get_user_model().objects.create_user(
            username="driver_progression",
            password="driverpassword123",
        )
        self.driver_profile = DeliveryProfile.objects.create(
            user=self.driver_user,
            is_approved=True,
            status="approved",
            serviceable_pincodes="625018",
        )
        self.product = Product.objects.create(
            name="Sparkling Drink",
            price=Decimal("90.00"),
            available=True,
        )
        self.order = Order.objects.create(
            product=self.product,
            customer_name="John Doe",
            customer_phone="+91 9876543210",
            delivery_address="12 Main St",
            delivery_city="Madurai",
            delivery_state="Tamil Nadu",
            delivery_postal_code="625018",
            quantity=1,
            total_amount=Decimal("90.00"),
            status="pending",
        )

    def test_shipped_status_progression_and_ajax_update(self):
        self.client.force_login(self.admin)

        # 1. Quick pack: pending -> packed
        res_pack = self.client.post(
            reverse("admin_update_order_status", kwargs={"order_id": self.order.id}),
            {"status": "packed"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "packed")

        # 2. Quick ship: packed -> shipped
        res_ship = self.client.post(
            reverse("admin_update_order_status", kwargs={"order_id": self.order.id}),
            {"status": "shipped"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "shipped")

        # 3. Dynamic AJAX update
        res_ajax = self.client.post(
            reverse("admin_update_order_status", kwargs={"order_id": self.order.id}),
            {"status": "cancelled"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(res_ajax.status_code, 200)
        ajax_data = res_ajax.json()
        self.assertEqual(ajax_data["status"], "success")
        self.assertEqual(ajax_data["new_status"], "cancelled")
        self.assertEqual(ajax_data["new_status_display"], "Cancelled")

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "cancelled")

    def test_delivery_partner_only_sees_and_picks_shipped_orders(self):
        self.client.force_login(self.driver_user)

        # Pending order: driver should NOT see in available orders
        self.order.status = "pending"
        self.order.save(update_fields=["status"])
        res_pending = self.client.get(f"{reverse('delivery_dashboard')}?tab=available")
        self.assertNotContains(res_pending, f"Pick Order #{self.order.order_number or self.order.id}")

        # Cannot pick pending order
        pick_pending = self.client.post(
            reverse("pick_delivery_order", kwargs={"order_id": self.order.id})
        )
        self.order.refresh_from_db()
        self.assertIsNone(self.order.delivery_user)

        # Packed order: driver should NOT see in available orders
        self.order.status = "packed"
        self.order.save(update_fields=["status"])
        res_packed = self.client.get(f"{reverse('delivery_dashboard')}?tab=available")
        self.assertNotContains(res_packed, f"Pick Order #{self.order.order_number or self.order.id}")

        # Cannot pick packed order
        pick_packed = self.client.post(
            reverse("pick_delivery_order", kwargs={"order_id": self.order.id})
        )
        self.order.refresh_from_db()
        self.assertIsNone(self.order.delivery_user)

        # Shipped order: driver CAN see in available orders
        self.order.status = "shipped"
        self.order.save(update_fields=["status"])
        res_shipped = self.client.get(f"{reverse('delivery_dashboard')}?tab=available")
        self.assertContains(res_shipped, f"Pick Order #{self.order.order_number or self.order.id}")

        # Driver picks shipped order -> status automatically transitions to out_for_delivery
        pick_res = self.client.post(
            reverse("pick_delivery_order", kwargs={"order_id": self.order.id})
        )
        self.assertRedirects(pick_res, f"{reverse('delivery_dashboard')}?tab=picked")
        self.order.refresh_from_db()
        self.assertEqual(self.order.delivery_user, self.driver_user)
        self.assertEqual(self.order.status, "out_for_delivery")

        # Driver marks as cancelled
        res_cancel = self.client.post(
            reverse("update_delivery_status", kwargs={"order_id": self.order.id}),
            {"status": "cancelled"},
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "cancelled")

    def test_admin_delivery_status_page_renders_shipped_and_cancelled_tabs(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse("admin_delivery_status"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Shipped")
        self.assertContains(res, "Cancelled")
        self.assertContains(res, "Customer Orders")
        self.assertContains(res, "auto-status-select")
        self.assertContains(res, "orders-stats-grid")
        self.assertContains(res, "stats-grid-3")

    def test_mobile_stats_grid_segmentation_and_monochrome_bottom_nav(self):
        self.client.force_login(self.admin)
        res_users = self.client.get(reverse("admin_delivery_users"))
        self.assertEqual(res_users.status_code, 200)
        self.assertContains(res_users, "partners-stats-grid")
        self.assertContains(res_users, "stats-grid-3")

        res_orders = self.client.get(reverse("admin_delivery_status"))
        self.assertEqual(res_orders.status_code, 200)
        self.assertContains(res_orders, "orders-stats-grid")
        self.assertContains(res_orders, "stats-grid-3")

        # Check mobile bottom nav on storefront
        res_home = self.client.get(reverse("home"))
        self.assertEqual(res_home.status_code, 200)
        self.assertContains(res_home, "mobile-bottom-nav")
        self.assertContains(res_home, "mobile-bottom-nav-item")
        self.assertContains(res_home, "data-nav=\"home\"")
        self.assertContains(res_home, "data-nav=\"categories\"")



class CouponSystemTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="coupon_admin",
            email="coupon_admin@example.com",
            password="adminpassword123",
        )
        self.user = get_user_model().objects.create_user(
            username="coupon_user",
            email="user@example.com",
            password="userpassword123",
        )
        self.cat_cola, _ = ProductCategory.objects.get_or_create(slug="cola", defaults={"name": "Cola"})
        self.cat_energy, _ = ProductCategory.objects.get_or_create(slug="energy_drink", defaults={"name": "Energy Drink"})
        self.product = Product.objects.create(
            name="Super Cola",
            category="cola",
            price=Decimal("100.00"),
            available=True,
        )

    def test_admin_coupons_requires_staff(self):
        res = self.client.get(reverse("admin_coupons"))
        self.assertEqual(res.status_code, 302)

        self.client.force_login(self.user)
        res = self.client.get(reverse("admin_coupons"))
        self.assertEqual(res.status_code, 302)

        self.client.force_login(self.admin)
        res = self.client.get(reverse("admin_coupons"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Coupons & Discounts")
        self.assertContains(res, "Create New Coupon")
        self.assertContains(res, "All Promotional Coupons")
        self.assertContains(res, "Orders Applied with Coupons")
        self.assertContains(res, 'id="searchCouponsInput"')
        self.assertContains(res, 'id="sortCouponsSelect"')
        self.assertContains(res, 'id="searchOrdersInput"')
        self.assertContains(res, 'id="sortOrdersSelect"')

    def test_admin_create_coupon_post(self):
        self.client.force_login(self.admin)
        data = {
            "code": "festive25",
            "discount_type": "percentage",
            "discount_value": "25.00",
            "min_order_amount": "200.00",
            "usage_limit": "100",
            "expire_date": "2026-12-31",
            "applicable_categories": [self.cat_cola.pk],
            "is_active": "on",
        }
        res = self.client.post(reverse("admin_coupons"), data=data)
        self.assertRedirects(res, reverse("admin_coupons"))

        coupon = Coupon.objects.filter(code="FESTIVE25").first()
        self.assertIsNotNone(coupon)
        self.assertEqual(coupon.discount_type, "percentage")
        self.assertEqual(coupon.discount_value, Decimal("25.00"))
        self.assertEqual(coupon.min_order_amount, Decimal("200.00"))
        self.assertEqual(coupon.usage_limit, 100)
        self.assertTrue(coupon.is_active)
        self.assertIn(self.cat_cola, coupon.applicable_categories.all())

    def test_admin_toggle_and_delete_coupon(self):
        self.client.force_login(self.admin)
        coupon = Coupon.objects.create(
            code="TOGGLE10",
            discount_type="fixed",
            discount_value=Decimal("10.00"),
            is_active=True,
        )
        res = self.client.post(reverse("admin_toggle_coupon", kwargs={"coupon_id": coupon.id}))
        self.assertRedirects(res, reverse("admin_coupons"))
        coupon.refresh_from_db()
        self.assertFalse(coupon.is_active)

        self.client.post(reverse("admin_toggle_coupon", kwargs={"coupon_id": coupon.id}))
        coupon.refresh_from_db()
        self.assertTrue(coupon.is_active)

        res_del = self.client.post(reverse("admin_delete_coupon", kwargs={"coupon_id": coupon.id}))
        self.assertRedirects(res_del, reverse("admin_coupons"))
        self.assertFalse(Coupon.objects.filter(id=coupon.id).exists())

    def test_coupon_discount_calculation(self):
        pct_coupon = Coupon.objects.create(
            code="PCT20",
            discount_type="percentage",
            discount_value=Decimal("20.00"),
            min_order_amount=Decimal("100.00"),
        )
        self.assertEqual(pct_coupon.calculate_discount(Decimal("80.00")), Decimal("0.00"))
        self.assertEqual(pct_coupon.calculate_discount(Decimal("200.00")), Decimal("40.00"))

        fix_coupon = Coupon.objects.create(
            code="FIX50",
            discount_type="fixed",
            discount_value=Decimal("50.00"),
            min_order_amount=Decimal("0.00"),
        )
        self.assertEqual(fix_coupon.calculate_discount(Decimal("30.00")), Decimal("30.00"))
        self.assertEqual(fix_coupon.calculate_discount(Decimal("150.00")), Decimal("50.00"))

        cat_coupon = Coupon.objects.create(
            code="COLAONLY",
            discount_type="percentage",
            discount_value=Decimal("50.00"),
        )
        cat_coupon.applicable_categories.add(self.cat_cola)
        prod_other = Product.objects.create(name="Juice", category="others", price=Decimal("200.00"), available=True)
        items_data = [
            {"product": self.product, "quantity": 1},
            {"product": prod_other, "quantity": 1},
        ]
        discount = cat_coupon.calculate_discount(Decimal("300.00"), order_items_data=items_data)
        self.assertEqual(discount, Decimal("50.00"))

    def test_orders_applied_with_coupons_rendered_in_table(self):
        coupon = Coupon.objects.create(
            code="BIGSALE",
            discount_type="fixed",
            discount_value=Decimal("20.00"),
        )
        order = Order.objects.create(
            product=self.product,
            customer_name="Alice Smith",
            customer_phone="+91 9123456789",
            delivery_address="45 Park Lane",
            delivery_city="Madurai",
            delivery_state="Tamil Nadu",
            delivery_postal_code="625001",
            quantity=1,
            total_amount=Decimal("80.00"),
            discount_amount=Decimal("20.00"),
            coupon=coupon,
            coupon_code="BIGSALE",
        )

        self.client.force_login(self.admin)
        res = self.client.get(reverse("admin_coupons"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "BIGSALE")
        self.assertContains(res, "Alice Smith")
        self.assertContains(res, f"#{order.order_number or order.id}")
        self.assertContains(res, "-₹20.00")

    def test_api_apply_coupon(self):
        Coupon.objects.create(
            code="API10",
            discount_type="percentage",
            discount_value=Decimal("10.00"),
            min_order_amount=Decimal("50.00"),
            is_active=True,
        )
        res = self.client.get(reverse("api_apply_coupon") + "?code=API10&subtotal=100")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["discount_amount"], 10.0)
        self.assertEqual(data["code"], "API10")

        res_bad = self.client.get(reverse("api_apply_coupon") + "?code=NOTFOUND&subtotal=100")
        self.assertEqual(res_bad.status_code, 200)
        self.assertFalse(res_bad.json()["valid"])

    def test_checkout_and_cart_display_payment_method_and_coupon_box(self):
        # Checkout page
        res_chk = self.client.get(f"/checkout/{self.product.id}/?qty=1")
        self.assertEqual(res_chk.status_code, 200)
        self.assertContains(res_chk, 'id="chkPmOnline"')
        self.assertContains(res_chk, 'id="chkPmCod"')
        self.assertContains(res_chk, 'id="chkCouponBox"')
        self.assertContains(res_chk, 'id="chkCouponInput"')
        self.assertContains(res_chk, 'id="chkApplyCouponBtn"')

        # Cart page
        self.client.post(reverse("add_to_cart", kwargs={"product_id": self.product.id}), data={"quantity": 1})
        res_cart = self.client.get(reverse("cart"))
        self.assertEqual(res_cart.status_code, 200)
        self.assertContains(res_cart, 'id="cartPmOnline"')
        self.assertContains(res_cart, 'id="cartPmCod"')
        self.assertContains(res_cart, 'id="cartCouponBox"')
        self.assertContains(res_cart, 'id="cartCouponInput"')
        self.assertContains(res_cart, 'id="cartApplyCouponBtn"')

    def test_coupon_applied_only_for_online_payment_not_cod(self):
        coupon = Coupon.objects.create(
            code="ONLINE20",
            discount_type="fixed",
            discount_value=Decimal("20.00"),
            is_active=True,
        )

        # 1. COD checkout: Coupon should NOT be applied
        res_cod = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            data={
                "first_name": "Cod",
                "last_name": "Tester",
                "email": "cod@example.com",
                "phone": "+91 9842100001",
                "address": "12 Street",
                "city": "Madurai",
                "state": "Tamil Nadu",
                "postal_code": "625001",
                "payment_method": "cod",
                "coupon_code": "ONLINE20",
            },
        )
        self.assertEqual(res_cod.status_code, 302)
        order_cod = Order.objects.filter(customer_phone="+91 9842100001").first()
        self.assertIsNotNone(order_cod)
        self.assertEqual(order_cod.payment_method, "cod")
        self.assertEqual(order_cod.discount_amount, Decimal("0.00"))
        self.assertIsNone(order_cod.coupon)

        # 2. Online checkout: Coupon SHOULD be applied
        res_online = self.client.post(
            f"/checkout/{self.product.id}/?qty=1",
            data={
                "first_name": "Online",
                "last_name": "Tester",
                "email": "online@example.com",
                "phone": "+91 9842100002",
                "address": "12 Street",
                "city": "Madurai",
                "state": "Tamil Nadu",
                "postal_code": "625001",
                "payment_method": "online",
                "coupon_code": "ONLINE20",
            },
        )
        self.assertEqual(res_online.status_code, 302)
        order_online = Order.objects.filter(customer_phone="+91 9842100002").first()
        self.assertIsNotNone(order_online)
        self.assertEqual(order_online.payment_method, "online")
        self.assertEqual(order_online.discount_amount, Decimal("20.00"))
        self.assertEqual(order_online.coupon, coupon)

    def test_api_apply_coupon_rejects_cod(self):
        Coupon.objects.create(
            code="ONLYONLINE",
            discount_type="fixed",
            discount_value=Decimal("15.00"),
            is_active=True,
        )
        res = self.client.get(reverse("api_apply_coupon") + "?code=ONLYONLINE&subtotal=100&payment_method=cod")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["valid"])
        self.assertIn("online payments", data["message"].lower())

    def test_admin_delivery_status_renders_coupon_info_and_subtracted_price(self):
        coupon = Coupon.objects.create(
            code="COLA10",
            discount_type="fixed",
            discount_value=Decimal("9.00"),
            is_active=True,
        )
        order = Order.objects.create(
            product=self.product,
            quantity=1,
            customer_name="Test Customer",
            customer_phone="+91 9842100099",
            delivery_address="1st Street",
            delivery_city="Chennai",
            delivery_state="Tamil Nadu",
            delivery_postal_code="600001",
            total_amount=Decimal("147.20"),
            gst_amount=Decimal("16.20"),
            shipping_fee=Decimal("50.00"),
            packing_fee=Decimal("0.00"),
            discount_amount=Decimal("9.00"),
            coupon=coupon,
            coupon_code="COLA10",
            payment_method="online",
            payment_status="paid",
            status="pending",
        )
        OrderItem.objects.create(
            order=order,
            product=self.product,
            quantity=1,
            unit_price=Decimal("90.00"),
        )

        self.client.force_login(self.admin)
        res = self.client.get(reverse("admin_delivery_status"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Coupon Discount")
        self.assertContains(res, "COLA10")
        self.assertContains(res, "-₹9.00")
        self.assertContains(res, "₹147.20")
        self.assertContains(res, "Coupon Applied")

        # Also check admin order detail
        res_detail = self.client.get(reverse("admin_order_detail", kwargs={"order_id": order.id}))
        self.assertEqual(res_detail.status_code, 200)
        self.assertContains(res_detail, "Coupon Discount (COLA10)")
        self.assertContains(res_detail, "-₹9.00")
        self.assertContains(res_detail, "Coupon Applied")

    def test_coupon_api_error_responses_and_single_product_validation(self):
        """Test that invalid coupons return detailed error messages and valid coupons calculate discounts properly."""
        # 1. Non-existent coupon (like POOJA2026)
        res = self.client.get(reverse("api_apply_coupon") + "?code=POOJA2026&subtotal=90.00&payment_method=online")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["valid"])
        self.assertIn("Coupon 'POOJA2026' does not exist", data["message"])

        # 2. COD payment method rejected
        res = self.client.get(reverse("api_apply_coupon") + "?code=DIWALI26&subtotal=90.00&payment_method=cod")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertFalse(data["valid"])
        self.assertIn("online payments", data["message"])

        # 3. Create DIWALI26 coupon (10% off)
        coupon = Coupon.objects.create(
            code="DIWALI26",
            discount_type="percentage",
            discount_value=Decimal("10.00"),
            min_order_amount=Decimal("50.00"),
            is_active=True,
        )

        # 4. Valid coupon with single product checkout
        res = self.client.get(
            reverse("api_apply_coupon")
            + f"?code=DIWALI26&subtotal=90.00&payment_method=online&product_id={self.product.id}&quantity=1"
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["valid"])
        self.assertEqual(data["discount_amount"], 9.0)
        self.assertIn("Coupon 'DIWALI26' applied! Saved ₹9.00", data["message"])

        # 5. Remove coupon API
        res_rm = self.client.get(reverse("api_remove_coupon"))
        self.assertEqual(res_rm.status_code, 200)
        self.assertTrue(res_rm.json()["valid"])

    def test_checkout_and_cart_templates_discount_summary_elements(self):
        """Verify checkout and cart templates have elements for original total, discount breakdown, and discounted total."""
        res_chk = self.client.get(reverse("checkout", kwargs={"product_id": self.product.id}))
        self.assertEqual(res_chk.status_code, 200)
        self.assertContains(res_chk, 'id="chkOriginalTotalRow"')
        self.assertContains(res_chk, 'id="chkDiscountRow"')
        self.assertContains(res_chk, 'id="chkTotalLabel"')
        self.assertContains(res_chk, 'id="chkCouponInput"')
        self.assertContains(res_chk, 'id="chkApplyCouponBtn"')

        # Cart template (populate cart in session first so items are shown)
        session = self.client.session
        session["cart"] = {str(self.product.id): 1}
        session.save()
        res_cart = self.client.get(reverse("cart"))
        self.assertEqual(res_cart.status_code, 200)
        self.assertContains(res_cart, 'id="cartOriginalTotalRow"')
        self.assertContains(res_cart, 'id="cartDiscountRow"')
        self.assertContains(res_cart, 'id="cartTotalLabel"')
        self.assertContains(res_cart, 'id="cartCouponInput"')
        self.assertContains(res_cart, 'id="cartApplyCouponBtn"')


class RazorpayPaymentGatewayTests(TestCase):
    def setUp(self):
        self.category = ProductCategory.objects.create(name="Energy", slug="energy-test")
        self.product = Product.objects.create(
            name="Classic Drink",
            category=self.category,
            volume="330 ml",
            price=Decimal("90.00"),
            available=True,
        )
        self.order = Order.objects.create(
            product=self.product,
            customer_name="Test Customer",
            customer_phone="9876543210",
            quantity=1,
            total_amount=Decimal("156.20"),
            payment_method="online",
            payment_status="pending",
            razorpay_order_id="order_test_mock_123",
        )

    def test_signature_verification(self):
        from main.razorpay_client import verify_razorpay_signature
        import hmac, hashlib
        from django.conf import settings

        order_id = "order_12345"
        payment_id = "pay_67890"
        msg = f"{order_id}|{payment_id}".encode("utf-8")
        sig = hmac.new(settings.RAZORPAY_KEY_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()

        self.assertTrue(verify_razorpay_signature(order_id, payment_id, sig))
        self.assertFalse(verify_razorpay_signature(order_id, payment_id, "invalid_sig"))

    def test_payment_page_renders_razorpay_elements(self):
        url = reverse("payment_page", kwargs={"payment_reference": self.order.payment_reference})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Confirm demo payment")
        self.assertContains(response, "checkout.razorpay.com/v1/checkout.js")
        self.assertContains(response, "confirmDemoPaymentBtn")

    def test_razorpay_create_order_endpoint(self):
        url = reverse("razorpay_create_order", kwargs={"payment_reference": self.order.payment_reference})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["order_id"], "order_test_mock_123")
        self.assertEqual(data["amount"], 15620)

    def test_razorpay_verify_payment_success(self):
        import hmac, hashlib
        from django.conf import settings

        order_id = self.order.razorpay_order_id
        payment_id = "pay_valid_mock_999"
        msg = f"{order_id}|{payment_id}".encode("utf-8")
        sig = hmac.new(settings.RAZORPAY_KEY_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()

        url = reverse("razorpay_verify_payment")
        response = self.client.post(
            url,
            data=json.dumps({
                "payment_reference": str(self.order.payment_reference),
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": sig,
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertIn("receipt", data["redirect_url"])

        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "paid")
        self.assertEqual(self.order.razorpay_payment_id, payment_id)
        self.assertEqual(self.order.payment_event_id, f"rzp_{payment_id}")

    def test_razorpay_verify_payment_invalid_signature_rejected(self):
        url = reverse("razorpay_verify_payment")
        response = self.client.post(
            url,
            data=json.dumps({
                "payment_reference": str(self.order.payment_reference),
                "razorpay_order_id": self.order.razorpay_order_id,
                "razorpay_payment_id": "pay_fake",
                "razorpay_signature": "fake_signature",
            }),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "pending")

    @patch("main.views.verify_razorpay_webhook_signature")
    def test_razorpay_webhook_success(self, mock_verify):
        mock_verify.return_value = (True, "Valid")
        payload = {
            "event": "payment.captured",
            "payload": {
                "order": {"entity": {"id": self.order.razorpay_order_id}},
                "payment": {"entity": {"id": "pay_hook_888", "order_id": self.order.razorpay_order_id}}
            }
        }
        response = self.client.post(
            reverse("razorpay_webhook"),
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_X_RAZORPAY_SIGNATURE="mock_sig",
        )
        self.assertEqual(response.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, "paid")
        self.assertEqual(self.order.razorpay_payment_id, "pay_hook_888")

    def test_razorpay_webhook_invalid_signature_rejected(self):
        response = self.client.post(
            reverse("razorpay_webhook"),
            data=json.dumps({"some": "data"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)


class ComboOfferTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="testuser", password="password123")
        self.admin = get_user_model().objects.create_superuser(username="adminuser", password="password123", email="admin@example.com")
        self.cat_cola = ProductCategory.objects.create(name="Cola", slug="cola")
        self.cat_energy = ProductCategory.objects.create(name="Energy Drink", slug="energy_drink")
        self.cat_others = ProductCategory.objects.create(name="Others", slug="others")

        self.products = []
        for i in range(1, 9):
            p = Product.objects.create(
                name=f"Can Flavour {i}",
                category="cola" if i <= 3 else "others",
                price=Decimal("90.00"),
                volume="330 ml",
                available=True,
            )
            self.products.append(p)

        self.combo = ComboOffer.objects.create(
            name="Cans of Assortment",
            offer_type="multiple_products",
            discount_type="percentage",
            discount_value=Decimal("15.00"),
            max_discount_cap=Decimal("100.00"),
            min_order_amount=Decimal("6.00"),
            min_quantity=6,
            min_distinct_products=6,
            badge_text="Cans of Assortment",
            is_active=True,
        )

    def test_combo_offer_creation_and_properties(self):
        self.assertTrue(self.combo.is_valid_status)
        self.assertFalse(self.combo.is_expired)
        self.assertFalse(self.combo.is_usage_limit_reached)
        self.assertIn("15% OFF", self.combo.discount_display)
        self.assertEqual(self.combo.offer_type_display, "Multiple Products Combo")

    def test_cans_of_assortment_triggers_with_6_distinct_cans(self):
        cart_items = [
            {"product": self.products[i], "quantity": 1, "line_total": self.products[i].price}
            for i in range(6)
        ]
        subtotal = sum(it["line_total"] for it in cart_items)  # 6 * 90 = 540
        qualifies, discount, details = self.combo.evaluate_cart(cart_items, subtotal)
        self.assertTrue(qualifies)
        # 15% of 540 = 81.00
        self.assertEqual(discount, Decimal("81.00"))
        self.assertEqual(details["badge_text"], "Cans of Assortment")
        self.assertEqual(details["distinct_count"], 6)

    def test_cans_of_assortment_fails_with_6_same_cans(self):
        cart_items = [
            {"product": self.products[0], "quantity": 6, "line_total": self.products[0].price * 6}
        ]
        subtotal = Decimal("540.00")
        qualifies, discount, details = self.combo.evaluate_cart(cart_items, subtotal)
        self.assertFalse(qualifies)
        self.assertEqual(discount, Decimal("0.00"))

    def test_cans_of_assortment_fails_with_fewer_than_6_cans(self):
        cart_items = [
            {"product": self.products[i], "quantity": 1, "line_total": self.products[i].price}
            for i in range(5)
        ]
        subtotal = Decimal("450.00")
        qualifies, discount, details = self.combo.evaluate_cart(cart_items, subtotal)
        self.assertFalse(qualifies)
        self.assertEqual(discount, Decimal("0.00"))

    def test_max_discount_cap_enforced(self):
        # Create a combo with 50% discount capped at 50
        capped_combo = ComboOffer.objects.create(
            name="Super Capped Combo",
            offer_type="price_based",
            discount_type="percentage",
            discount_value=Decimal("50.00"),
            max_discount_cap=Decimal("50.00"),
            min_order_amount=Decimal("100.00"),
            is_active=True,
        )
        cart_items = [{"product": self.products[0], "quantity": 10, "line_total": Decimal("900.00")}]
        qualifies, discount, details = capped_combo.evaluate_cart(cart_items, Decimal("900.00"))
        self.assertTrue(qualifies)
        # 50% of 900 is 450, but capped at 50
        self.assertEqual(discount, Decimal("50.00"))

    def test_combos_showcase_redirects_to_home_shop(self):
        response = self.client.get(reverse("combos_showcase"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].endswith("#shop"))

    def test_home_page_displays_combos_category_and_pack(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-filter-category="combo"')
        self.assertContains(response, "Combos")
        self.assertContains(response, "Cans of Assortment")
        self.assertNotContains(response, "✨ Combo Offers")

    def test_admin_combo_creation_with_image(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.client.force_login(self.admin)
        gif_bytes = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
        test_image = SimpleUploadedFile("pack.gif", gif_bytes, content_type="image/gif")
        response = self.client.post(
            reverse("admin_combos"),
            data={
                "name": "Summer 6 Pack",
                "offer_type": "multiple_products",
                "image": test_image,
                "discount_type": "percentage",
                "discount_value": "20.00",
                "min_order_amount": "6.00",
                "min_quantity": 6,
                "min_distinct_products": 6,
                "badge_text": "Summer Pack",
                "is_active": True,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        new_combo = ComboOffer.objects.filter(name="Summer 6 Pack").first()
        self.assertIsNotNone(new_combo)
        self.assertTrue(bool(new_combo.image))

    def test_admin_combo_creation_with_selective_products(self):
        self.client.force_login(self.admin)
        selected_pids = [self.products[0].id, self.products[1].id, self.products[2].id]
        response = self.client.post(
            reverse("admin_combos"),
            data={
                "name": "Cola Trio Special",
                "offer_type": "multiple_products",
                "applicable_products": selected_pids,
                "discount_type": "percentage",
                "discount_value": "10.00",
                "min_order_amount": "6.00",
                "min_quantity": 3,
                "min_distinct_products": 3,
                "badge_text": "Trio Pack",
                "is_active": True,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        trio = ComboOffer.objects.filter(name="Cola Trio Special").first()
        self.assertIsNotNone(trio)
        self.assertEqual(trio.applicable_products.count(), 3)
        self.assertIn(self.products[0].name, trio.products_display)

    def test_admin_edit_combo_view(self):
        self.client.force_login(self.admin)
        # Edit the existing combo
        edit_url = reverse("admin_edit_combo", kwargs={"combo_id": self.combo.id})
        selected_pids = [self.products[0].id, self.products[1].id]
        response = self.client.post(
            edit_url,
            data={
                "name": "Cans of Assortment Updated",
                "bundle_product_ids": selected_pids,
                f"product_qty_{selected_pids[0]}": "3",
                f"product_qty_{selected_pids[1]}": "3",
                "discount_type": "percentage",
                "discount_value": "25.00",
                "max_discount_cap": "150.00",
                "description": "Updated promo description",
                "is_active": True,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.combo.refresh_from_db()
        self.assertEqual(self.combo.name, "Cans of Assortment Updated")
        self.assertEqual(self.combo.discount_value, Decimal("25.00"))
        self.assertEqual(self.combo.bundle_items.count(), 2)
        self.assertEqual(self.combo.total_bundle_cans, 6)

    def test_add_bundle_to_cart_view(self):
        bundle_url = reverse("add_bundle_to_cart", kwargs={"combo_id": self.combo.id})
        response = self.client.post(bundle_url, follow=True)
        self.assertEqual(response.status_code, 200)
        cart = self.client.session.get("cart", {})
        self.assertGreaterEqual(len(cart), 6)
        self.assertContains(response, "Cans of Assortment")

    def test_add_assortment_combo_to_cart_action(self):
        response = self.client.post(reverse("add_assortment_combo_to_cart"), follow=True)
        self.assertEqual(response.status_code, 200)
        cart = self.client.session.get("cart", {})
        self.assertGreaterEqual(len(cart), 6)
        self.assertContains(response, "Cans of Assortment")

    def test_cart_page_displays_cans_of_assortment(self):
        session = self.client.session
        session["cart"] = {str(self.products[i].id): 1 for i in range(6)}
        session.save()

        response = self.client.get(reverse("cart"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cans of Assortment")
        self.assertContains(response, "COMBO OFFER APPLIED")

    def test_single_flavor_bundle_lime_blast_applies_and_reflects_in_cart(self):
        lime_combo = ComboOffer.objects.create(
            name="lime blast",
            discount_type="percentage",
            discount_value=Decimal("15.00"),
            max_discount_cap=Decimal("600.00"),
            is_active=True,
        )
        from main.models import ComboBundleItem
        ComboBundleItem.objects.create(combo_offer=lime_combo, product=self.products[0], quantity=6)

        # User adds lime blast bundle to cart
        add_url = reverse("add_bundle_to_cart", kwargs={"combo_id": lime_combo.id})
        res_add = self.client.post(add_url, follow=True)
        self.assertEqual(res_add.status_code, 200)

        # Cart should have 6 of product[0]
        cart = self.client.session.get("cart", {})
        self.assertEqual(cart.get(str(self.products[0].id)), 6)

        # Cart page should reflect combo discount
        res_cart = self.client.get(reverse("cart"))
        self.assertEqual(res_cart.status_code, 200)
        self.assertContains(res_cart, "lime blast")
        self.assertContains(res_cart, "COMBO OFFER APPLIED")
        self.assertContains(res_cart, "cartComboRow")
        self.assertContains(res_cart, "-₹81.00")

    def test_cart_checkout_saves_combo_offer_fields(self):
        session = self.client.session
        session["cart"] = {str(self.products[i].id): 1 for i in range(6)}
        session.save()

        post_data = {
            "first_name": "Combo",
            "last_name": "Tester",
            "email": "combo@test.com",
            "phone": "9876543210",
            "address": "123 Beverage Road",
            "city": "Chennai",
            "state": "Tamil Nadu",
            "postal_code": "600001",
            "payment_method": "online",
        }
        response = self.client.post(reverse("cart_checkout"), data=post_data)
        self.assertEqual(response.status_code, 302)

        order = Order.objects.order_by("-id").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.combo_offer, self.combo)
        self.assertEqual(order.combo_name, "Cans of Assortment")
        self.assertEqual(order.combo_discount, Decimal("81.00"))

    def test_admin_combos_view_requires_staff(self):
        # Anonymous
        response = self.client.get(reverse("admin_combos"))
        self.assertEqual(response.status_code, 302)

        # Non-staff
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin_combos"))
        self.assertEqual(response.status_code, 302)

        # Staff
        self.client.force_login(self.admin)
        response = self.client.get(reverse("admin_combos"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Combo Offers")

    def test_admin_create_toggle_delete_combo(self):
        self.client.force_login(self.admin)

        # Create
        create_data = {
            "name": "Weekend Party Pack",
            "offer_type": "price_based",
            "discount_type": "fixed",
            "discount_value": "75.00",
            "min_order_amount": "500.00",
            "min_quantity": 4,
            "min_distinct_products": 2,
            "is_active": True,
        }
        response = self.client.post(reverse("admin_combos"), data=create_data, follow=True)
        self.assertEqual(response.status_code, 200)
        new_combo = ComboOffer.objects.filter(name="Weekend Party Pack").first()
        self.assertIsNotNone(new_combo)
        self.assertTrue(new_combo.is_active)

        # Toggle
        toggle_res = self.client.post(reverse("admin_toggle_combo", kwargs={"combo_id": new_combo.id}), follow=True)
        self.assertEqual(toggle_res.status_code, 200)
        new_combo.refresh_from_db()
        self.assertFalse(new_combo.is_active)


class WebsiteVisitorTrackingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="testvisitor", email="visitor@example.com", password="password123")
        self.admin = User.objects.create_superuser(username="adminvisitor", email="adminvis@example.com", password="password123")
        self.wifi_ip = "192.168.1.100"

    def test_combo_discount_display_has_no_capped_cost(self):
        combo = ComboOffer.objects.create(
            name="Zero Cola Combo",
            discount_type="percentage",
            discount_value=Decimal("12.00"),
            max_discount_cap=Decimal("2000.00"),
            is_active=True,
        )
        self.assertEqual(combo.discount_display, "12% OFF")
        self.assertNotIn("Capped", combo.discount_display)
        self.assertNotIn("capped", combo.discount_display.lower())

    def test_middleware_records_unique_wifi_ip_view(self):
        # 1st request from WiFi IP as guest
        response = self.client.get(reverse("home"), HTTP_X_FORWARDED_FOR=self.wifi_ip)
        self.assertEqual(response.status_code, 200)

        record = WebsiteView.objects.filter(ip_address=self.wifi_ip).first()
        self.assertIsNotNone(record)
        self.assertEqual(record.view_count, 1)
        self.assertIsNone(record.user)
        self.assertEqual(record.username_display, "Guest")

        # 2nd request from the same WiFi IP
        self.client.get(reverse("home"), HTTP_X_FORWARDED_FOR=self.wifi_ip)
        today = timezone.localdate()
        # Count of unique records for this WiFi IP today must remain exactly 1!
        self.assertEqual(WebsiteView.objects.filter(date=today, ip_address=self.wifi_ip).count(), 1)
        record.refresh_from_db()
        self.assertEqual(record.view_count, 2)

    def test_multiple_logins_on_same_wifi_count_as_one_view_and_link_user(self):
        today = timezone.localdate()
        # Guest visit from WiFi IP
        self.client.get(reverse("home"), HTTP_X_FORWARDED_FOR=self.wifi_ip)
        self.assertEqual(WebsiteView.objects.filter(date=today, ip_address=self.wifi_ip).count(), 1)

        # User logs in and visits from the same WiFi IP
        self.client.force_login(self.user)
        self.client.get(reverse("home"), HTTP_X_FORWARDED_FOR=self.wifi_ip)

        # Still only 1 unique daily view record for that WiFi IP!
        self.assertEqual(WebsiteView.objects.filter(date=today, ip_address=self.wifi_ip).count(), 1)
        record = WebsiteView.objects.get(date=today, ip_address=self.wifi_ip)
        self.assertEqual(record.user, self.user)
        self.assertEqual(record.username_display, self.user.username)
        self.assertEqual(record.user_email, self.user.email)
        self.assertEqual(record.view_count, 2)

    def test_different_wifi_ips_count_as_separate_views(self):
        today = timezone.localdate()
        ip_1 = "10.0.0.1"
        ip_2 = "10.0.0.2"
        self.client.get(reverse("home"), HTTP_X_FORWARDED_FOR=ip_1)
        self.client.get(reverse("home"), HTTP_X_FORWARDED_FOR=ip_2)

        self.assertEqual(WebsiteView.objects.filter(date=today).count(), 2)

    def test_admin_visitors_view_security_and_rendering(self):
        # Anonymous is redirected
        anon_resp = self.client.get(reverse("admin_visitors"))
        self.assertEqual(anon_resp.status_code, 302)

        # Non-staff user redirected or forbidden
        self.client.force_login(self.user)
        user_resp = self.client.get(reverse("admin_visitors"))
        self.assertEqual(user_resp.status_code, 302)

        # Staff user gets 200 and sees visitor details
        self.client.force_login(self.admin)
        admin_resp = self.client.get(reverse("admin_visitors"))
        self.assertEqual(admin_resp.status_code, 200)
        self.assertContains(admin_resp, "Website Visitors & Traffic")
        self.assertContains(admin_resp, "Today's Unique Views")
        self.assertContains(admin_resp, "WiFi IP Address")


class AdminDashboardOperationsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff_user = User.objects.create_superuser(
            username="superadmin", email="superadmin@example.com", password="password123"
        )
        self.normal_user = User.objects.create_user(
            username="regularuser", email="user@example.com", password="password123"
        )
        self.product = Product.objects.create(
            name="Test Fizzy Drink",
            price=Decimal("90.00"),
            available=True,
            volume="330 ml",
        )
        # 1. New Pending Order
        self.pending_order = Order.objects.create(
            customer=self.normal_user,
            product=self.product,
            customer_name="Alice Green",
            customer_phone="9876543210",
            delivery_address="456 Elm Street",
            delivery_city="Chennai",
            delivery_postal_code="600001",
            quantity=2,
            total_amount=Decimal("180.00"),
            status="pending",
            payment_status="paid",
        )
        # 2. Packed Order (Delivery requested / dispatch pending)
        self.packed_order = Order.objects.create(
            customer=self.normal_user,
            product=self.product,
            customer_name="Bob Brown",
            customer_phone="9123456780",
            delivery_address="789 Oak Ave",
            delivery_city="Chennai",
            delivery_postal_code="600002",
            quantity=6,
            total_amount=Decimal("540.00"),
            status="packed",
            payment_status="paid",
        )
        # 3. Pending Delivery Partner Applicant
        self.driver_user = User.objects.create_user(
            username="speedydriver", email="speedy@example.com", password="password123"
        )
        self.pending_partner = DeliveryProfile.objects.create(
            user=self.driver_user,
            phone="9988776655",
            vehicle_type="bike",
            vehicle_number="TN-59-AB-1234",
            driving_license="DL99887766",
            aadhar_number="1234-5678-9012",
            status="pending",
            is_approved=False,
        )

    def test_anonymous_redirected_from_dashboard(self):
        resp = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(resp.status_code, 302)

    def test_normal_user_redirected_from_dashboard(self):
        self.client.force_login(self.normal_user)
        resp = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(resp.status_code, 302)

    def test_staff_can_view_operations_dashboard_with_all_three_sections(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("admin_dashboard"))
        self.assertEqual(resp.status_code, 200)

        # 1. Verification of the 3 key sections in the dashboard
        self.assertContains(resp, "Operations Dashboard")
        self.assertContains(resp, "New Incoming Orders")
        self.assertContains(resp, "Delivery Requested Orders")
        self.assertContains(resp, "Delivery Partner Approval Requests")

        # 2. Section 1: Only new pending orders shown
        self.assertContains(resp, "Alice Green")
        self.assertContains(resp, "#" + str(self.pending_order.order_number or self.pending_order.id))
        self.assertContains(resp, "Mark Packed")

        # 3. Section 2: Delivery requested (packed orders) shown
        self.assertContains(resp, "Bob Brown")
        self.assertContains(resp, "#" + str(self.packed_order.order_number or self.packed_order.id))
        self.assertContains(resp, "Packed (Ready for Dispatch)")

        # 4. Section 3: Delivery partner approval requests shown
        self.assertContains(resp, "speedydriver")
        self.assertContains(resp, "TN-59-AB-1234")
        self.assertContains(resp, "DL99887766")
        self.assertContains(resp, "Approve")
        self.assertContains(resp, "Reject")

    def test_admin_can_approve_partner_from_dashboard(self):
        self.client.force_login(self.staff_user)
        post_data = {"next": reverse("admin_dashboard")}
        resp = self.client.post(
            reverse("admin_approve_delivery_partner", kwargs={"profile_id": self.pending_partner.id}),
            data=post_data,
        )
        self.assertRedirects(resp, reverse("admin_dashboard"))
        self.pending_partner.refresh_from_db()
        self.assertTrue(self.pending_partner.is_approved)
        self.assertEqual(self.pending_partner.status, "approved")

    def test_admin_can_mark_order_packed_from_dashboard(self):
        self.client.force_login(self.staff_user)
        post_data = {"status": "packed", "next": reverse("admin_dashboard")}
        resp = self.client.post(
            reverse("admin_update_order_status", kwargs={"order_id": self.pending_order.id}),
            data=post_data,
        )
        self.assertRedirects(resp, reverse("admin_dashboard"))
        self.pending_order.refresh_from_db()
        self.assertEqual(self.pending_order.status, "packed")


class ProductCostPriceAndBulkAddTests(TestCase):
    def setUp(self):
        self.staff_user = get_user_model().objects.create_user(
            username="productadmin", password="password123", is_staff=True
        )
        self.normal_user = get_user_model().objects.create_user(
            username="normaluser", password="password123", is_staff=False
        )

    def test_product_default_cost_price_and_profit(self):
        product = Product.objects.create(name="Mango Spark", price=Decimal("90.00"))
        self.assertEqual(product.cost_price, Decimal("60.00"))
        # Pre-tax net profit: base price (76.27) - cost price (60.00) = 16.27 (margin 21.3%)
        self.assertEqual(product.profit_amount, Decimal("16.27"))
        self.assertEqual(product.profit_margin_percent, Decimal("21.3"))

    def test_custom_cost_price(self):
        product = Product.objects.create(
            name="Premium Cola", cost_price=Decimal("50.00"), price=Decimal("100.00")
        )
        self.assertEqual(product.cost_price, Decimal("50.00"))
        # Pre-tax net profit with 18% GST: base price (84.75) - cost price (50.00) = 34.75 (margin 41.0%)
        self.assertEqual(product.profit_amount, Decimal("34.75"))
        self.assertEqual(product.profit_margin_percent, Decimal("41.0"))

        # Zero GST rate (0%): profit = 100.00 - 50.00 = 50.00 (margin 50.0%)
        product_zero_gst = Product.objects.create(
            name="Zero GST Drink", cost_price=Decimal("50.00"), price=Decimal("100.00"), gst_rate=0
        )
        self.assertEqual(product_zero_gst.profit_amount, Decimal("50.00"))
        self.assertEqual(product_zero_gst.profit_margin_percent, Decimal("50.0"))

    def test_product_admin_displays_cost_and_bulk_button(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("admin_products"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bulk Add Products")
        self.assertContains(resp, "Cost Price (₹)")
        self.assertContains(resp, "Recommended: ₹60")

    def test_bulk_add_products_get(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("admin_bulk_add_products"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Bulk Product Ingestion")
        self.assertContains(resp, "Recommended Store Unit Cost")
        self.assertContains(resp, "60.00")

    def test_bulk_add_products_post_creates_multiple_products(self):
        self.client.force_login(self.staff_user)
        post_data = {
            "row_index": ["1", "2", "3"],
            "name_1": "Guava Blast",
            "category_1": "others",
            "cost_price_1": "60.00",
            "price_1": "90.00",
            "volume_1": "330 ml",
            "available_1": "1",
            "name_2": "Berry Cooler",
            "category_2": "energy_drink",
            "cost_price_2": "55.00",
            "price_2": "95.00",
            "volume_2": "330 ml",
            "available_2": "1",
            "name_3": "",
            "cost_price_3": "60.00",
            "price_3": "90.00",
        }
        resp = self.client.post(reverse("admin_bulk_add_products"), data=post_data)
        self.assertRedirects(resp, reverse("admin_products"))

        p1 = Product.objects.get(name="Guava Blast")
        self.assertEqual(p1.cost_price, Decimal("60.00"))
        self.assertEqual(p1.price, Decimal("90.00"))
        self.assertEqual(p1.category, "others")
        self.assertTrue(p1.available)

        p2 = Product.objects.get(name="Berry Cooler")
        self.assertEqual(p2.cost_price, Decimal("55.00"))
        self.assertEqual(p2.price, Decimal("95.00"))
        self.assertEqual(p2.category, "energy_drink")

        self.assertFalse(Product.objects.filter(name="").exists())


class AdminUsersAndSalesReportTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff_user = User.objects.create_user(
            username="test_admin_staff",
            email="staff@store.com",
            password="adminpassword123",
            is_staff=True,
        )
        self.customer_user = User.objects.create_user(
            username="alex_customer",
            email="alex@customer.com",
            first_name="Alex",
            last_name="Johnson",
            password="customerpassword123",
            is_staff=False,
        )
        self.prod_a = Product.objects.create(
            name="Classic Cola Can",
            price=Decimal("90.00"),
            cost_price=Decimal("60.00"),
            category="classic_cola",
            available=True,
        )
        self.prod_b = Product.objects.create(
            name="Fresh Lime Can",
            price=Decimal("90.00"),
            cost_price=Decimal("50.00"),
            category="lime_soda",
            available=True,
        )
        self.order1 = Order.objects.create(
            customer=self.customer_user,
            customer_name="Alex Johnson",
            customer_phone="9876543210",
            delivery_address="123 High Street",
            delivery_city="Chennai",
            product=self.prod_a,
            quantity=2,
            total_amount=Decimal("180.00"),
            status="delivered",
            payment_status="paid",
        )
        OrderItem.objects.create(
            order=self.order1,
            product=self.prod_a,
            quantity=2,
            unit_price=Decimal("90.00"),
        )

    def test_admin_users_access_control(self):
        resp_anon = self.client.get(reverse("admin_users"))
        self.assertEqual(resp_anon.status_code, 302)

        self.client.force_login(self.customer_user)
        resp_cust = self.client.get(reverse("admin_users"))
        self.assertRedirects(resp_cust, reverse("home"))

        self.client.force_login(self.staff_user)
        resp_staff = self.client.get(reverse("admin_users"))
        self.assertEqual(resp_staff.status_code, 200)
        self.assertContains(resp_staff, "Users & Customer Accounts")
        self.assertContains(resp_staff, "alex_customer")
        self.assertContains(resp_staff, "Alex Johnson")

    def test_admin_users_search_and_filter(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(f"{reverse('admin_users')}?q=alex")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "alex_customer")

        resp_none = self.client.get(f"{reverse('admin_users')}?q=nonexistentuserxyz")
        self.assertEqual(resp_none.status_code, 200)
        self.assertContains(resp_none, "No registered users found")

    def test_admin_reports_access_and_profit_calculations(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("admin_reports"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Sales & Profit/Loss Report")
        self.assertContains(resp, "Which Product Sells More")
        self.assertContains(resp, "Which Product Is More Buying")

        self.assertEqual(resp.context["gross_sales"], Decimal("180.00"))
        self.assertEqual(resp.context["total_gst_collected"], Decimal("27.46"))
        self.assertEqual(resp.context["net_sales"], Decimal("152.54"))
        self.assertEqual(resp.context["total_cogs"], Decimal("120.00"))
        self.assertEqual(resp.context["net_profit"], Decimal("32.54"))
        self.assertTrue(resp.context["is_profitable"])

    def test_admin_reports_export_csv(self):
        self.client.force_login(self.staff_user)
        resp = self.client.get(reverse("admin_reports_export_csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        self.assertIn("Classic Cola Can", resp.content.decode("utf-8"))

    def test_random_order_number_generation(self):
        order = Order.objects.create(
            customer=self.customer_user,
            product=self.prod_a,
            quantity=1,
            total_amount=Decimal("90.00"),
        )
        self.assertIsNotNone(order.order_number)
        self.assertEqual(len(order.order_number), 6)
        self.assertTrue(order.order_number.isdigit())
        self.assertEqual(order.display_order_number, f"#{order.order_number}")


class DailyPromoPopupTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff_user = User.objects.create_user(
            username="popup_admin", email="popup@admin.com", password="password123", is_staff=True
        )
        self.customer = User.objects.create_user(
            username="popup_shopper", email="shopper@test.com", password="password123"
        )
        self.prod = Product.objects.create(
            name="Sparkling Citrus Can",
            price=Decimal("90.00"),
            cost_price=Decimal("60.00"),
            available=True,
        )
        self.combo = ComboOffer.objects.create(
            name="Weekend Party Pack",
            discount_type="percentage",
            discount_value=Decimal("20.00"),
            is_active=True,
            description="6 pack of ice cold citrus soda",
        )
        self.coupon = Coupon.objects.create(
            code="SAVE15",
            discount_type="percentage",
            discount_value=Decimal("15.00"),
            min_order_amount=Decimal("200.00"),
            is_active=True,
        )
        self.details = SiteDetails.get_solo()
        self.details.popup_enabled = True
        self.details.popup_offer_type = "combo"
        self.details.popup_combo = self.combo
        self.details.save()

    def test_popup_returns_none_when_disabled(self):
        self.details.popup_enabled = False
        self.details.save()
        self.assertIsNone(self.details.get_active_popup_offer())

    def test_popup_returns_active_combo_offer(self):
        offer = self.details.get_active_popup_offer()
        self.assertIsNotNone(offer)
        self.assertEqual(offer["type"], "combo")
        self.assertEqual(offer["id"], self.combo.id)
        self.assertEqual(offer["title"], "Special Deal of the Day!")
        self.assertIn("20% OFF", offer["discount_display"])

    def test_popup_returns_active_coupon_offer(self):
        self.details.popup_offer_type = "coupon"
        self.details.popup_coupon = self.coupon
        self.details.popup_title = "Flash Discount Code"
        self.details.save()

        offer = self.details.get_active_popup_offer()
        self.assertIsNotNone(offer)
        self.assertEqual(offer["type"], "coupon")
        self.assertEqual(offer["code"], "SAVE15")
        self.assertEqual(offer["title"], "Flash Discount Code")
        self.assertIn("15% OFF", offer["discount_display"])

    def test_admin_details_save_popup_settings(self):
        self.client.force_login(self.staff_user)
        post_data = {
            "action": "save_popup",
            "popup_enabled": "on",
            "popup_offer_type": "coupon",
            "popup_coupon": str(self.coupon.id),
            "popup_combo": "",
            "popup_title": "Exclusive Today Only",
            "popup_message": "Apply this code at checkout to save big!",
            "popup_badge_text": "DAILY REWARD",
        }
        resp = self.client.post(f"{reverse('admin_details')}?tab=popup", data=post_data)
        self.assertRedirects(resp, f"{reverse('admin_details')}?tab=popup")

        self.details.refresh_from_db()
        self.assertTrue(self.details.popup_enabled)
        self.assertEqual(self.details.popup_offer_type, "coupon")
        self.assertEqual(self.details.popup_coupon, self.coupon)
        self.assertEqual(self.details.popup_title, "Exclusive Today Only")
        self.assertEqual(self.details.popup_badge_text, "DAILY REWARD")

    def test_admin_set_popup_offer_one_click_actions(self):
        self.client.force_login(self.staff_user)

        # 1-click feature coupon
        resp = self.client.post(
            reverse("admin_set_popup_offer"),
            data={"offer_type": "coupon", "offer_id": str(self.coupon.id)},
        )
        self.assertRedirects(resp, reverse("admin_coupons"))
        self.details.refresh_from_db()
        self.assertTrue(self.details.popup_enabled)
        self.assertEqual(self.details.popup_offer_type, "coupon")
        self.assertEqual(self.details.popup_coupon, self.coupon)

        # 1-click feature combo
        resp = self.client.post(
            reverse("admin_set_popup_offer"),
            data={"offer_type": "combo", "offer_id": str(self.combo.id)},
        )
        self.assertRedirects(resp, reverse("admin_combos"))
        self.details.refresh_from_db()
        self.assertTrue(self.details.popup_enabled)
        self.assertEqual(self.details.popup_offer_type, "combo")
        self.assertEqual(self.details.popup_combo, self.combo)

    def test_storefront_renders_popup_and_frequency_script(self):
        # When popup enabled, modal is rendered with local storage frequency cap key
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "dailyPromoModal")
        self.assertContains(resp, "jcsd_daily_promo_seen_date")
        self.assertContains(resp, "Weekend Party Pack")

        # When popup disabled, modal is NOT rendered in DOM
        self.details.popup_enabled = False
        self.details.save()
        resp_disabled = self.client.get(reverse("home"))
        self.assertNotContains(resp_disabled, "dailyPromoModal")


class TableCsvExportsTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff_user = User.objects.create_user(
            username="export_admin", email="admin@export.com", password="password123", is_staff=True
        )
        self.normal_user = User.objects.create_user(
            username="regular_shopper", email="shopper@export.com", password="password123"
        )
        self.driver_user = User.objects.create_user(
            username="delivery_pro", email="pro@driver.com", password="password123"
        )
        self.driver_profile = DeliveryProfile.objects.create(
            user=self.driver_user,
            phone="9876501234",
            vehicle_type="bike",
            vehicle_number="TN-01-AB-9999",
            driving_license="DL12345678",
            aadhar_number="9876-5432-1098",
            serviceable_pincodes="600001, 600002",
            status="pending",
            is_approved=False,
        )
        self.product = Product.objects.create(
            name="Ginger Fizz Can",
            price=Decimal("90.00"),
            cost_price=Decimal("60.00"),
            category="ginger_fizz",
            available=True,
        )
        self.pending_order = Order.objects.create(
            customer=self.normal_user,
            customer_name="John Shopper",
            customer_phone="9876543210",
            delivery_address="12 Ocean Drive",
            delivery_city="Chennai",
            delivery_postal_code="600001",
            product=self.product,
            quantity=3,
            total_amount=Decimal("270.00"),
            status="pending",
            payment_status="paid",
        )
        self.packed_order = Order.objects.create(
            customer=self.normal_user,
            customer_name="Mary Jane",
            customer_phone="9123456789",
            delivery_address="34 Marina View",
            delivery_city="Chennai",
            delivery_postal_code="600002",
            product=self.product,
            quantity=2,
            total_amount=Decimal("180.00"),
            status="packed",
            payment_status="paid",
        )

    def test_anonymous_and_non_staff_denied_from_exports(self):
        endpoints = [
            reverse("admin_reports_export_csv"),
            reverse("admin_orders_export_csv"),
            reverse("admin_dashboard_export_csv"),
        ]
        for url in endpoints:
            with self.subTest(url=url):
                # Anonymous
                resp_anon = self.client.get(url)
                self.assertEqual(resp_anon.status_code, 302)

                # Non-staff
                self.client.force_login(self.normal_user)
                resp_norm = self.client.get(url)
                self.assertEqual(resp_norm.status_code, 302)

    def test_admin_reports_table_csv_exports(self):
        self.client.force_login(self.staff_user)

        # 1. Full report
        resp_all = self.client.get(f"{reverse('admin_reports_export_csv')}?table=all")
        self.assertEqual(resp_all.status_code, 200)
        self.assertEqual(resp_all["Content-Type"], "text/csv")
        content_all = resp_all.content.decode("utf-8")
        self.assertIn("J CSD SALES & PROFIT/LOSS REPORT", content_all)
        self.assertIn("Ginger Fizz Can", content_all)

        # 2. Table: Selling Most
        resp_selling = self.client.get(f"{reverse('admin_reports_export_csv')}?table=selling_most")
        self.assertEqual(resp_selling.status_code, 200)
        content_selling = resp_selling.content.decode("utf-8")
        self.assertIn("Rank,Product Name,Category", content_selling)
        self.assertIn("Ginger Fizz Can", content_selling)

        # 3. Table: Buying Most
        resp_buying = self.client.get(f"{reverse('admin_reports_export_csv')}?table=buying_most")
        self.assertEqual(resp_buying.status_code, 200)
        content_buying = resp_buying.content.decode("utf-8")
        self.assertIn("Orders Appeared In", content_buying)
        self.assertIn("Order Inclusion Rate", content_buying)

        # 4. Table: Categories
        resp_cat = self.client.get(f"{reverse('admin_reports_export_csv')}?table=categories")
        self.assertEqual(resp_cat.status_code, 200)
        content_cat = resp_cat.content.decode("utf-8")
        self.assertIn("Category,Units Sold", content_cat)

        # 5. Table: Orders Log
        resp_log = self.client.get(f"{reverse('admin_reports_export_csv')}?table=orders_log")
        self.assertEqual(resp_log.status_code, 200)
        content_log = resp_log.content.decode("utf-8")
        self.assertIn("John Shopper", content_log)
        self.assertIn("Order Net Profit", content_log)

    def test_admin_customer_orders_csv_export(self):
        self.client.force_login(self.staff_user)

        # Export all orders
        resp = self.client.get(reverse("admin_orders_export_csv"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        content = resp.content.decode("utf-8")
        self.assertIn("John Shopper", content)
        self.assertIn("Mary Jane", content)
        self.assertIn("12 Ocean Drive", content)

        # Export filtered by status=pending
        resp_pending = self.client.get(f"{reverse('admin_orders_export_csv')}?status=pending")
        self.assertEqual(resp_pending.status_code, 200)
        content_pending = resp_pending.content.decode("utf-8")
        self.assertIn("John Shopper", content_pending)
        self.assertNotIn("Mary Jane", content_pending)

    def test_admin_dashboard_csv_exports(self):
        self.client.force_login(self.staff_user)

        # 1. Full dashboard workbook
        resp_dash_all = self.client.get(reverse("admin_dashboard_export_csv"))
        self.assertEqual(resp_dash_all.status_code, 200)
        self.assertEqual(resp_dash_all["Content-Type"], "text/csv")
        content_dash_all = resp_dash_all.content.decode("utf-8")
        self.assertIn("NEW INCOMING ORDERS", content_dash_all)
        self.assertIn("DELIVERY DISPATCH QUEUE", content_dash_all)
        self.assertIn("DELIVERY PARTNER APPROVAL REQUESTS", content_dash_all)

        # 2. Section: new_orders
        resp_new = self.client.get(f"{reverse('admin_dashboard_export_csv')}?section=new_orders")
        self.assertEqual(resp_new.status_code, 200)
        content_new = resp_new.content.decode("utf-8")
        self.assertIn("John Shopper", content_new)
        self.assertNotIn("Mary Jane", content_new)

        # 3. Section: delivery_requested
        resp_deliv = self.client.get(f"{reverse('admin_dashboard_export_csv')}?section=delivery_requested")
        self.assertEqual(resp_deliv.status_code, 200)
        content_deliv = resp_deliv.content.decode("utf-8")
        self.assertIn("Mary Jane", content_deliv)
        self.assertNotIn("John Shopper", content_deliv)

        # 4. Section: partner_approvals
        resp_part = self.client.get(f"{reverse('admin_dashboard_export_csv')}?section=partner_approvals")
        self.assertEqual(resp_part.status_code, 200)
        content_part = resp_part.content.decode("utf-8")
        self.assertIn("delivery_pro", content_part)
        self.assertIn("TN-01-AB-9999", content_part)


class GSTRateAndInclusivePricingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin_user = User.objects.create_user(
            username="gst_admin",
            password="adminpassword123",
            is_staff=True,
        )
        cls.customer = User.objects.create_user(
            username="gst_shopper",
            password="shopperpassword123",
            is_staff=False,
        )

        # Products with each GST rate: 0%, 5%, 18%, 40%
        cls.prod_0 = Product.objects.create(
            name="Mineral Water Zero GST",
            price=Decimal("50.00"),
            cost_price=Decimal("30.00"),
            gst_rate=0,
            available=True,
        )
        cls.prod_5 = Product.objects.create(
            name="Milk Drink Five GST",
            price=Decimal("105.00"),
            cost_price=Decimal("70.00"),
            gst_rate=5,
            available=True,
        )
        cls.prod_18 = Product.objects.create(
            name="Soda Eighteen GST",
            price=Decimal("118.00"),
            cost_price=Decimal("60.00"),
            gst_rate=18,
            available=True,
        )
        cls.prod_40 = Product.objects.create(
            name="Caffeinated Energy Forty GST",
            price=Decimal("140.00"),
            cost_price=Decimal("60.00"),
            gst_rate=40,
            available=True,
        )

    def test_gst_rates_and_base_price_auto_calculation(self):
        # 0% GST: Base price == Selling price
        self.prod_0.refresh_from_db()
        self.assertEqual(self.prod_0.base_price, Decimal("50.00"))
        self.assertEqual(self.prod_0.gst_amount_per_unit, Decimal("0.00"))
        self.assertEqual(self.prod_0.net_profit_per_unit, Decimal("20.00"))

        # 5% GST on 105: Base = 105 / 1.05 = 100.00, GST = 5.00, Profit = 100 - 70 = 30.00
        self.prod_5.refresh_from_db()
        self.assertEqual(self.prod_5.base_price, Decimal("100.00"))
        self.assertEqual(self.prod_5.gst_amount_per_unit, Decimal("5.00"))
        self.assertEqual(self.prod_5.net_profit_per_unit, Decimal("30.00"))

        # 18% GST on 118: Base = 118 / 1.18 = 100.00, GST = 18.00, Profit = 100 - 60 = 40.00
        self.prod_18.refresh_from_db()
        self.assertEqual(self.prod_18.base_price, Decimal("100.00"))
        self.assertEqual(self.prod_18.gst_amount_per_unit, Decimal("18.00"))
        self.assertEqual(self.prod_18.net_profit_per_unit, Decimal("40.00"))

        # 40% GST on 140: Base = 140 / 1.40 = 100.00, GST = 40.00, Profit = 100 - 60 = 40.00
        self.prod_40.refresh_from_db()
        self.assertEqual(self.prod_40.base_price, Decimal("100.00"))
        self.assertEqual(self.prod_40.gst_amount_per_unit, Decimal("40.00"))
        self.assertEqual(self.prod_40.net_profit_per_unit, Decimal("40.00"))

    def test_admin_single_product_form_gst_choices_and_saving(self):
        self.client.force_login(self.admin_user)
        res = self.client.get(reverse("admin_products"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "GST Rate (%)")
        self.assertContains(res, '<option value="0">0%</option>')
        self.assertContains(res, '<option value="5">5%</option>')
        self.assertContains(res, '<option value="18" selected>18%</option>')
        self.assertContains(res, '<option value="40">40%</option>')

        post_data = {
            "name": "Super Spark 40%",
            "category": "energy",
            "volume": "330 ml",
            "cost_price": "60.00",
            "gst_rate": "40",
            "base_price": "100.00",
            "price": "140.00",
            "available": True,
            "featured": False,
            "display_order": 1,
        }
        create_res = self.client.post(reverse("admin_products"), post_data)
        self.assertEqual(create_res.status_code, 302)
        created_prod = Product.objects.filter(name="Super Spark 40%").first()
        self.assertIsNotNone(created_prod)
        self.assertEqual(created_prod.gst_rate, 40)
        self.assertEqual(created_prod.base_price, Decimal("100.00"))
        self.assertEqual(created_prod.price, Decimal("140.00"))
        self.assertEqual(created_prod.net_profit_per_unit, Decimal("40.00"))

    def test_admin_bulk_add_products_with_gst_rates(self):
        self.client.force_login(self.admin_user)
        bulk_data = {
            "row_count": "2",
            "name_0": "Bulk Zero 0",
            "category_0": "soda",
            "volume_0": "330 ml",
            "cost_price_0": "40.00",
            "gst_rate_0": "0",
            "base_price_0": "70.00",
            "price_0": "70.00",
            "name_1": "Bulk Concessional 5",
            "category_1": "juice",
            "volume_1": "330 ml",
            "cost_price_1": "50.00",
            "gst_rate_1": "5",
            "base_price_1": "100.00",
            "price_1": "105.00",
        }
        res = self.client.post(reverse("admin_bulk_add_products"), bulk_data)
        self.assertEqual(res.status_code, 302)
        p0 = Product.objects.filter(name="Bulk Zero 0").first()
        self.assertIsNotNone(p0)
        self.assertEqual(p0.gst_rate, 0)
        self.assertEqual(p0.price, Decimal("70.00"))
        self.assertEqual(p0.base_price, Decimal("70.00"))

        p1 = Product.objects.filter(name="Bulk Concessional 5").first()
        self.assertIsNotNone(p1)
        self.assertEqual(p1.gst_rate, 5)
        self.assertEqual(p1.price, Decimal("105.00"))
        self.assertEqual(p1.base_price, Decimal("100.00"))

    def test_storefront_inclusive_taxes_notes(self):
        home_res = self.client.get(reverse("home"))
        self.assertEqual(home_res.status_code, 200)
        self.assertContains(home_res, "Inclusive of all taxes")

        detail_res = self.client.get(reverse("product_detail", kwargs={"product_id": self.prod_18.id}))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, "(Inclusive of all taxes)")

    def test_checkout_does_not_charge_extra_gst(self):
        self.client.force_login(self.customer)
        post_data = {
            "first_name": "GST",
            "last_name": "Buyer",
            "email": "gstbuyer@example.com",
            "phone": "+91 9123456789",
            "address": "40 Luxury Road",
            "city": "Chennai",
            "state": "Tamil Nadu",
            "postal_code": "600001",
        }
        res = self.client.post(f"/checkout/{self.prod_40.id}/?qty=1", post_data)
        self.assertEqual(res.status_code, 302)
        order = Order.objects.filter(customer_phone="+91 9123456789").first()
        self.assertIsNotNone(order)
        self.assertEqual(order.items_subtotal, Decimal("140.00"))
        self.assertEqual(order.shipping_fee, Decimal("50.00"))
        self.assertEqual(order.total_amount, Decimal("190.00"))
        self.assertEqual(order.gst_amount, Decimal("40.00"))

    def test_reports_show_gst_collected_and_accurate_net_profit(self):
        order = Order.objects.create(
            customer=self.customer,
            customer_name="GST Test Shopper",
            customer_phone="9876500001",
            delivery_address="100 Tax Street",
            delivery_city="Chennai",
            product=self.prod_18,
            quantity=2,
            total_amount=Decimal("236.00"),
            gst_amount=Decimal("36.00"),
            status="delivered",
            payment_status="paid",
        )
        OrderItem.objects.create(
            order=order,
            product=self.prod_18,
            quantity=2,
            unit_price=Decimal("118.00"),
        )

        self.client.force_login(self.admin_user)
        res = self.client.get(reverse("admin_reports"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "GST Collected")
        self.assertContains(res, "Net Sales")
        self.assertContains(res, "Government Tax Liability")
        self.assertContains(res, "profit-equation-banner")

        csv_res = self.client.get(reverse("admin_reports_export_csv"))
        self.assertEqual(csv_res.status_code, 200)
        csv_content = csv_res.content.decode("utf-8")
        self.assertIn("GST Collected", csv_content)
        self.assertIn("Net Sales", csv_content)














