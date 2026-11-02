from decimal import Decimal
import json
import re
import uuid

from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.forms import SetPasswordForm as DjangoSetPasswordForm
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.views import redirect_to_login
from django.conf import settings
from django.db import models, transaction
from django.db.models import Case, Q, When
from django.http import Http404, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
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
    AboutDetailsForm,
    AdminLoginForm,
    ContactDetailsForm,
    CustomerAccountForm,
    CustomerAddressForm,
    CustomerProfileForm,
    CustomerRegistrationForm,
    DeliveryAccountForm,
    DeliveryAddressForm,
    DeliveryPartnerApplicationForm,
    EmailAuthenticationForm,
    PackingChargesForm,
    PasswordChangeForm,
    ProductForm,
    ShippingChargesForm,
    ShippingSettingsForm,
)
from .models import (
    ContactMessage,
    CustomerAddress,
    CustomerProfile,
    DeliveryProfile,
    INDIAN_STATES,
    Order,
    OrderItem,
    Product,
    ProductCategory,
    SiteDetails,
)
from .payments import process_payment_webhook, sign_webhook_payload
from .captcha import generate_captcha_image, generate_captcha_text

MAX_CART_QUANTITY = 1_000_000
CART_SESSION_KEY = "cart"
WISHLIST_SESSION_KEY = "wishlist"
GUEST_PASSWORD_SETUP_SESSION_KEY = "guest_account_password_setup"


def _create_guest_account(first_name, last_name, email, phone):
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
                    "email": email,
                    "password": phone,
                }
            )
        suffix += 1


MAX_SAVED_ADDRESSES = 5


def get_user_saved_addresses(user):
    if not user or not user.is_authenticated:
        return []
    addresses = list(
        CustomerAddress.objects.filter(user=user).order_by("-is_default", "-updated_at", "-created_at")[
            :MAX_SAVED_ADDRESSES
        ]
    )
    if not addresses:
        profile = CustomerProfile.objects.filter(user=user).first()
        if profile and profile.address:
            addr = CustomerAddress.objects.create(
                user=user,
                phone=profile.phone or "",
                address=profile.address,
                city=profile.city or "",
                state=profile.state or "",
                postal_code=profile.postal_code or "",
                is_default=True,
            )
            addresses = [addr]
    return addresses


def save_customer_address(user, phone, address, city, state, postal_code, full_name="", set_default=False):
    if not user or not user.is_authenticated:
        return None

    address = (address or "").strip()
    if not address:
        return None

    phone = (phone or "").strip()
    city = (city or "").strip()
    state = (state or "").strip()
    postal_code = (postal_code or "").strip()
    full_name = (full_name or "").strip()

    existing = CustomerAddress.objects.filter(
        user=user,
        address__iexact=address,
        city__iexact=city,
        state__iexact=state,
        postal_code__iexact=postal_code,
    ).first()

    has_any = CustomerAddress.objects.filter(user=user).exists()
    should_be_default = set_default or not has_any

    if should_be_default:
        CustomerAddress.objects.filter(user=user).update(is_default=False)

    if existing:
        if phone:
            existing.phone = phone
        if full_name:
            existing.full_name = full_name
        if should_be_default:
            existing.is_default = True
        existing.save()
        addr_obj = existing
    else:
        count = CustomerAddress.objects.filter(user=user).count()
        if count >= MAX_SAVED_ADDRESSES:
            oldest_non_default = (
                CustomerAddress.objects.filter(user=user, is_default=False)
                .order_by("updated_at", "created_at")
                .first()
            )
            if oldest_non_default:
                oldest_non_default.delete()
            else:
                CustomerAddress.objects.filter(user=user).order_by("updated_at", "created_at").first().delete()

        addr_obj = CustomerAddress.objects.create(
            user=user,
            full_name=full_name,
            phone=phone,
            address=address,
            city=city,
            state=state,
            postal_code=postal_code,
            is_default=should_be_default,
        )

    default_addr = (
        CustomerAddress.objects.filter(user=user, is_default=True).first()
        or CustomerAddress.objects.filter(user=user).first()
    )
    if default_addr:
        CustomerProfile.objects.update_or_create(
            user=user,
            defaults={
                "phone": default_addr.phone,
                "address": default_addr.address,
                "city": default_addr.city,
                "state": default_addr.state,
                "postal_code": default_addr.postal_code,
            },
        )

    return addr_obj


def _user_matches_phone(user, phone_10):
    if not phone_10:
        return False
    profile = CustomerProfile.objects.filter(user=user).first()
    if profile and profile.phone:
        prof_digits = re.sub(r"\D", "", str(profile.phone))
        if prof_digits.endswith(phone_10) or phone_10 in prof_digits:
            return True
    for addr in CustomerAddress.objects.filter(user=user):
        if addr.phone:
            addr_digits = re.sub(r"\D", "", str(addr.phone))
            if addr_digits.endswith(phone_10) or phone_10 in addr_digits:
                return True
    for order in Order.objects.filter(customer=user):
        if order.customer_phone:
            ord_digits = re.sub(r"\D", "", str(order.customer_phone))
            if ord_digits.endswith(phone_10) or phone_10 in ord_digits:
                return True
    return False


def _find_existing_customer(email, phone):
    user_model = get_user_model()
    clean_email = (email or "").strip().lower()
    clean_digits = re.sub(r"\D", "", str(phone or ""))
    phone_10 = clean_digits[-10:] if len(clean_digits) >= 10 else clean_digits

    if not clean_email and not phone_10:
        return None

    # Step 1: Match by email (case-insensitive)
    if clean_email:
        email_matches = list(
            user_model._default_manager.filter(email__iexact=clean_email).order_by("id")
        )
        if email_matches:
            # If phone is provided, prioritize match whose phone also matches
            if phone_10:
                for u in email_matches:
                    if _user_matches_phone(u, phone_10):
                        return u
            # If phone wasn't recorded on the account yet, return this user
            return email_matches[0]

    # Step 2: Match by phone if no user had this email
    if phone_10:
        profiles = (
            CustomerProfile.objects.filter(phone__icontains=phone_10)
            .select_related("user")
            .order_by("user_id")
        )
        for prof in profiles:
            if prof.user:
                if not clean_email or not prof.user.email or prof.user.email.strip().lower() == clean_email:
                    return prof.user

        addrs = (
            CustomerAddress.objects.filter(phone__icontains=phone_10)
            .select_related("user")
            .order_by("user_id")
        )
        for addr in addrs:
            if addr.user:
                if not clean_email or not addr.user.email or addr.user.email.strip().lower() == clean_email:
                    return addr.user

        orders = (
            Order.objects.filter(customer_phone__icontains=phone_10, customer__isnull=False)
            .select_related("customer")
            .order_by("customer_id")
        )
        for ord_obj in orders:
            if ord_obj.customer:
                if not clean_email or not ord_obj.customer.email or ord_obj.customer.email.strip().lower() == clean_email:
                    return ord_obj.customer

    return None


def _checkout_customer(request, details):
    if request.user.is_authenticated:
        customer = request.user
        customer._is_new_customer = False
        if request.POST.get("save_address_to_profile") in {"1", "true", "on"}:
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
            save_customer_address(
                user=customer,
                phone=details["phone"],
                address=details["address"],
                city=details["city"],
                state=details["state"],
                postal_code=details["postal_code"],
                full_name=f"{details.get('first_name', '')} {details.get('last_name', '')}".strip(),
                set_default=False,
            )
        return customer

    # Check for existing customer with same email and phone number
    existing_user = _find_existing_customer(details.get("email"), details.get("phone"))
    if existing_user:
        customer = existing_user
        customer._is_new_customer = False

        updated_fields = []
        if not customer.first_name and details.get("first_name"):
            customer.first_name = details["first_name"]
            updated_fields.append("first_name")
        if not customer.last_name and details.get("last_name"):
            customer.last_name = details["last_name"]
            updated_fields.append("last_name")
        if not customer.email and details.get("email"):
            customer.email = details["email"]
            updated_fields.append("email")
        if updated_fields:
            customer.save(update_fields=updated_fields)

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
        save_customer_address(
            user=customer,
            phone=details["phone"],
            address=details["address"],
            city=details["city"],
            state=details["state"],
            postal_code=details["postal_code"],
            full_name=f"{details.get('first_name', '')} {details.get('last_name', '')}".strip(),
            set_default=False,
        )
        return customer

    # Create new customer account
    customer = _create_guest_account(
        details["first_name"], details["last_name"],
        details["email"], details["phone"],
    )
    customer._is_new_customer = True
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
    save_customer_address(
        user=customer,
        phone=details["phone"],
        address=details["address"],
        city=details["city"],
        state=details["state"],
        postal_code=details["postal_code"],
        full_name=f"{details.get('first_name', '')} {details.get('last_name', '')}".strip(),
        set_default=True,
    )

    return customer


def _sign_in_guest_customer(request, customer, is_new=None):
    if is_new is None:
        is_new = getattr(customer, "_is_new_customer", False)
    login(request, customer, backend="django.contrib.auth.backends.ModelBackend")
    if is_new:
        request.session[GUEST_PASSWORD_SETUP_SESSION_KEY] = True
        messages.success(
            request,
            "We created your account and signed you in. Your phone number is your password. You can change it in your profile.",
        )
    else:
        messages.success(
            request,
            "Welcome back! You're signed in to your account.",
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
    return (
        user.is_authenticated
        and DeliveryProfile.objects.filter(user=user, is_approved=True).exists()
    )


def home(request):
    wishlist_products = _wishlist_products(request)
    wishlisted_ids = {product.pk for product in wishlist_products}
    product_records = Product.objects.filter(available=True)
    products = [
        {
            "id": product.id,
            "name": product.name,
            "description": product.description,
            "price": str(product.price),
            "volume": product.volume,
            "image": product.image_url,
            "category": product.category_slug,
            "category_display": product.category_display,
            "is_wishlisted": product.id in wishlisted_ids,
            "wishlist_url": reverse("wishlist_toggle", kwargs={"product_id": product.id}),
        }
        for product in product_records
    ]

    category_counts = {
        "all": len(products),
        "cola": sum(1 for p in products if p["category"] == "cola"),
        "energy_drink": sum(1 for p in products if p["category"] == "energy_drink"),
        "others": sum(1 for p in products if p["category"] == "others"),
    }
    for p in products:
        c_slug = p["category"]
        if c_slug not in category_counts:
            category_counts[c_slug] = sum(1 for prod in products if prod["category"] == c_slug)

    categories = [
        {"slug": "cola", "name": "Cola", "count": category_counts.get("cola", 0)},
        {"slug": "energy_drink", "name": "Energy Drink", "count": category_counts.get("energy_drink", 0)},
        {"slug": "others", "name": "Others", "count": category_counts.get("others", 0)},
    ]
    extra_cats = ProductCategory.objects.exclude(slug__in=["cola", "energy_drink", "others"]).order_by("name")
    seen_extra = set()
    for ec in extra_cats:
        seen_extra.add(ec.slug)
        categories.append({
            "slug": ec.slug,
            "name": ec.name,
            "count": category_counts.get(ec.slug, 0),
        })
    for p in products:
        slug = p["category"]
        if slug not in ["cola", "energy_drink", "others"] and slug not in seen_extra:
            seen_extra.add(slug)
            categories.append({
                "slug": slug,
                "name": p["category_display"],
                "count": category_counts.get(slug, 0),
            })

    return render(
        request,
        "main/home.html",
        {
            "products": products,
            "categories": categories,
            "category_counts": category_counts,
            "cart_count": _cart_quantity(request),
            "wishlist_count": len(wishlist_products),
            "is_delivery_user": _is_delivery_user(request.user),
        },
    )


def about(request):
    details = SiteDetails.get_solo()
    return render(request, "main/about.html", {"details": details})


def captcha_image(request):
    code = generate_captcha_text(5)
    request.session["contact_captcha"] = code.upper()
    request.session.modified = True
    image_bytes = generate_captcha_image(code)
    response = HttpResponse(image_bytes, content_type="image/png")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["Expires"] = "0"
    return response


def contact(request):
    details = SiteDetails.get_solo()
    submitted = False
    error_message = None
    form_data = {
        "name": "",
        "email": "",
        "subject": "General inquiry",
        "message": "",
    }

    if request.user.is_authenticated:
        form_data["name"] = request.user.get_full_name() or request.user.username
        form_data["email"] = request.user.email or ""

    if request.method == "POST":
        name = request.POST.get("name", "").strip()
        email = request.POST.get("email", "").strip()
        subject = request.POST.get("subject", "").strip() or "General inquiry"
        message = request.POST.get("message", "").strip()
        captcha_input = request.POST.get("captcha", "").strip().upper()

        # Each submission attempt consumes the active captcha from session so it cannot be reused
        expected_captcha = request.session.pop("contact_captcha", "").upper()

        form_data = {
            "name": name,
            "email": email,
            "subject": subject,
            "message": message,
        }

        # Check required fields
        if not name or not email or not message:
            error_message = "Please fill in all required fields (name, email, and message)."
            messages.error(request, error_message)
        # Check CAPTCHA verification
        elif not expected_captcha or not captcha_input or captcha_input != expected_captcha:
            error_message = "Incorrect security verification (CAPTCHA) code. Please enter the new code shown below."
            messages.error(request, error_message)
        else:
            ContactMessage.objects.create(
                name=name,
                email=email,
                subject=subject,
                message=message,
            )
            messages.success(request, "Thanks for reaching out! Our team will get back to you shortly.")
            submitted = True
            form_data = {
                "name": "",
                "email": "",
                "subject": "General inquiry",
                "message": "",
            }

    return render(
        request,
        "main/contact.html",
        {
            "submitted": submitted,
            "details": details,
            "form_data": form_data,
            "error_message": error_message,
        },
    )


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
                "image": product.image_url,
                "category": product.category_slug,
                "category_display": product.category_display,
                "available_pincodes": product.available_pincodes,
                "available_pins_list": product.get_available_pincodes_list(),
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
        site_details = SiteDetails.get_solo()
        cart_count = sum(item["quantity"] for item in items)
        cart_total = sum((item["line_total"] for item in items), Decimal("0.00"))
        gst_amount = site_details.calculate_gst(cart_total)
        packing_fee = site_details.calculate_packing_fee(cart_count)
        return JsonResponse(
            {
                "cart_count": cart_count,
                "cart_total": str(cart_total),
                "gst_amount": str(gst_amount),
                "packing_fee": str(packing_fee),
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
    saved_addresses = (
        get_user_saved_addresses(request.user)
        if request.user.is_authenticated
        else []
    )
    site_details = SiteDetails.get_solo()
    raw_phone = saved_addresses[0].phone if saved_addresses else (customer_profile.phone if customer_profile else "")
    digits_phone = re.sub(r"\D", "", raw_phone)
    if len(digits_phone) == 12 and digits_phone.startswith("91"):
        clean_10_phone = digits_phone[2:]
    elif len(digits_phone) == 11 and digits_phone.startswith("0"):
        clean_10_phone = digits_phone[1:]
    else:
        clean_10_phone = digits_phone[-10:] if len(digits_phone) >= 10 else digits_phone

    initial_state = saved_addresses[0].state if saved_addresses else (customer_profile.state if customer_profile else "")
    initial_shipping_fee = site_details.calculate_shipping_fee(initial_state)
    cart_count = sum(item["quantity"] for item in items)
    initial_packing_fee = site_details.calculate_packing_fee(cart_count)
    initial_gst_amount = site_details.calculate_gst(total)
    total_with_shipping = total + initial_gst_amount + initial_packing_fee + initial_shipping_fee

    cart_pin_rules = [
        {
            "name": it["product"].name,
            "pins": it["product"].get_available_pincodes_list(),
        }
        for it in items
        if it["product"].get_available_pincodes_list()
    ]

    return render(
        request,
        "main/cart.html",
        {
            "items": items,
            "cart_pin_rules": cart_pin_rules,
            "cart_total": total,
            "cart_count": cart_count,
            "customer_profile": customer_profile,
            "saved_addresses": saved_addresses,
            "indian_states": INDIAN_STATES,
            "shipping_fee_local": site_details.shipping_fee_local,
            "shipping_fee_other": site_details.shipping_fee_other,
            "shipping_local_states": site_details.shipping_local_states,
            "shipping_fee": initial_shipping_fee,
            "gst_rate": site_details.gst_rate,
            "gst_amount": initial_gst_amount,
            "packing_fee": initial_packing_fee,
            "packing_free_cans": site_details.packing_free_cans,
            "packing_cost_per_batch": site_details.packing_cost_per_batch,
            "packing_batch_size": site_details.packing_batch_size,
            "total_with_shipping": total_with_shipping,
            "customer_phone_10_digits": clean_10_phone,
            "customer_address_form": {
                "phone": raw_phone,
                "state": initial_state,
            },
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


def order_receipt(request, order_id=None, payment_reference=None):
    if order_id is not None:
        order = get_object_or_404(
            Order.objects.select_related("product", "customer").prefetch_related("items__product"),
            pk=order_id,
        )
    elif payment_reference is not None:
        order = get_object_or_404(
            Order.objects.select_related("product", "customer").prefetch_related("items__product"),
            payment_reference=payment_reference,
        )
    else:
        raise Http404("Order not found.")

    is_staff = request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser)
    is_owner = request.user.is_authenticated and order.customer_id == request.user.id
    ref_param = request.GET.get("ref", "").strip()
    session_ref = str(request.session.get("last_order_reference", ""))
    is_ref_valid = (
        (ref_param and ref_param.lower() == str(order.payment_reference).lower())
        or (session_ref and session_ref.lower() == str(order.payment_reference).lower())
        or (payment_reference is not None and str(payment_reference).lower() == str(order.payment_reference).lower())
    )

    if not (is_staff or is_owner or is_ref_valid):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('customer_login')}?next={request.get_full_path()}")
        return HttpResponseForbidden("You do not have permission to view this receipt.")

    order_items = list(order.items.all())
    if not order_items and order.product:
        order_items = [
            {
                "product": order.product,
                "quantity": order.quantity,
                "unit_price": order.product.price,
                "line_total": order.items_subtotal,
            }
        ]

    auto_print = request.GET.get("print") in ["1", "true", "yes"]
    site_details = SiteDetails.objects.first()

    context = {
        "order": order,
        "order_items": order_items,
        "auto_print": auto_print,
        "site_details": site_details,
        "is_staff_view": is_staff,
    }
    return render(request, "main/order_receipt.html", context)


@login_required(login_url="customer_login")
def customer_profile(request):
    profile, _created = CustomerProfile.objects.get_or_create(user=request.user)
    account_form = CustomerAccountForm(instance=request.user)
    profile_form = CustomerProfileForm(instance=profile)
    new_address_form = CustomerAddressForm()
    password_form = PasswordChangeForm(request.user)
    password_setup_required = request.session.get(GUEST_PASSWORD_SETUP_SESSION_KEY, False)
    password_setup_form = (
        DjangoSetPasswordForm(request.user) if password_setup_required else None
    )

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_profile":
            account_form = CustomerAccountForm(request.POST, instance=request.user)
            profile_form = CustomerProfileForm(request.POST, request.FILES, instance=profile)
            if request.POST.get("remove_avatar") == "1" and profile.avatar:
                try:
                    profile.avatar.delete(save=False)
                except Exception:
                    pass
                profile.avatar = None
            if account_form.is_valid() and profile_form.is_valid():
                try:
                    with transaction.atomic():
                        account_form.save()
                        profile_obj = profile_form.save()
                        if profile_obj.address:
                            save_customer_address(
                                user=request.user,
                                phone=profile_obj.phone,
                                address=profile_obj.address,
                                city=profile_obj.city,
                                state=profile_obj.state,
                                postal_code=profile_obj.postal_code,
                                full_name=f"{request.user.first_name} {request.user.last_name}".strip(),
                                set_default=True,
                            )
                    messages.success(request, "Your profile has been updated.")
                    return redirect("customer_profile")
                except Exception as e:
                    messages.error(request, f"Could not save profile: {e}")
        elif action == "add_address":
            current_count = CustomerAddress.objects.filter(user=request.user).count()
            if current_count >= MAX_SAVED_ADDRESSES:
                messages.error(
                    request,
                    f"You can save up to {MAX_SAVED_ADDRESSES} addresses. Please delete an address first.",
                )
                return redirect("customer_profile")
            new_address_form = CustomerAddressForm(request.POST)
            if new_address_form.is_valid():
                data = new_address_form.cleaned_data
                save_customer_address(
                    user=request.user,
                    phone=data.get("phone", ""),
                    address=data.get("address", ""),
                    city=data.get("city", ""),
                    state=data.get("state", ""),
                    postal_code=data.get("postal_code", ""),
                    full_name=data.get("full_name", ""),
                    set_default=data.get("is_default", False),
                )
                messages.success(request, "New address added successfully.")
                return redirect("customer_profile")
            else:
                messages.error(request, "Please enter all required address fields.")
        elif action == "set_default_address":
            address_id = request.POST.get("address_id")
            addr = get_object_or_404(CustomerAddress, id=address_id, user=request.user)
            CustomerAddress.objects.filter(user=request.user).update(is_default=False)
            addr.is_default = True
            addr.save()
            CustomerProfile.objects.update_or_create(
                user=request.user,
                defaults={
                    "phone": addr.phone,
                    "address": addr.address,
                    "city": addr.city,
                    "state": addr.state,
                    "postal_code": addr.postal_code,
                },
            )
            messages.success(request, "Default delivery address updated.")
            return redirect("customer_profile")
        elif action == "delete_address":
            address_id = request.POST.get("address_id")
            addr = get_object_or_404(CustomerAddress, id=address_id, user=request.user)
            was_default = addr.is_default
            addr.delete()
            if was_default:
                next_addr = (
                    CustomerAddress.objects.filter(user=request.user)
                    .order_by("-updated_at")
                    .first()
                )
                if next_addr:
                    next_addr.is_default = True
                    next_addr.save()
                    CustomerProfile.objects.update_or_create(
                        user=request.user,
                        defaults={
                            "phone": next_addr.phone,
                            "address": next_addr.address,
                            "city": next_addr.city,
                            "state": next_addr.state,
                            "postal_code": next_addr.postal_code,
                        },
                    )
                else:
                    CustomerProfile.objects.filter(user=request.user).update(
                        address="", city="", state="", postal_code=""
                    )
            messages.success(request, "Address removed.")
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

    saved_addresses = get_user_saved_addresses(request.user)
    return render(
        request,
        "main/customer_profile.html",
        {
            "profile": profile,
            "account_form": account_form,
            "profile_form": profile_form,
            "new_address_form": new_address_form,
            "saved_addresses": saved_addresses,
            "can_add_address": len(saved_addresses) < MAX_SAVED_ADDRESSES,
            "max_addresses": MAX_SAVED_ADDRESSES,
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

    post_data = request.POST.copy()
    if request.user.is_authenticated and not post_data.get("email"):
        post_data["email"] = request.user.email

    address_form = DeliveryAddressForm(post_data)
    if not address_form.is_valid():
        return HttpResponseBadRequest("Complete all required delivery details.")
    details = address_form.cleaned_data
    postal_code = details.get("postal_code", "").strip()
    unavailable_items = [it for it in items if not it["product"].is_available_for_pincode(postal_code)]
    if unavailable_items:
        names = ", ".join(it["product"].name for it in unavailable_items)
        messages.error(
            request,
            f"The following drinks are not available for delivery to PIN code {postal_code}: {names}. Please update your delivery location or adjust your cart."
        )
        return redirect("cart")

    items_subtotal = sum((item["line_total"] for item in items), Decimal("0.00"))
    total_quantity = sum(item["quantity"] for item in items)
    site_details = SiteDetails.get_solo()
    packing_fee = site_details.calculate_packing_fee(total_quantity)
    shipping_fee = site_details.calculate_shipping_fee(details.get("state") or "")
    gst_amount = site_details.calculate_gst(items_subtotal)
    total_amount = items_subtotal + gst_amount + packing_fee + shipping_fee
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
            packing_fee=packing_fee,
            shipping_fee=shipping_fee,
            gst_amount=gst_amount,
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
    items_subtotal = unit_price * quantity
    site_details = SiteDetails.get_solo()
    order = None
    customer_profile = (
        CustomerProfile.objects.filter(user=request.user).first()
        if request.user.is_authenticated
        else None
    )

    saved_addresses = (
        get_user_saved_addresses(request.user)
        if request.user.is_authenticated
        else []
    )

    if request.method == "POST":
        post_data = request.POST.copy()
        if request.user.is_authenticated and not post_data.get("email"):
            post_data["email"] = request.user.email

        address_form = DeliveryAddressForm(post_data)
        if not address_form.is_valid():
            return HttpResponseBadRequest("Complete all required delivery details.")
        details = address_form.cleaned_data
        postal_code = details.get("postal_code", "").strip()
        if not product.is_available_for_pincode(postal_code):
            messages.error(
                request,
                f"Sorry, '{product.name}' is not deliverable to PIN code {postal_code}. Please choose a different delivery address."
            )
            return redirect(f"{reverse('checkout', kwargs={'product_id': product.id})}?qty={quantity}")

        state = details.get("state") or ""
        gst_amount = site_details.calculate_gst(items_subtotal)
        packing_fee = site_details.calculate_packing_fee(quantity)
        shipping_fee = site_details.calculate_shipping_fee(state)
        total_price = items_subtotal + gst_amount + packing_fee + shipping_fee

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
                packing_fee=packing_fee,
                shipping_fee=shipping_fee,
                gst_amount=gst_amount,
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

    initial_state = ""
    if saved_addresses:
        initial_state = saved_addresses[0].state
    elif customer_profile and customer_profile.state:
        initial_state = customer_profile.state

    initial_gst_amount = site_details.calculate_gst(items_subtotal)
    initial_packing_fee = site_details.calculate_packing_fee(quantity)
    initial_shipping_fee = site_details.calculate_shipping_fee(initial_state)
    initial_total_with_shipping = items_subtotal + initial_gst_amount + initial_packing_fee + initial_shipping_fee

    raw_phone = request.POST.get(
        "phone",
        saved_addresses[0].phone if saved_addresses else (customer_profile.phone if customer_profile else ""),
    )
    digits_phone = re.sub(r"\D", "", raw_phone)
    if len(digits_phone) == 12 and digits_phone.startswith("91"):
        clean_10_phone = digits_phone[2:]
    elif len(digits_phone) == 11 and digits_phone.startswith("0"):
        clean_10_phone = digits_phone[1:]
    else:
        clean_10_phone = digits_phone[-10:] if len(digits_phone) >= 10 else digits_phone

    initial_address = saved_addresses[0].address if saved_addresses else (customer_profile.address if customer_profile else "")
    initial_city = saved_addresses[0].city if saved_addresses else (customer_profile.city if customer_profile else "")
    initial_zip = saved_addresses[0].postal_code if saved_addresses else (customer_profile.postal_code if customer_profile else "")

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
                "image": product.image_url,
                "available_pincodes": product.available_pincodes,
                "available_pins_list": product.get_available_pincodes_list(),
            },
            "quantity": quantity,
            "unit_price": unit_price,
            "total_price": items_subtotal,
            "gst_rate": site_details.gst_rate,
            "gst_amount": initial_gst_amount,
            "packing_fee": initial_packing_fee,
            "packing_free_cans": site_details.packing_free_cans,
            "packing_cost_per_batch": site_details.packing_cost_per_batch,
            "packing_batch_size": site_details.packing_batch_size,
            "shipping_fee": initial_shipping_fee,
            "total_with_shipping": initial_total_with_shipping,
            "shipping_fee_local": site_details.shipping_fee_local,
            "shipping_fee_other": site_details.shipping_fee_other,
            "shipping_local_states": site_details.shipping_local_states,
            "indian_states": INDIAN_STATES,
            "payment_simulation_enabled": settings.PAYMENT_SIMULATION_ENABLED,
            "customer_profile": customer_profile,
            "customer_first_name": request.user.first_name if request.user.is_authenticated else "",
            "customer_last_name": request.user.last_name if request.user.is_authenticated else "",
            "customer_email": request.POST.get("email", request.user.email if request.user.is_authenticated else ""),
            "customer_phone_10_digits": clean_10_phone,
            "customer_address_form": {
                "phone": raw_phone,
                "address": request.POST.get("address", initial_address),
                "city": request.POST.get("city", initial_city),
                "state": request.POST.get("state", initial_state),
                "postal_code": request.POST.get("postal_code", initial_zip),
            },
            "saved_addresses": saved_addresses,
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

    User = get_user_model()
    has_staff = User.objects.filter(is_staff=True).exists()
    is_setup_mode = (request.GET.get("setup") in {"1", "admin", "true"}) or (not has_staff and request.GET.get("setup") != "0")
    setup_errors = []

    if request.method == "POST" and "setup_admin_submit" in request.POST:
        username = request.POST.get("setup_username", "").strip()
        password = request.POST.get("setup_password", "").strip()
        password_confirm = request.POST.get("setup_password_confirm", "").strip()
        email = request.POST.get("setup_email", "").strip()

        if not username:
            setup_errors.append("Please enter a username.")
        if not password or len(password) < 4:
            setup_errors.append("Password must be at least 4 characters.")
        if password != password_confirm:
            setup_errors.append("Passwords do not match.")

        if not setup_errors:
            user = User.objects.filter(username=username).first()
            if not user:
                user = User(username=username)
            if email:
                user.email = email
            user.set_password(password)
            user.is_staff = True
            user.is_superuser = True
            user.save()
            login(request, user)
            return redirect("admin_dashboard")
        is_setup_mode = True

    form = AdminLoginForm(request, data=request.POST or None)
    if request.method == "POST" and "setup_admin_submit" not in request.POST:
        is_setup_mode = False
        if form.is_valid():
            user = form.get_user()
            if user.is_staff:
                login(request, user)
                return redirect("admin_dashboard")
            form.add_error(None, "Admin access is restricted to staff accounts.")

    return render(
        request,
        "main/admin_login.html",
        {
            "form": form,
            "google_login_enabled": settings.GOOGLE_SIGN_IN_ENABLED,
            "is_setup_mode": is_setup_mode,
            "has_staff": has_staff,
            "setup_errors": setup_errors,
        },
    )


def delivery_partner_apply(request):
    if request.user.is_authenticated and DeliveryProfile.objects.filter(user=request.user).exists():
        dp = DeliveryProfile.objects.filter(user=request.user).first()
        if dp and dp.is_approved:
            return redirect("delivery_dashboard")

    if request.method == "POST":
        form = DeliveryPartnerApplicationForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = get_user_model().objects.create_user(
                    username=form.cleaned_data["username"].strip(),
                    email=form.cleaned_data["email"].strip().lower(),
                    password=form.cleaned_data["password"],
                    first_name=form.cleaned_data["first_name"].strip(),
                    last_name=form.cleaned_data.get("last_name", "").strip(),
                )
                dp = DeliveryProfile.objects.create(
                    user=user,
                    phone=form.cleaned_data["phone"].strip(),
                    address=form.cleaned_data["address"].strip(),
                    aadhar_number=form.cleaned_data["aadhar_number"].strip(),
                    driving_license=form.cleaned_data["driving_license"].strip(),
                    vehicle_type=form.cleaned_data["vehicle_type"],
                    vehicle_number=form.cleaned_data["vehicle_number"].strip(),
                    serviceable_pincodes=form.cleaned_data["serviceable_pincodes"].strip(),
                    is_approved=False,
                    status="pending",
                )
            return render(
                request,
                "main/delivery_apply_success.html",
                {
                    "applicant": dp,
                    "serviceable_pins": dp.get_serviceable_pincodes_list(),
                },
            )
        else:
            for error_list in form.errors.values():
                for error in error_list:
                    messages.error(request, error)
    else:
        form = DeliveryPartnerApplicationForm()

    return render(
        request,
        "main/delivery_apply.html",
        {
            "form": form,
            "vehicle_choices": DeliveryProfile.VEHICLE_CHOICES,
        },
    )


def delivery_login(request):
    if request.user.is_authenticated and DeliveryProfile.objects.filter(user=request.user).exists():
        dp = DeliveryProfile.objects.filter(user=request.user).first()
        if dp and not dp.is_approved:
            logout(request)
            messages.warning(
                request,
                "Your delivery partner account is currently pending admin verification. You can log in once approved.",
            )
            return redirect("delivery_login")
        return redirect("delivery_dashboard")

    form = EmailAuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        dp = DeliveryProfile.objects.filter(user=user).first()
        if dp:
            if not dp.is_approved:
                if dp.status == "rejected":
                    reason = dp.rejection_reason or "Document verification requirements were not met."
                    form.add_error(None, f"Your delivery partner application was not approved. Reason: {reason}")
                else:
                    form.add_error(
                        None,
                        "Your delivery partner application is under review. Our admin team will verify your Aadhaar, Licence, and Vehicle details soon.",
                    )
                return render(request, "main/delivery_login.html", {"form": form})
            login(request, user)
            return redirect("delivery_dashboard")
        form.add_error(None, "This account does not have delivery access.")

    return render(request, "main/delivery_login.html", {"form": form})


@login_required(login_url="delivery_login")
def delivery_dashboard(request):
    profile = DeliveryProfile.objects.filter(user=request.user).first()
    if not profile:
        return HttpResponseForbidden("Delivery access is required.")
    if not profile.is_approved:
        return HttpResponseForbidden("Your delivery partner account is pending admin approval.")

    active_tab = request.GET.get("tab", "picked").strip().lower()
    if active_tab not in {"picked", "available"}:
        active_tab = "picked"

    serviceable_pins = profile.get_serviceable_pincodes_list()

    # 1. Orders available to be picked (shows only SHIPPED unassigned orders ready for driver pickup)
    available_orders = (
        Order.objects.filter(status="shipped", delivery_user__isnull=True)
        .select_related("product", "customer")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )

    # Core requirement: Delivery partners can ONLY view orders whose PIN code they can deliver to
    if serviceable_pins:
        pin_q = Q()
        for pin in serviceable_pins:
            pin_q |= Q(delivery_postal_code__iexact=pin) | Q(delivery_postal_code__icontains=pin)
        available_orders = available_orders.filter(pin_q)

    available_count = available_orders.count()

    # 2. Orders picked by the current delivery partner
    picked_orders = (
        Order.objects.filter(delivery_user=request.user)
        .select_related("product", "customer")
        .prefetch_related("items__product")
        .order_by(
            models.Case(
                models.When(status="out_for_delivery", then=0),
                models.When(status="cancelled", then=1),
                models.When(status="returned", then=1),
                models.When(status="delivered", then=2),
                default=3,
            ),
            "-created_at",
        )
    )
    active_picked_count = picked_orders.filter(status="out_for_delivery").count()
    total_picked_count = picked_orders.count()

    # Compatibility for existing tests and templates
    if active_tab == "available":
        display_orders = available_orders
    else:
        display_orders = picked_orders

    return render(
        request,
        "main/delivery_dashboard.html",
        {
            "active_tab": active_tab,
            "available_orders": available_orders,
            "picked_orders": picked_orders,
            "available_count": available_count,
            "active_picked_count": active_picked_count,
            "total_picked_count": total_picked_count,
            "orders": display_orders,
            "profile": profile,
            "delivery_profile": profile,
            "serviceable_pins": serviceable_pins,
        },
    )


@login_required(login_url="delivery_login")
@require_POST
def pick_delivery_order(request, order_id):
    profile = DeliveryProfile.objects.filter(user=request.user).first()
    if not profile:
        return HttpResponseForbidden("Delivery access is required.")
    if not profile.is_approved:
        return HttpResponseForbidden("Your delivery partner account is pending admin approval.")

    order = get_object_or_404(Order, pk=order_id)

    # Core requirement: Delivery partners can ONLY pick orders whose PIN code they can deliver to
    if not profile.can_deliver_to_pincode(order.delivery_postal_code):
        pins_str = ", ".join(profile.get_serviceable_pincodes_list())
        messages.error(
            request,
            f"You cannot pick Order #{order.pk} because its delivery PIN code ({order.delivery_postal_code or 'Unspecified'}) is outside your assigned area ({pins_str}).",
        )
        return redirect(f"{reverse('delivery_dashboard')}?tab=available")

    # If already picked by another delivery partner, prevent double pickup
    if order.delivery_user is not None and order.delivery_user != request.user:
        messages.error(request, f"Order #{order.pk} has already been picked by another delivery partner.")
        return redirect(f"{reverse('delivery_dashboard')}?tab=available")

    # Only shipped orders can be picked
    if order.status not in ["shipped", "out_for_delivery"]:
        messages.error(
            request,
            f"Order #{order.pk} cannot be picked because it is not shipped yet (current status: {order.get_status_display()}).",
        )
        return redirect(f"{reverse('delivery_dashboard')}?tab=available")

    with transaction.atomic():
        order.delivery_user = request.user
        # Automatically update status to Out for Delivery
        order.status = "out_for_delivery"
        order.save(update_fields=["delivery_user", "status"])

    messages.success(request, f"Order #{order.pk} picked! Status automatically updated to Out for Delivery.")
    return redirect(f"{reverse('delivery_dashboard')}?tab=picked")


@login_required(login_url="delivery_login")
@require_POST
def update_delivery_status(request, order_id):
    if not DeliveryProfile.objects.filter(user=request.user).exists():
        return HttpResponseForbidden("Delivery access is required.")

    order = get_object_or_404(Order, pk=order_id)

    # If the order is assigned to another delivery driver, forbid
    if order.delivery_user is not None and order.delivery_user != request.user:
        return HttpResponseForbidden("You can only update orders assigned to you.")

    # If unassigned order is updated directly, assign to this driver
    if order.delivery_user is None:
        order.delivery_user = request.user

    status = request.POST.get("status")
    if status == "returned":
        status = "cancelled"
    # Delivery drivers can ONLY update to delivered or cancelled
    allowed_statuses = {"delivered", "cancelled"}
    if status not in allowed_statuses:
        return HttpResponseBadRequest("Delivery partners can only update orders as Delivered or Cancelled.")

    order.status = status
    order.delivered_at = timezone.now() if status == "delivered" else None
    order.save(update_fields=["status", "delivered_at", "delivery_user"])

    if status == "delivered":
        messages.success(request, f"Order #{order.pk} marked as Delivered.")
    else:
        messages.warning(request, f"Order #{order.pk} marked as Cancelled.")

    return redirect(f"{reverse('delivery_dashboard')}?tab=picked")


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def create_delivery_account(request):
    form = DeliveryAccountForm(request.POST)
    if form.is_valid():
        user = form.save()
        messages.success(request, f"Delivery account created for {user.get_username()}.")
    else:
        for error in form.errors.values():
            for message in error:
                messages.error(request, message)
    redirect_target = request.POST.get("next") or "admin_dashboard"
    return redirect(redirect_target)


def customer_login(request):
    if request.user.is_authenticated:
        if request.user.is_staff and not request.GET.get("next"):
            return redirect("admin_dashboard")
        return redirect(_customer_redirect_target(request))

    form = EmailAuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        login(request, user)
        if user.is_staff and not request.POST.get("next") and not request.GET.get("next"):
            return redirect("admin_dashboard")
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
    if request.user.is_authenticated and request.session.get(GUEST_PASSWORD_SETUP_SESSION_KEY, False):
        profile = CustomerProfile.objects.filter(user=request.user).first()
        if profile and profile.phone:
            request.user.set_password(profile.phone)
            request.user.save(update_fields=["password"])
    logout(request)
    return redirect("home")


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_dashboard(request):
    return admin_products(request)


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_products(request):
    edit_id = request.GET.get("edit")
    product_to_edit = get_object_or_404(Product, id=edit_id) if edit_id else None

    if request.method == "POST" and request.POST.get("action") == "add_category":
        cat_name = (request.POST.get("new_category_name") or "").strip()
        is_ajax = (
            request.headers.get("x-requested-with") == "XMLHttpRequest"
            or "application/json" in request.headers.get("accept", "")
        )
        if cat_name:
            slug = slugify(cat_name).replace("-", "_")
            cat_obj, created = ProductCategory.objects.get_or_create(slug=slug, defaults={"name": cat_name.title()})
            if is_ajax:
                return JsonResponse({"status": "ok", "slug": cat_obj.slug, "name": cat_obj.name, "created": created})
            if created:
                messages.success(request, f"Category '{cat_obj.name}' added successfully.")
            else:
                messages.info(request, f"Category '{cat_obj.name}' already exists.")
        else:
            if is_ajax:
                return JsonResponse({"status": "error", "message": "Please enter a valid category name."}, status=400)
            messages.error(request, "Please enter a valid category name.")
        return redirect("admin_products")

    if request.method == "POST":
        product_form = ProductForm(request.POST, request.FILES, instance=product_to_edit)
        if product_form.is_valid():
            product = product_form.save()
            if product_to_edit:
                messages.success(request, f"Product '{product.name}' updated successfully.")
            else:
                messages.success(request, f"Product '{product.name}' added successfully.")
            return redirect("admin_products")
        else:
            for field, error_list in product_form.errors.items():
                for error in error_list:
                    messages.error(request, f"{field.replace('_', ' ').title()}: {error}")
    else:
        product_form = ProductForm(instance=product_to_edit)

    products = Product.objects.order_by("name")
    total_products_count = products.count()
    available_count = products.filter(available=True).count()
    hidden_count = products.filter(available=False).count()
    total_delivery_users_count = DeliveryProfile.objects.count()
    pending_orders_count = Order.objects.filter(status="pending").count()
    all_categories = ProductCategory.objects.all().order_by("name")

    context = {
        "active_page": "products",
        "products": products,
        "product_form": product_form,
        "editing_product": product_to_edit,
        "total_products_count": total_products_count,
        "available_count": available_count,
        "hidden_count": hidden_count,
        "total_delivery_users_count": total_delivery_users_count,
        "pending_orders_count": pending_orders_count,
        "all_categories": all_categories,
    }
    return render(request, "main/admin_products.html", context)


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_toggle_product_availability(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    product.available = not product.available
    product.save(update_fields=["available"])
    status_label = "Active (visible to customers)" if product.available else "Hidden from storefront"
    messages.success(request, f"Availability for '{product.name}' set to {status_label}.")
    return redirect("admin_products")


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_update_product_pincodes(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    pincodes_raw = request.POST.get("available_pincodes", "").strip()
    codes = re.findall(r"\b\d{6}\b", pincodes_raw)
    if not codes and pincodes_raw:
        codes = [c.strip() for c in re.split(r"[,;\s]+", pincodes_raw) if c.strip()]
    product.available_pincodes = ", ".join(sorted(list(dict.fromkeys(codes))))
    product.save(update_fields=["available_pincodes"])
    messages.success(request, f"Updated available delivery PIN codes for '{product.name}'.")
    next_url = request.POST.get("next") or reverse("admin_products")
    return redirect(next_url)


def check_pincode_availability(request, product_id):
    product = get_object_or_404(Product, pk=product_id)
    pin = (request.GET.get("pin") or request.GET.get("pincode") or "").strip()
    if not pin:
        return JsonResponse({"available": False, "pincode": "", "message": "Please enter a PIN code."})
    is_available = product.is_available_for_pincode(pin)
    pins_list = product.get_available_pincodes_list()
    if is_available:
        msg = f"Delivery is available for PIN code {pin}!"
    else:
        if pins_list:
            msg = f"Sorry, {product.name} is not deliverable to PIN code {pin}. Available in: {', '.join(pins_list)}"
        else:
            msg = f"Sorry, {product.name} is currently unavailable for delivery."
    return JsonResponse({
        "available": is_available,
        "pincode": pin,
        "product_id": product.id,
        "product_name": product.name,
        "message": msg,
    })


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_delivery_users(request):
    if request.method == "POST":
        form = DeliveryAccountForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"Delivery staff account '{user.get_username()}' created successfully.")
            return redirect("admin_delivery_users")
        else:
            for error_list in form.errors.values():
                for error in error_list:
                    messages.error(request, error)
    else:
        form = DeliveryAccountForm()

    status_filter = request.GET.get("status", "all").strip().lower()
    search_query = request.GET.get("q", "").strip()

    delivery_profiles = DeliveryProfile.objects.select_related("user").order_by("-created_at")

    total_delivery_users_count = delivery_profiles.count()
    pending_delivery_users_count = delivery_profiles.filter(Q(status="pending") | Q(is_approved=False)).count()
    approved_delivery_users_count = delivery_profiles.filter(status="approved", is_approved=True).count()
    rejected_delivery_users_count = delivery_profiles.filter(status="rejected").count()
    total_products_count = Product.objects.count()
    pending_orders_count = Order.objects.filter(status="pending").count()

    if status_filter == "pending":
        filtered_profiles = delivery_profiles.filter(Q(status="pending") | Q(is_approved=False))
    elif status_filter == "approved":
        filtered_profiles = delivery_profiles.filter(status="approved", is_approved=True)
    elif status_filter == "rejected":
        filtered_profiles = delivery_profiles.filter(status="rejected")
    else:
        status_filter = "all"
        filtered_profiles = delivery_profiles

    if search_query:
        filtered_profiles = filtered_profiles.filter(
            Q(user__username__icontains=search_query)
            | Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
            | Q(user__email__icontains=search_query)
            | Q(phone__icontains=search_query)
            | Q(address__icontains=search_query)
            | Q(aadhar_number__icontains=search_query)
            | Q(driving_license__icontains=search_query)
            | Q(vehicle_number__icontains=search_query)
            | Q(serviceable_pincodes__icontains=search_query)
        )

    context = {
        "active_page": "delivery_users",
        "delivery_profiles": filtered_profiles,
        "delivery_form": form,
        "status_filter": status_filter,
        "search_query": search_query,
        "total_delivery_users_count": total_delivery_users_count,
        "pending_delivery_users_count": pending_delivery_users_count,
        "approved_delivery_users_count": approved_delivery_users_count,
        "rejected_delivery_users_count": rejected_delivery_users_count,
        "active_delivery_users_count": approved_delivery_users_count,
        "total_products_count": total_products_count,
        "pending_orders_count": pending_orders_count,
        "vehicle_choices": DeliveryProfile.VEHICLE_CHOICES,
    }
    return render(request, "main/admin_delivery_users.html", context)


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_approve_delivery_partner(request, profile_id):
    profile = get_object_or_404(DeliveryProfile, pk=profile_id)
    profile.is_approved = True
    profile.status = "approved"
    profile.rejection_reason = ""
    profile.save(update_fields=["is_approved", "status", "rejection_reason", "updated_at"])
    if not profile.user.is_active:
        profile.user.is_active = True
        profile.user.save(update_fields=["is_active"])
    messages.success(request, f"Delivery partner '{profile.user.username}' has been approved successfully.")
    next_url = request.POST.get("next") or reverse("admin_delivery_users")
    return redirect(next_url)


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_reject_delivery_partner(request, profile_id):
    profile = get_object_or_404(DeliveryProfile, pk=profile_id)
    reason = request.POST.get("rejection_reason", "").strip() or "Application rejected by admin."
    profile.is_approved = False
    profile.status = "rejected"
    profile.rejection_reason = reason
    profile.save(update_fields=["is_approved", "status", "rejection_reason", "updated_at"])
    messages.warning(request, f"Delivery partner '{profile.user.username}' has been rejected.")
    next_url = request.POST.get("next") or reverse("admin_delivery_users")
    return redirect(next_url)


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_update_delivery_pincodes(request, profile_id):
    profile = get_object_or_404(DeliveryProfile, pk=profile_id)
    pincodes_raw = request.POST.get("serviceable_pincodes", "").strip()
    codes = re.findall(r"\b\d{6}\b", pincodes_raw)
    if not codes:
        codes = [c.strip() for c in re.split(r"[,;\s]+", pincodes_raw) if c.strip()]
    profile.serviceable_pincodes = ", ".join(sorted(list(dict.fromkeys(codes))))

    if "vehicle_type" in request.POST:
        profile.vehicle_type = request.POST.get("vehicle_type", profile.vehicle_type)
    if "vehicle_number" in request.POST:
        profile.vehicle_number = request.POST.get("vehicle_number", profile.vehicle_number).strip()
    if "phone" in request.POST:
        profile.phone = request.POST.get("phone", profile.phone).strip()
    if "address" in request.POST:
        profile.address = request.POST.get("address", profile.address).strip()
    if "aadhar_number" in request.POST:
        profile.aadhar_number = request.POST.get("aadhar_number", profile.aadhar_number).strip()
    if "driving_license" in request.POST:
        profile.driving_license = request.POST.get("driving_license", profile.driving_license).strip()

    profile.save()
    messages.success(request, f"Updated delivery details & PIN codes for '{profile.user.username}'.")
    next_url = request.POST.get("next") or reverse("admin_delivery_users")
    return redirect(next_url)


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_delete_delivery_partner(request, profile_id):
    profile = get_object_or_404(DeliveryProfile, pk=profile_id)
    username = profile.user.username
    with transaction.atomic():
        profile.user.delete()
    messages.success(request, f"Delivery partner account '{username}' has been deleted.")
    next_url = request.POST.get("next") or reverse("admin_delivery_users")
    return redirect(next_url)


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_delivery_status(request):
    status_filter = request.GET.get("status", "all").strip().lower()
    if status_filter == "returned":
        status_filter = "cancelled"
    search_query = request.GET.get("q", "").strip()

    orders_queryset = (
        Order.objects.select_related("product", "delivery_user", "customer")
        .prefetch_related("items__product")
        .order_by("-created_at")
    )

    valid_statuses = {choice for choice, _ in Order.STATUS_CHOICES}
    if status_filter in valid_statuses:
        filtered_orders = orders_queryset.filter(status=status_filter)
    else:
        status_filter = "all"
        filtered_orders = orders_queryset

    if search_query:
        filtered_orders = filtered_orders.filter(
            Q(id__icontains=search_query)
            | Q(customer_name__icontains=search_query)
            | Q(customer_phone__icontains=search_query)
            | Q(delivery_address__icontains=search_query)
            | Q(delivery_city__icontains=search_query)
        )

    total_orders_count = orders_queryset.count()
    pending_count = orders_queryset.filter(status="pending").count()
    packed_count = orders_queryset.filter(status="packed").count()
    shipped_count = orders_queryset.filter(status="shipped").count()
    out_for_delivery_count = orders_queryset.filter(status="out_for_delivery").count()
    delivered_count = orders_queryset.filter(status="delivered").count()
    cancelled_count = orders_queryset.filter(status__in=["cancelled", "returned"]).count()

    context = {
        "active_page": "delivery_status",
        "orders": filtered_orders,
        "status_choices": Order.STATUS_CHOICES,
        "current_status_filter": status_filter,
        "search_query": search_query,
        "total_orders_count": total_orders_count,
        "pending_count": pending_count,
        "packed_count": packed_count,
        "shipped_count": shipped_count,
        "out_for_delivery_count": out_for_delivery_count,
        "delivered_count": delivered_count,
        "cancelled_count": cancelled_count,
        "returned_count": cancelled_count,
        "total_products_count": Product.objects.count(),
        "total_delivery_users_count": DeliveryProfile.objects.count(),
        "pending_orders_count": pending_count,
    }
    return render(request, "main/admin_delivery_status.html", context)


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_update_order_status(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    new_status = request.POST.get("status")
    if new_status == "returned":
        new_status = "cancelled"
    valid_statuses = {choice for choice, _ in Order.STATUS_CHOICES}
    if new_status not in valid_statuses:
        if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
            return JsonResponse({"status": "error", "message": "Please choose a valid delivery status."}, status=400)
        messages.error(request, "Please choose a valid delivery status.")
        return redirect("admin_delivery_status")

    order.status = new_status
    if new_status == "delivered":
        order.delivered_at = timezone.now()
    else:
        order.delivered_at = None
    order.save(update_fields=["status", "delivered_at"])
    messages.success(request, f"Order #{order.pk} status updated to {order.get_status_display()}.")

    if request.headers.get("x-requested-with") == "XMLHttpRequest" or "application/json" in request.headers.get("Accept", ""):
        return JsonResponse({
            "status": "success",
            "order_id": order.id,
            "new_status": new_status,
            "new_status_display": order.get_status_display(),
            "message": f"Order #{order.pk} status updated to {order.get_status_display()}."
        })

    next_url = request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect("admin_delivery_status")


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_order_detail(request, order_id):
    order = get_object_or_404(
        Order.objects.select_related("product", "delivery_user", "customer")
        .prefetch_related("items__product"),
        pk=order_id,
    )
    if request.method == "POST":
        new_status = request.POST.get("status")
        if new_status == "returned":
            new_status = "cancelled"
        valid_statuses = {choice for choice, _ in Order.STATUS_CHOICES}
        if new_status in valid_statuses:
            order.status = new_status
            if new_status == "delivered":
                order.delivered_at = timezone.now()
            else:
                order.delivered_at = None
            order.save(update_fields=["status", "delivered_at"])
            messages.success(request, f"Order #{order.pk} status updated to {order.get_status_display()}.")
            return redirect("admin_order_detail", order_id=order.pk)
        else:
            messages.error(request, "Please choose a valid delivery status.")

    context = {
        "active_page": "delivery_status",
        "order": order,
        "status_choices": Order.STATUS_CHOICES,
        "total_products_count": Product.objects.count(),
        "total_delivery_users_count": DeliveryProfile.objects.count(),
        "pending_orders_count": Order.objects.filter(status="pending").count(),
    }
    return render(request, "main/admin_order_detail.html", context)


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_details(request):
    details = SiteDetails.get_solo()
    active_tab = request.GET.get("tab", "messages").strip().lower()
    if active_tab not in {"messages", "about", "contact"}:
        active_tab = "messages"

    about_form = AboutDetailsForm(instance=details)
    contact_form = ContactDetailsForm(instance=details)

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "save_about":
            about_form = AboutDetailsForm(request.POST, instance=details)
            if about_form.is_valid():
                about_form.save()
                messages.success(request, "About Us page details updated successfully.")
                return redirect(f"{reverse('admin_details')}?tab=about")
            else:
                active_tab = "about"
                for err_list in about_form.errors.values():
                    for err in err_list:
                        messages.error(request, err)
        elif action == "save_contact":
            contact_form = ContactDetailsForm(request.POST, instance=details)
            if contact_form.is_valid():
                contact_form.save()
                messages.success(request, "Contact Us page details updated successfully.")
                return redirect(f"{reverse('admin_details')}?tab=contact")
            else:
                active_tab = "contact"
                for err_list in contact_form.errors.values():
                    for err in err_list:
                        messages.error(request, err)

    contact_messages = ContactMessage.objects.all().order_by("-created_at")
    total_messages_count = contact_messages.count()
    unread_messages_count = contact_messages.filter(is_read=False).count()

    context = {
        "active_page": "details",
        "active_tab": active_tab,
        "details": details,
        "about_form": about_form,
        "contact_form": contact_form,
        "contact_messages": contact_messages,
        "total_messages_count": total_messages_count,
        "unread_messages_count": unread_messages_count,
        "total_products_count": Product.objects.count(),
        "total_delivery_users_count": DeliveryProfile.objects.count(),
        "pending_orders_count": Order.objects.filter(status="pending").count(),
    }
    return render(request, "main/admin_details.html", context)


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_shipping_charges(request):
    details = SiteDetails.get_solo()
    if request.method == "POST":
        shipping_form = ShippingChargesForm(request.POST, instance=details)
        if shipping_form.is_valid():
            shipping_form.save()
            messages.success(request, "Shipping charges and regional delivery rules updated successfully.")
            return redirect("admin_shipping_charges")
        else:
            for err_list in shipping_form.errors.values():
                for err in err_list:
                    messages.error(request, err)
    else:
        shipping_form = ShippingChargesForm(instance=details)

    selected_states_list = [
        s.strip() for s in (details.shipping_local_states or "").split(",") if s.strip()
    ]

    context = {
        "active_page": "shipping_charges",
        "details": details,
        "shipping_form": shipping_form,
        "indian_states": INDIAN_STATES,
        "selected_states_list": selected_states_list,
        "selected_states_count": len(selected_states_list),
        "total_products_count": Product.objects.count(),
        "total_delivery_users_count": DeliveryProfile.objects.count(),
        "pending_orders_count": Order.objects.filter(status="pending").count(),
        "unread_messages_count": ContactMessage.objects.filter(is_read=False).count(),
    }
    return render(request, "main/admin_shipping_charges.html", context)


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_packing_charges(request):
    details = SiteDetails.get_solo()
    if request.method == "POST":
        packing_form = PackingChargesForm(request.POST, instance=details)
        if packing_form.is_valid():
            packing_form.save()
            messages.success(request, "Packing charges and carton rules updated successfully.")
            return redirect("admin_packing_charges")
        else:
            for err_list in packing_form.errors.values():
                for err in err_list:
                    messages.error(request, err)
    else:
        packing_form = PackingChargesForm(instance=details)

    context = {
        "active_page": "packing_charges",
        "details": details,
        "packing_form": packing_form,
        "total_products_count": Product.objects.count(),
        "total_delivery_users_count": DeliveryProfile.objects.count(),
        "pending_orders_count": Order.objects.filter(status="pending").count(),
        "unread_messages_count": ContactMessage.objects.filter(is_read=False).count(),
    }
    return render(request, "main/admin_packing_charges.html", context)


@login_required
@user_passes_test(lambda user: user.is_staff)
def admin_shipping_rates(request):
    return redirect("admin_shipping_charges")


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_toggle_message_read(request, message_id):
    msg = get_object_or_404(ContactMessage, pk=message_id)
    msg.is_read = not msg.is_read
    msg.save(update_fields=["is_read"])
    status_str = "read" if msg.is_read else "unread"
    messages.success(request, f"Message from '{msg.name}' marked as {status_str}.")
    return redirect(f"{reverse('admin_details')}?tab=messages")


@login_required
@user_passes_test(lambda user: user.is_staff)
@require_POST
def admin_delete_message(request, message_id):
    msg = get_object_or_404(ContactMessage, pk=message_id)
    sender = msg.name
    msg.delete()
    messages.success(request, f"Message from '{sender}' was deleted.")
    return redirect(f"{reverse('admin_details')}?tab=messages")


