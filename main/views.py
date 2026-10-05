from decimal import Decimal
import json
import uuid

from django.contrib.auth import login
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.conf import settings
from django.db import transaction
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .forms import AdminLoginForm, ProductForm
from .models import Order, OrderItem, Product
from .payments import process_payment_webhook, sign_webhook_payload

MAX_CART_QUANTITY = 1_000_000
CART_SESSION_KEY = "cart"


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


def home(request):
    products = [
        {
            **product,
            "price": str(product["price"]),
            "image": static(product["image"]),
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
        {"products": products, "cart_count": _cart_quantity(request)},
    )


def product_detail(request, product_id):
    product = get_object_or_404(Product, id=product_id, available=True)
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
        },
    )


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
    return redirect("cart")


def cart_page(request):
    items = _cart_items(request)
    total = sum((item["line_total"] for item in items), Decimal("0.00"))
    return render(
        request,
        "main/cart.html",
        {
            "items": items,
            "cart_total": total,
            "cart_count": sum(item["quantity"] for item in items),
        },
    )


@require_POST
def cart_checkout(request):
    items = _cart_items(request)
    if not items:
        return redirect("cart")

    first_name = request.POST.get("first_name", "").strip()
    last_name = request.POST.get("last_name", "").strip()
    if not first_name or not last_name:
        return HttpResponseBadRequest("First and last name are required.")

    total_amount = sum((item["line_total"] for item in items), Decimal("0.00"))
    total_quantity = sum(item["quantity"] for item in items)
    with transaction.atomic():
        order = Order.objects.create(
            product=items[0]["product"],
            customer_name=f"{first_name} {last_name}",
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
    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        if not first_name or not last_name:
            return HttpResponseBadRequest("First and last name are required.")
        order = Order.objects.create(
            product=product,
            customer_name=f"{first_name} {last_name}",
            quantity=quantity,
            total_amount=total_price,
        )
        OrderItem.objects.create(
            order=order,
            product=product,
            quantity=quantity,
            unit_price=unit_price,
        )
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
        },
    )


def payment_page(request, payment_reference):
    order = get_object_or_404(
        Order.objects.select_related("product").prefetch_related(
            "items__product"
        ),
        payment_reference=payment_reference,
    )
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
    }
    return render(request, "main/admin_dashboard.html", context)
