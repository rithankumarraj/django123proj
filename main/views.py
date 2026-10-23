from decimal import Decimal
import json
import uuid

from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm as DjangoSetPasswordForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import redirect_to_login
from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils.crypto import get_random_string
from django.utils.text import slugify
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import (
    AdminLoginForm,
    CustomerAccountForm,
    CustomerProfileForm,
    CustomerRegistrationForm,
    DeliveryAccountForm,
    DeliveryAddressForm,
    EmailAuthenticationForm,
    PasswordChangeForm,
    ProductForm,
)
from .models import CustomerProfile, DeliveryProfile, Order, OrderItem, Product
from .payments import process_payment_webhook, sign_webhook_payload

MAX_CART_QUANTITY = 1_000_000
CART_SESSION_KEY = "cart"
WISHLIST_SESSION_KEY = "wishlist"
GUEST_PASSWORD_SETUP_SESSION_KEY = "guest_account_password_setup"


def _create_guest_account(first_name, last_name):
    user_model = get_user_model()
    username_field = user_model.USERNAME_FIELD
    username_max_length = user_model._meta.get_field(username_field).max_length or 150
    username_base = slugify(first_name)[:username_max_length].strip("-") or "customer"

    suffix = 0
    while True:
        suffix_text = str(suffix) if suffix else ""
        username = f"{username_base[:username_max_length - len(suffix_text)]}{suffix_text}"
        if not user_model._default_manager.filter(
            **{f"{username_field}__iexact": username}
        ).exists():
            return user_model._default_manager.create_user(
                **{
                    username_field: username,
                    "first_name": first_name,
                    "last_name": last_name,
                    "password": get_random_string(64),
                }
            )
        suffix += 1


def _checkout_customer(request, details):
    if request.user.is_authenticated:
        return request.user

    customer = _create_guest_account(details["first_name"], details["last_name"])
    CustomerProfile.objects.update_or_create(
        user=customer,
        defaults={
            "phone": details["phone"],
            "address": details["address"],
            "city": details["city"],
            "state": details["state"],
            "postal_code": details["postal_code"],
        },
    )

    return customer


def _sign_in_guest_customer(request, customer):
    login(request, customer, backend="django.contrib.auth.backends.ModelBackend")
    request.session[GUEST_PASSWORD_SETUP_SESSION_KEY] = True
    messages.success(
        request,
        "We created your account and signed you in. Set a password in your profile before signing out.",
    )


def _customer_redirect_target(request):
    next_url = request.POST.get("next") or request.GET.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return reverse("customer_orders")


def _cart_items(request):
    cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        cart = {}

    product_ids = []
    quantities = {}
    for raw_id, raw_quantity in cart.items():
        try:
            product_id = int(raw_id)
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and 1 <= quantity <= MAX_CART_QUANTITY:
            product_ids.append(product_id)
            quantities[product_id] = quantity

    products = Product.objects.filter(id__in=product_ids, available=True).order_by("name")
    items = []
    for product in products:
        quantity = quantities[product.id]
        items.append(
            {
                "product": product,
                "quantity": quantity,
                "line_total": product.price * quantity,
            }
        )

    valid_cart = {str(item["product"].id): item["quantity"] for item in items}
    if valid_cart != cart:
        request.session[CART_SESSION_KEY] = valid_cart
        request.session.modified = True
    return items


def _cart_quantity(request):
    return sum(item["quantity"] for item in _cart_items(request))


def _wishlist_products(request):
    wishlist = request.session.get(WISHLIST_SESSION_KEY, [])
    if not isinstance(wishlist, list):
        wishlist = []

    product_ids = []
    for raw_id in wishlist:
        try:
            product_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if product_id > 0 and product_id not in product_ids:
            product_ids.append(product_id)

    products_by_id = Product.objects.filter(id__in=product_ids, available=True).in_bulk()
    products = [
        products_by_id[product_id]
        for product_id in product_ids
        if product_id in products_by_id
    ]
    valid_ids = [str(product.pk) for product in products]
    if valid_ids != wishlist:
        request.session[WISHLIST_SESSION_KEY] = valid_ids
        request.session.modified = True
    return products


def _is_delivery_user(user):
    return user.is_authenticated and DeliveryProfile.objects.filter(user=user).exists()


def home(request):
    wishlist_products = _wishlist_products(request)
    wishlisted_ids = {product.pk for product in wishlist_products}
    products = [
        {
            **product,
            "price": str(product["price"]),
            "image": static(product["image"]),
            "is_wishlisted": product["id"] in wishlisted_ids,
            "wishlist_url": reverse("wishlist_toggle", kwargs={"product_id": product["id"]}),
        }
        for product in Product.objects.filter(available=True).values(
            "id",
            "name",
            "description",
            "price",
            "volume",
            "image",
        )
    ]

    return render(
        request,
        "main/home.html",
        {
            "products": products,
            "cart_count": _cart_quantity(request),
            "wishlist_count": len(wishlist_products),
            "is_delivery_user": _is_delivery_user(request.user),
        },
    )


def about(request):
    return render(request, "main/about.html")


def privacy_policy(request):
    return render(request, "main/privacy_policy.html")


def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id, available=True)
    wishlist_products = _wishlist_products(request)
    wishlisted_ids = {item.pk for item in wishlist_products}
    return render(
        request,
        "main/product_detail.html",
        {
            "product": {
                "id": product.id,
                "name": product.name,
                "description": product.description,
                "price": str(product.price),
                "volume": product.volume,
                "image": static(product.image),
            },
            "cart_count": _cart_quantity(request),
            "wishlist_count": len(wishlist_products),
            "is_wishlisted": product.pk in wishlisted_ids,
            "is_delivery_user": _is_delivery_user(request.user),
        },
    )


def wishlist_page(request):
    products = _wishlist_products(request)
    return render(
        request,
        "main/wishlist.html",
        {
            "products": products,
            "wishlist_count": len(products),
            "cart_count": _cart_quantity(request),
        },
    )


@require_POST
def toggle_wishlist(request, product_id):
    product = get_object_or_404(Product, id=product_id, available=True)
    products = _wishlist_products(request)
    product_ids = [item.pk for item in products]
    action = request.POST.get("action", "toggle")

    if action == "remove" or (action == "toggle" and product.pk in product_ids):
        if product.pk in product_ids:
            product_ids.remove(product.pk)
            messages.success(request, f"{product.name} removed from your wishlist.")
    elif action in {"add", "toggle"}:
        if product.pk not in product_ids:
            product_ids.append(product.pk)
            messages.success(request, f"{product.name} added to your wishlist.")
    else:
        return HttpResponseBadRequest("Invalid wishlist action.")

    request.session[WISHLIST_SESSION_KEY] = [str(product_id) for product_id in product_ids]
    request.session.modified = True
    next_url = request.POST.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect("wishlist")


@require_POST
def add_to_cart(request, product_id):
    product = get_object_or_404(Product, id=product_id, available=True)
    try:
        quantity = int(request.POST.get("quantity", "1"))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Quantity must be a positive whole number.")
    if not 1 <= quantity <= MAX_CART_QUANTITY:
        return HttpResponseBadRequest("Quantity must be between 1 and 1,000,000.")

    cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        cart = {}
    try:
        current_quantity = int(cart.get(str(product.id), 0))
    except (TypeError, ValueError):
        current_quantity = 0
    new_quantity = current_quantity + quantity
    if new_quantity > MAX_CART_QUANTITY:
        return HttpResponseBadRequest("Cart quantity exceeds the allowed maximum.")

    cart[str(product.id)] = new_quantity
    request.session[CART_SESSION_KEY] = cart
    if request.headers.get("Accept") == "application/json":
        return JsonResponse({"cart_count": _cart_quantity(request)})

    messages.success(request, f"{product.name} added to your cart.")
    return redirect("cart")


@require_POST
def update_cart(request):
    action = request.POST.get("action")
    cart = request.session.get(CART_SESSION_KEY, {})
    if not isinstance(cart, dict):
        cart = {}

    if action == "remove":
        product_id = request.POST.get("product_id", "")
        cart.pop(str(product_id), None)
    elif action == "update":
        for raw_id in list(cart):
            try:
                quantity = int(request.POST.get(f"quantity_{raw_id}", ""))
                product_id = int(raw_id)
            except (TypeError, ValueError):
                return HttpResponseBadRequest("Quantity must be a positive whole number.")
            if quantity < 1 or quantity > MAX_CART_QUANTITY:
                return HttpResponseBadRequest("Quantity must be between 1 and 1,000,000.")
            if not Product.objects.filter(id=product_id, available=True).exists():
                cart.pop(raw_id, None)
            else:
                cart[raw_id] = quantity
    else:
        return HttpResponseBadRequest("Invalid cart action.")

    request.session[CART_SESSION_KEY] = cart
    request.session.modified = True
    if action == "update" and request.headers.get("Accept") == "application/json":
        items = _cart_items(request)
        return JsonResponse(
            {
                "cart_count": sum(item["quantity"] for item in items),
                "cart_total": str(
                    sum((item["line_total"] for item in items), Decimal("0.00"))
                ),
                "items": [
                    {
                        "product_id": item["product"].id,
                        "quantity": item["quantity"],
                        "line_total": str(item["line_total"]),
                    }
                    for item in items
                ],
            }
        )
    return redirect("cart")


def cart_page(request):
    items = _cart_items(request)
    total = sum((item["line_total"] for item in items), Decimal("0.00"))
    customer_profile = (
        CustomerProfile.objects.filter(user=request.user).first()
        if request.user.is_authenticated
        else None
    )
    return render(
        request,
        "main/cart.html",
        {
            "items": items,
            "cart_total": total,
            "cart_count": sum(item["quantity"] for item in items),
            "customer_profile": customer_profile,
        },
    )


@login_required(login_url="customer_login")
def customer_orders(request):
    search_query = request.GET.get("q", "").strip()[:100]
    sort_order = request.GET.get("sort", "newest")
    sort_options = {
        "newest": ("-created_at", "-pk"),
        "oldest": ("created_at", "pk"),
        "total_high": ("-total_amount", "-created_at", "-pk"),
        "total_low": ("total_amount", "-created_at", "-pk"),
    }
    if sort_order not in sort_options:
        sort_order = "newest"

    orders = Order.objects.filter(customer=request.user)
    if search_query:
        order_number = search_query.removeprefix("#")
        if order_number.isdecimal():
            search_filter = Q(pk=int(order_number))
        else:
            search_filter = (
                Q(customer_name__icontains=search_query)
                | Q(delivery_address__icontains=search_query)
                | Q(delivery_city__icontains=search_query)
                | Q(delivery_state__icontains=search_query)
                | Q(delivery_postal_code__icontains=search_query)
                | Q(product__name__icontains=search_query)
                | Q(items__product__name__icontains=search_query)
            )
        orders = orders.filter(search_filter).distinct()

    orders = (
        orders.select_related("product")
        .prefetch_related("items__product")
        .order_by(*sort_options[sort_order])
    )
    return render(
        request,
        "main/customer_orders.html",
        {
            "orders": orders,
            "search_query": search_query,
            "sort_order": sort_order,
        },
    )


@login_required(login_url="customer_login")
def customer_profile(request):
    profile, _created = CustomerProfile.objects.get_or_create(user=request.user)
    account_form = CustomerAccountForm(instance=request.user)
    profile_form = CustomerProfileForm(instance=profile)
    password_form = PasswordChangeForm(request.user)
    password_setup_required = request.session.get(GUEST_PASSWORD_SETUP_SESSION_KEY, False)
    password_setup_form = (
        DjangoSetPasswordForm(request.user) if password_setup_required else None
    )

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_profile":
            account_form = CustomerAccountForm(request.POST, instance=request.user)
            profile_form = CustomerProfileForm(request.POST, instance=profile)
            if account_form.is_valid() and profile_form.is_valid():
                with transaction.atomic():
                    account_form.save()
                    profile_form.save()
                messages.success(request, "Your profile has been updated.")
                return redirect("customer_profile")
        elif action == "change_password":
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                user = password_form.save()
                update_session_auth_hash(request, user)
                messages.success(request, "Your password has been changed.")
                return redirect("customer_profile")
        elif action == "set_password" and password_setup_required:
            password_setup_form = DjangoSetPasswordForm(request.user, request.POST)
            if password_setup_form.is_valid():
                user = password_setup_form.save()
                update_session_auth_hash(request, user)
                request.session.pop(GUEST_PASSWORD_SETUP_SESSION_KEY, None)
                messages.success(request, "Your password has been set.")
                return redirect("customer_profile")
        elif action == "set_password":
            return HttpResponseBadRequest(
                "A password cannot be set for this account this way."
            )
        else:
            return HttpResponseBadRequest("Choose a valid profile action.")

    return render(
        request,
        "main/customer_profile.html",
        {
            "account_form": account_form,
            "profile_form": profile_form,
            "password_form": password_form,
            "password_setup_required": password_setup_required,
            "password_setup_form": password_setup_form,
            "is_delivery_user": _is_delivery_user(request.user),
        },
    )


@require_POST
def cart_checkout(request):
    items = _cart_items(request)
    if not items:
        return redirect("cart")

    address_form = DeliveryAddressForm(request.POST)
    if not address_form.is_valid():
        return HttpResponseBadRequest("Complete all required delivery details.")
    details = address_form.cleaned_data

    total_amount = sum((item["line_total"] for item in items), Decimal("0.00"))
    total_quantity = sum(item["quantity"] for item in items)
    guest_checkout = not request.user.is_authenticated
    with transaction.atomic():
        customer = _checkout_customer(request, details)
        order = Order.objects.create(
            product=items[0]["product"],
            customer=customer,
            customer_name=f"{details['first_name']} {details['last_name']}",
            customer_phone=details["phone"],
            delivery_address=details["address"],
            delivery_city=details["city"],
            delivery_state=details["state"],
            delivery_postal_code=details["postal_code"],
            quantity=total_quantity,
            total_amount=total_amount,
        )
        OrderItem.objects.bulk_create(
            [
                OrderItem(
                    order=order,
                    product=item["product"],
                    quantity=item["quantity"],
                    unit_price=item["product"].price,
                )
                for item in items
            ]
        )
    if guest_checkout:
        _sign_in_guest_customer(request, customer)
    request.session[CART_SESSION_KEY] = {}
    request.session.modified = True
    return redirect("payment_page", payment_reference=order.payment_reference)


def checkout(request, product_id):
    product = get_object_or_404(Product, id=product_id, available=True)
    raw_quantity = request.GET.get("qty", "1")
    try:
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Quantity must be a positive whole number.")
    if quantity < 1:
        return HttpResponseBadRequest("Quantity must be a positive whole number.")

    unit_price = Decimal(str(product.price))
    total_price = unit_price * quantity
    order = None
    customer_profile = (
        CustomerProfile.objects.filter(user=request.user).first()
        if request.user.is_authenticated
        else None
    )
    if request.method == "POST":
        address_form = DeliveryAddressForm(request.POST)
        if not address_form.is_valid():
            return HttpResponseBadRequest("Complete all required delivery details.")
        details = address_form.cleaned_data
        guest_checkout = not request.user.is_authenticated
        with transaction.atomic():
            customer = _checkout_customer(request, details)
            order = Order.objects.create(
                product=product,
                customer=customer,
                customer_name=f"{details['first_name']} {details['last_name']}",
                customer_phone=details["phone"],
                delivery_address=details["address"],
                delivery_city=details["city"],
                delivery_state=details["state"],
                delivery_postal_code=details["postal_code"],
                quantity=quantity,
                total_amount=total_price,
            )
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantity,
                unit_price=unit_price,
            )
        if guest_checkout:
            _sign_in_guest_customer(request, customer)
        return redirect("payment_page", payment_reference=order.payment_reference)

    return render(
        request,
        "main/checkout.html",
        {
            "product": {
                "id": product.id,
                "name": product.name,
                "volume": product.volume,
                "description": product.description,
                "price": str(product.price),
                "image": static(product.image),
            },
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": total_price,
            "payment_simulation_enabled": settings.PAYMENT_SIMULATION_ENABLED,
            "customer_first_name": request.user.first_name if request.user.is_authenticated else "",
            "customer_last_name": request.user.last_name if request.user.is_authenticated else "",
            "customer_address_form": {
                "phone": request.POST.get(
                    "phone", customer_profile.phone if customer_profile else ""
                ),
                "address": request.POST.get(
                    "address", customer_profile.address if customer_profile else ""
                ),
                "city": request.POST.get(
                    "city", customer_profile.city if customer_profile else ""
                ),
                "state": request.POST.get(
                    "state", customer_profile.state if customer_profile else ""
                ),
                "postal_code": request.POST.get(
                    "postal_code", customer_profile.postal_code if customer_profile else ""
                ),
            },
        },
    )


def payment_page(request, payment_reference):
    order = get_object_or_404(
        Order.objects.select_related("product").prefetch_related(
            "items__product"
        ),
        payment_reference=payment_reference,
    )
    if order.customer_id:
        if not request.user.is_authenticated:
            return redirect_to_login(
                request.get_full_path(), login_url=reverse("customer_login")
            )
        if order.customer_id != request.user.pk:
            raise Http404
    order_items = list(order.items.all())
    if not order_items and order.product_id:
        order_items = [
            {
                "product": order.product,
                "quantity": order.quantity,
                "unit_price": order.total_amount / order.quantity,
                "line_total": order.total_amount,
            }
        ]
    error = None

    if request.method == "POST":
        if not settings.PAYMENT_SIMULATION_ENABLED:
            error = "Demo payment confirmation is disabled on this server."
        elif order.payment_status != "pending":
            error = "This order already has a final payment status."
        else:
            action = request.POST.get("action")
            event_types = {
                "confirm": "payment.succeeded",
                "cancel": "payment.failed",
            }
            event_type = event_types.get(action)
            if event_type is None:
                return HttpResponseBadRequest("Invalid payment action.")

            event = {
                "event_id": str(uuid.uuid4()),
                "type": event_type,
                "order_id": order.pk,
                "payment_reference": str(order.payment_reference),
                "amount": str(order.total_amount),
                "currency": "INR",
            }
            raw_event = json.dumps(event, separators=(",", ":")).encode()
            status_code, result = process_payment_webhook(
                raw_event, sign_webhook_payload(raw_event)
            )
            if status_code != 200:
                return HttpResponseBadRequest(result["error"])
            return redirect(
                "payment_page", payment_reference=order.payment_reference
            )

    return render(
        request,
        "main/payment.html",
        {
            "order": order,
            "order_items": order_items,
            "simulation_enabled": settings.PAYMENT_SIMULATION_ENABLED,
            "password_setup_required": request.session.get(
                GUEST_PASSWORD_SETUP_SESSION_KEY, False
            ),
            "error": error,
        },
    )


@csrf_exempt
@require_POST
def payment_webhook(request):
    if request.content_type != "application/json":
        return JsonResponse({"error": "Content-Type must be application/json."}, status=415)

    status_code, result = process_payment_webhook(
        request.body, request.headers.get("X-Payment-Signature", "")
    )
    return JsonResponse(result, status=status_code)


def admin_login(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect("admin_dashboard")

    form = AdminLoginForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if user.is_staff:
            login(request, user)
            return redirect("admin_dashboard")
        form.add_error(None, "Admin access is restricted to staff accounts.")

    return render(
        request,
        "main/admin_login.html",
        {"form": form, "google_login_enabled": settings.GOOGLE_SIGN_IN_ENABLED},
    )


def delivery_login(request):
    if request.user.is_authenticated and DeliveryProfile.objects.filter(user=request.user).exists():
        return redirect("delivery_dashboard")

    form = EmailAuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        if DeliveryProfile.objects.filter(user=user).exists():
            login(request, user)
            return redirect("delivery_dashboard")
        form.add_error(None, "This account does not have delivery access.")

    return render(request, "main/delivery_login.html", {"form": form})


@login_required(login_url="delivery_login")
def delivery_dashboard(request):
    if not DeliveryProfile.objects.filter(user=request.user).exists():
        return HttpResponseForbidden("Delivery access is required.")

    orders = (
        Order.objects.select_related("product")
        .prefetch_related("items__product")
        .order_by("status", "-created_at")
    )
    products = Product.objects.order_by("name")
    return render(
        request,
        "main/delivery_dashboard.html",
        {
            "orders": orders,
            "products": products,
            "available_stock_count": products.filter(available=True).count(),
            "unavailable_stock_count": products.filter(available=False).count(),
        },
    )


@login_required(login_url="delivery_login")
@require_POST
def update_delivery_status(request, order_id):
    if not DeliveryProfile.objects.filter(user=request.user).exists():
        return HttpResponseForbidden("Delivery access is required.")

    order = get_object_or_404(Order, pk=order_id)
    status = request.POST.get("status")
    valid_statuses = {choice for choice, _label in Order.STATUS_CHOICES}
    if status not in valid_statuses:
        return HttpResponseBadRequest("Choose a valid delivery status.")

    order.status = status
    order.delivered_at = timezone.now() if status == "delivered" else None
    order.save(update_fields=["status", "delivered_at"])
    messages.success(request, f"Order #{order.pk} delivery status updated.")
    return redirect("delivery_dashboard")


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def create_delivery_account(request):
    form = DeliveryAccountForm(request.POST)
    if form.is_valid():
        with transaction.atomic():
            user = form.save()
            DeliveryProfile.objects.create(user=user)
        messages.success(request, f"Delivery account created for {user.get_username()}.")
    else:
        for error in form.errors.values():
            for message in error:
                messages.error(request, message)
    return redirect("admin_dashboard")


def customer_login(request):
    if request.user.is_authenticated:
        return redirect(_customer_redirect_target(request))

    form = EmailAuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.get_user())
        return redirect(_customer_redirect_target(request))

    return render(
        request,
        "main/customer_login.html",
        {"form": form, "next": request.POST.get("next") or request.GET.get("next", "")},
    )


def customer_register(request):
    if request.user.is_authenticated:
        return redirect(_customer_redirect_target(request))

    form = CustomerRegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect(_customer_redirect_target(request))

    return render(
        request,
        "main/customer_register.html",
        {"form": form, "next": request.POST.get("next") or request.GET.get("next", "")},
    )


@require_POST
def customer_logout(request):
    logout(request)
    return redirect("home")


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_dashboard(request):
    edit_id = request.GET.get("edit")
    product_to_edit = get_object_or_404(Product, id=edit_id) if edit_id else None

    if request.method == "POST":
        product_form = ProductForm(request.POST, instance=product_to_edit)
        if product_form.is_valid():
            product = product_form.save()
            if product_to_edit:
                messages.success(request, f"{product.name} updated successfully.")
            else:
                messages.success(request, f"{product.name} added successfully.")
            return redirect("admin_dashboard")
    else:
        product_form = ProductForm(instance=product_to_edit)

    products = Product.objects.order_by("name")
    orders = (
        Order.objects.select_related("product")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )

    context = {
        "products": products,
        "orders": orders,
        "product_form": product_form,
        "editing_product": product_to_edit,
        "total_products": products.count(),
        "delivered_count": orders.filter(status="delivered").count(),
        "pending_count": orders.filter(status="pending").count(),
        "delivery_account_form": DeliveryAccountForm(),
    }
    return render(request, "main/admin_dashboard.html", context)
