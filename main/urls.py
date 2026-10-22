from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("privacy-policy/", views.privacy_policy, name="privacy_policy"),
    path("admin-login/", views.admin_login, name="admin_login"),
    path("delivery-login/", views.delivery_login, name="delivery_login"),
    path("delivery-profile/", views.delivery_dashboard, name="delivery_dashboard"),
    path(
        "delivery-profile/orders/<int:order_id>/status/",
        views.update_delivery_status,
        name="update_delivery_status",
    ),
    path(
        "admin-profile/delivery-account/",
        views.create_delivery_account,
        name="create_delivery_account",
    ),
    path("customer-login/", views.customer_login, name="customer_login"),
    path("customer-register/", views.customer_register, name="customer_register"),
    path("my-orders/", views.customer_orders, name="customer_orders"),
    path("customer-logout/", views.customer_logout, name="customer_logout"),
    path("product/<int:product_id>/", views.product_detail, name="product_detail"),
    path("cart/", views.cart_page, name="cart"),
    path("cart/add/<int:product_id>/", views.add_to_cart, name="add_to_cart"),
    path("cart/update/", views.update_cart, name="update_cart"),
    path("cart/checkout/", views.cart_checkout, name="cart_checkout"),
    path("checkout/<int:product_id>/", views.checkout, name="checkout"),
    path("payment/<uuid:payment_reference>/", views.payment_page, name="payment_page"),
    path("webhooks/payment/", views.payment_webhook, name="payment_webhook"),
    path("admin-profile/", views.admin_dashboard, name="admin_dashboard"),
]