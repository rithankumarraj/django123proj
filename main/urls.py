from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin-login/", views.admin_login, name="admin_login"),
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