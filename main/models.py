from decimal import Decimal
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone
import uuid


INDIAN_STATES = [
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
]


class ProductCategory(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Product categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Product(models.Model):
    CATEGORY_CHOICES = [
        ("cola", "Cola"),
        ("energy_drink", "Energy Drink"),
        ("others", "Others"),
    ]

    name = models.CharField(max_length=100)
    category = models.CharField(max_length=60, default="others")
    description = models.TextField(blank=True)
    cost_price = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=Decimal("60.00"),
        verbose_name="Cost Price (₹)",
        help_text="Store wholesale/cost price per unit (recommended ₹60.00)."
    )
    price = models.DecimalField(max_digits=8, decimal_places=2, default=90)
    volume = models.CharField(max_length=20, default="330 ml")
    image = models.CharField(max_length=255)
    available_pincodes = models.TextField(
        blank=True,
        help_text="Comma-separated 6-digit postal codes where this product is deliverable. Leave empty for all PIN codes.",
        verbose_name="Available PIN Codes",
    )
    available = models.BooleanField(default=True)

    def __str__(self):
        return self.name

    @property
    def profit_amount(self):
        cp = self.cost_price if self.cost_price is not None else Decimal("60.00")
        sp = self.price if self.price is not None else Decimal("0.00")
        return max(Decimal("0.00"), sp - cp)

    @property
    def profit_margin_percent(self):
        cp = self.cost_price if self.cost_price is not None else Decimal("60.00")
        sp = self.price if self.price is not None else Decimal("0.00")
        if sp > Decimal("0.00"):
            return round(((sp - cp) / sp) * Decimal("100.0"), 1)
        return Decimal("0.0")

    def get_available_pincodes_list(self):
        if not self.available_pincodes:
            return []
        import re
        codes = re.findall(r"\b\d{6}\b", self.available_pincodes)
        if not codes:
            codes = [c.strip() for c in re.split(r"[,;\s]+", self.available_pincodes) if c.strip()]
        return sorted(list(dict.fromkeys(codes)))

    def is_available_for_pincode(self, pincode):
        if not self.available:
            return False
        codes = self.get_available_pincodes_list()
        if not codes:
            return True
        if not pincode:
            return False
        import re
        clean_pin = re.sub(r"\D", "", str(pincode).strip())
        return clean_pin in codes or str(pincode).strip() in codes

    @property
    def category_slug(self):
        cat = (self.category or "").lower().strip()
        if cat in ["cola", "energy_drink"]:
            return cat
        if cat == "others" or not cat:
            name_lower = (self.name or "").lower()
            if "cola" in name_lower:
                return "cola"
            if "energy" in name_lower:
                return "energy_drink"
            return "others"
        from django.utils.text import slugify
        return slugify(cat).replace("-", "_")

    @property
    def category_display(self):
        slug = self.category_slug
        if slug == "cola":
            return "Cola"
        elif slug == "energy_drink":
            return "Energy Drink"
        elif slug == "others":
            return "Others"
        try:
            pc = ProductCategory.objects.filter(slug=slug).first()
            if pc:
                return pc.name
        except Exception:
            pass
        return slug.replace("_", " ").title()

    @property
    def category_name(self):
        return self.category_display

    @property
    def image_url(self):
        img = (self.image or "").strip()
        if not img:
            return "/static/main/images/cola.png"
        if img.startswith("http://") or img.startswith("https://") or img.startswith("/"):
            return img
        if img.startswith("media/"):
            return f"/{img}"
        if img.startswith("static/"):
            return f"/{img}"
        if "/" not in img:
            return f"/static/main/images/{img}"
        return f"/static/{img}"


class DeliveryProfile(models.Model):
    VEHICLE_CHOICES = [
        ("bike", "Motorcycle / Bike"),
        ("scooter", "Scooter / Moped"),
        ("ev", "Electric Vehicle (EV)"),
        ("auto", "Auto Rickshaw (3-Wheeler)"),
        ("van", "Delivery Van / Mini Truck"),
        ("car", "Car"),
        ("other", "Other"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending Verification"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="delivery_profile",
        on_delete=models.CASCADE,
    )
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True, verbose_name="Address")
    aadhar_number = models.CharField(max_length=30, blank=True, verbose_name="Aadhaar Number")
    driving_license = models.CharField(max_length=50, blank=True, verbose_name="Driving Licence")
    vehicle_type = models.CharField(max_length=30, choices=VEHICLE_CHOICES, default="bike")
    vehicle_number = models.CharField(max_length=40, blank=True, verbose_name="Vehicle Number")
    serviceable_pincodes = models.TextField(
        blank=True,
        help_text="Comma-separated postal/PIN codes this partner can deliver to (e.g. 625018, 625001)",
    )
    is_approved = models.BooleanField(default=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="approved")
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Delivery profile for {self.user.get_username()} ({self.get_status_display()})"

    def get_serviceable_pincodes_list(self):
        if not self.serviceable_pincodes:
            return []
        import re
        codes = re.findall(r"\b\d{6}\b", self.serviceable_pincodes)
        if not codes:
            codes = [c.strip() for c in re.split(r"[,;\s]+", self.serviceable_pincodes) if c.strip()]
        return sorted(list(dict.fromkeys(codes)))

    def can_deliver_to_pincode(self, pincode):
        pincodes = self.get_serviceable_pincodes_list()
        if not pincodes:
            return True
        if not pincode:
            return False
        import re
        clean_pin = re.sub(r"\D", "", str(pincode).strip())
        return clean_pin in pincodes or str(pincode).strip() in pincodes

    @property
    def vehicle_display(self):
        return dict(self.VEHICLE_CHOICES).get(self.vehicle_type, self.vehicle_type.title())


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="customer_profile",
        on_delete=models.CASCADE,
    )
    avatar = models.ImageField(upload_to="profile_photos/", blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"Customer profile for {self.user.get_username()}"


class CustomerAddress(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="addresses",
        on_delete=models.CASCADE,
    )
    full_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-is_default", "-updated_at", "-created_at"]

    def __str__(self):
        return f"{self.user.get_username()} - {self.address}"


class Coupon(models.Model):
    DISCOUNT_TYPE_CHOICES = [
        ("percentage", "Percentage (%)"),
        ("fixed", "Fixed Amount (₹)"),
    ]

    code = models.CharField(max_length=50, unique=True, db_index=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES, default="percentage")
    discount_value = models.DecimalField(max_digits=10, decimal_places=2)
    min_order_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum total uses across all orders. Leave blank for unlimited.",
    )
    expire_date = models.DateField(
        null=True,
        blank=True,
        help_text="Expiry date for coupon.",
    )
    applicable_categories = models.ManyToManyField(
        ProductCategory,
        blank=True,
        related_name="coupons",
        help_text="Selective categories this coupon applies to. Leave empty for all categories.",
    )
    times_used = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} ({self.get_discount_type_display()} - {self.discount_value})"

    def clean(self):
        if self.code:
            self.code = self.code.strip().upper()
        if self.discount_type == "percentage" and self.discount_value is not None:
            if self.discount_value > 100:
                raise ValidationError({"discount_value": "Percentage discount cannot exceed 100%."})
            if self.discount_value <= 0:
                raise ValidationError({"discount_value": "Discount value must be greater than 0."})
        elif self.discount_type == "fixed" and self.discount_value is not None:
            if self.discount_value <= 0:
                raise ValidationError({"discount_value": "Discount value must be greater than 0."})

    def save(self, *args, **kwargs):
        if self.code:
            self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        if not self.expire_date:
            return False
        return self.expire_date < timezone.localdate()

    @property
    def is_usage_limit_reached(self):
        if self.usage_limit is not None and self.usage_limit > 0:
            return self.times_used >= self.usage_limit
        return False

    @property
    def is_valid_status(self):
        return self.is_active and not self.is_expired and not self.is_usage_limit_reached

    @property
    def discount_display(self):
        if self.discount_type == "percentage":
            val = int(self.discount_value) if self.discount_value == int(self.discount_value) else self.discount_value
            return f"{val}% OFF"
        val = int(self.discount_value) if self.discount_value == int(self.discount_value) else self.discount_value
        return f"₹{val} OFF"

    @property
    def categories_display(self):
        cats = list(self.applicable_categories.all())
        if not cats:
            return "All Categories"
        return ", ".join(c.name for c in cats)

    def calculate_discount(self, items_subtotal, order_items_data=None):
        if items_subtotal < self.min_order_amount:
            return Decimal("0.00")

        target_subtotal = items_subtotal
        cats = list(self.applicable_categories.all())
        if cats and order_items_data:
            cat_slugs = {c.slug.lower() for c in cats}
            cat_names = {c.name.lower() for c in cats}
            eligible_subtotal = Decimal("0.00")
            for it in order_items_data:
                prod = it.get("product")
                prod_cat = getattr(prod, "category", "") or ""
                if prod_cat.lower() in cat_slugs or prod_cat.lower() in cat_names:
                    qty = it.get("quantity", 1)
                    price = getattr(prod, "price", Decimal("0.00"))
                    eligible_subtotal += Decimal(str(price)) * int(qty)
            target_subtotal = eligible_subtotal
            if target_subtotal <= 0:
                return Decimal("0.00")

        if self.discount_type == "percentage":
            discount = (target_subtotal * (self.discount_value / Decimal("100"))).quantize(Decimal("0.01"))
        else:
            discount = min(target_subtotal, self.discount_value)

        return max(Decimal("0.00"), discount)


class ComboOffer(models.Model):
    OFFER_TYPE_CHOICES = [
        ("bundle", "Combo Bundle"),
        ("multiple_products", "Multiple Products Combo"),
        ("single_quantity", "Single Quantity Offer"),
        ("price_based", "Price Based Offer"),
    ]
    DISCOUNT_TYPE_CHOICES = [
        ("percentage", "Percentage (%)"),
        ("fixed", "Fixed Price (₹)"),
    ]

    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, blank=True)
    offer_type = models.CharField(
        max_length=30,
        choices=OFFER_TYPE_CHOICES,
        default="bundle",
    )
    applicable_categories = models.ManyToManyField(
        ProductCategory,
        blank=True,
        related_name="combo_offers",
        help_text="Selective categories this combo applies to. Leave empty for all categories.",
    )
    applicable_products = models.ManyToManyField(
        Product,
        blank=True,
        related_name="combo_offers",
        help_text="Selective products this combo applies to. Leave empty for all products.",
    )
    usage_limit = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum total uses across all orders. Leave blank for unlimited.",
    )
    discount_type = models.CharField(
        max_length=20,
        choices=DISCOUNT_TYPE_CHOICES,
        default="percentage",
    )
    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("15.00"),
    )
    max_discount_cap = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Maximum discount amount in ₹ (applies to percentage discounts).",
    )
    min_order_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        blank=True,
        null=True,
        help_text="Minimum order amount.",
    )
    min_quantity = models.PositiveIntegerField(
        default=1,
        blank=True,
        null=True,
        help_text="Minimum items quantity required.",
    )
    min_distinct_products = models.PositiveIntegerField(
        default=1,
        blank=True,
        null=True,
        help_text="Minimum distinct products required.",
    )
    expire_date = models.DateField(
        null=True,
        blank=True,
        help_text="Expiry Date for combo offer.",
    )
    image = models.ImageField(
        upload_to="combos/",
        blank=True,
        null=True,
        help_text="Upload combo pack showcase image.",
    )
    image_data_url = models.TextField(
        blank=True,
        default="",
        help_text="Base64 Data URL for persistent image display.",
    )
    show_in_announcement = models.BooleanField(
        default=True,
        help_text="Show this combo offer in the top announcement bar slider.",
    )
    announcement_text = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Custom highlight text for announcement bar slide (optional).",
    )
    times_used = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    description = models.TextField(
        blank=True,
        default="Mix and match our handcrafted cans to unlock special combo bundle pricing!",
    )
    badge_text = models.CharField(
        max_length=100,
        default="",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.get_offer_type_display()} - {self.discount_display})"

    def clean(self):
        if self.name:
            self.name = self.name.strip()
        if self.discount_type == "percentage" and self.discount_value is not None:
            if self.discount_value > 100 or self.discount_value <= 0:
                raise ValidationError({"discount_value": "Percentage discount must be between 0.01% and 100%."})
        elif self.discount_type == "fixed" and self.discount_value is not None:
            if self.discount_value <= 0:
                raise ValidationError({"discount_value": "Discount value must be greater than 0."})
        if self.min_order_amount is not None and self.min_order_amount < 0:
            raise ValidationError({"min_order_amount": "Minimum order amount cannot be negative."})
        if self.max_discount_cap is not None and self.max_discount_cap <= 0:
            raise ValidationError({"max_discount_cap": "Max discount cap must be greater than 0."})

    def save(self, *args, **kwargs):
        if self.name and not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        if not self.expire_date:
            return False
        return self.expire_date < timezone.localdate()

    @property
    def is_usage_limit_reached(self):
        if self.usage_limit is not None and self.usage_limit > 0:
            return self.times_used >= self.usage_limit
        return False

    @property
    def is_valid_status(self):
        return self.is_active and not self.is_expired and not self.is_usage_limit_reached

    @property
    def discount_display(self):
        val = int(self.discount_value) if self.discount_value == int(self.discount_value) else self.discount_value
        if self.discount_type == "percentage":
            return f"{val}% OFF"
        return f"₹{val} OFF"

    @property
    def categories_display(self):
        cats = list(self.applicable_categories.all())
        if not cats:
            return "All Categories"
        return ", ".join(c.name for c in cats)

    @property
    def products_display(self):
        prods = list(self.applicable_products.all())
        if not prods:
            return "All Products"
        return ", ".join(p.name for p in prods)

    @property
    def offer_type_display(self):
        return dict(self.OFFER_TYPE_CHOICES).get(self.offer_type, self.offer_type.replace("_", " ").title())

    @property
    def bundle_items_display(self):
        items = list(self.bundle_items.select_related("product").all())
        if items:
            return ", ".join(f"{it.quantity}× {it.product.name}" for it in items)
        prods = list(self.applicable_products.all())
        if prods:
            return ", ".join(f"1× {p.name}" for p in prods)
        return "All Products"

    @property
    def total_bundle_cans(self):
        items = list(self.bundle_items.all())
        if items:
            return sum(it.quantity for it in items)
        return self.min_quantity or 6

    @property
    def bundle_regular_price(self):
        items = list(self.bundle_items.select_related("product").all())
        if items:
            return sum(it.product.price * it.quantity for it in items)
        prods = list(self.applicable_products.all())
        if prods:
            return sum(p.price for p in prods)
        return Decimal("540.00")

    @property
    def bundle_discounted_price(self):
        reg = self.bundle_regular_price
        if self.discount_type == "percentage":
            disc = (reg * (self.discount_value / Decimal("100.00"))).quantize(Decimal("0.01"))
            if self.max_discount_cap and disc > self.max_discount_cap:
                disc = self.max_discount_cap
            return max(Decimal("0.00"), reg - disc)
        elif self.discount_type == "fixed":
            return max(Decimal("0.00"), reg - self.discount_value)
        return reg

    @property
    def bundle_savings(self):
        return max(Decimal("0.00"), self.bundle_regular_price - self.bundle_discounted_price)

    @property
    def image_url(self):
        if hasattr(self, "image_data_url") and self.image_data_url and self.image_data_url.strip():
            return self.image_data_url.strip()
        if self.image:
            try:
                url = self.image.url
                if url:
                    return url
            except Exception:
                pass
            name = str(self.image).strip()
            if name:
                if name.startswith("http://") or name.startswith("https://") or name.startswith("/") or name.startswith("data:"):
                    return name
                return f"/media/{name}"
        # If combo bundle has a single product, use that product's image
        items = list(self.bundle_items.select_related("product").all()[:2])
        if len(items) == 1 and hasattr(items[0].product, "image_url"):
            return items[0].product.image_url
        prods = list(self.applicable_products.all()[:2])
        if len(prods) == 1 and hasattr(prods[0], "image_url"):
            return prods[0].image_url
        return "/static/main/images/combos/cans_of_assortment.png"

    def evaluate_cart(self, cart_items, subtotal=None):
        if not self.is_valid_status:
            return False, Decimal("0.00"), {}

        items = list(self.bundle_items.select_related("product").all())
        cart_product_qtys = {}
        for it in cart_items:
            prod = it.get("product")
            if prod:
                cart_product_qtys[prod.id] = cart_product_qtys.get(prod.id, 0) + it.get("quantity", 1)

        qualifies = False
        bundle_price = Decimal("0.00")

        if items:
            # Bundle requirements check: cart must contain every bundle product with at least required quantity
            meets_all = True
            for b_item in items:
                in_cart_qty = cart_product_qtys.get(b_item.product_id, 0)
                if in_cart_qty < b_item.quantity:
                    meets_all = False
                    break
            if meets_all:
                qualifies = True
                bundle_price = sum(it.product.price * it.quantity for it in items)
        else:
            # Fallback for combos without bundle items defined
            prods = list(self.applicable_products.all())
            prod_ids = {p.id for p in prods}
            cats = list(self.applicable_categories.all())
            cat_slugs = {c.slug.lower() for c in cats}
            cat_names = {c.name.lower() for c in cats}

            eligible_items = []
            eligible_subtotal = Decimal("0.00")
            for it in cart_items:
                prod = it.get("product")
                if not prod:
                    continue
                is_eligible = True
                if prods:
                    is_eligible = prod.id in prod_ids
                elif cats:
                    prod_cat = (getattr(prod, "category", "") or "").lower().strip()
                    prod_cat_slug = (getattr(prod, "category_slug", "") or "").lower().strip()
                    is_eligible = (
                        prod_cat in cat_slugs
                        or prod_cat in cat_names
                        or prod_cat_slug in cat_slugs
                    )
                if is_eligible:
                    eligible_items.append(it)
                    qty = it.get("quantity", 1)
                    price = getattr(prod, "price", Decimal("0.00"))
                    eligible_subtotal += Decimal(str(price)) * int(qty)

            if eligible_items:
                total_eligible_qty = sum(it.get("quantity", 1) for it in eligible_items)
                distinct_eligible_count = len({it["product"].id for it in eligible_items})
                min_q = self.min_quantity or 6
                min_d = min(len(prods), self.min_distinct_products or 1) if prods else (self.min_distinct_products or 6)
                if total_eligible_qty >= min_q and distinct_eligible_count >= min_d:
                    qualifies = True
                    bundle_price = eligible_subtotal

        if not qualifies or bundle_price <= Decimal("0.00"):
            return False, Decimal("0.00"), {}

        if self.discount_type == "percentage":
            discount = (bundle_price * (self.discount_value / Decimal("100"))).quantize(Decimal("0.01"))
            if self.max_discount_cap and self.max_discount_cap > Decimal("0.00"):
                discount = min(discount, self.max_discount_cap)
        else:
            discount = min(bundle_price, self.discount_value)

        discount = max(Decimal("0.00"), discount)
        eligible_pids = [it.product_id for it in items] if items else [it["product"].id for it in eligible_items]
        return True, discount, {
            "combo_id": self.id,
            "name": self.name,
            "badge_text": self.badge_text or self.name,
            "distinct_count": len(cart_product_qtys),
            "total_qty": sum(cart_product_qtys.values()),
            "bundle_items": [f"{it.quantity}× {it.product.name}" for it in items],
            "eligible_product_ids": eligible_pids,
            "regular_price": bundle_price,
            "final_price": max(Decimal("0.00"), bundle_price - discount),
        }


class ComboBundleItem(models.Model):
    combo_offer = models.ForeignKey(
        ComboOffer, on_delete=models.CASCADE, related_name="bundle_items"
    )
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="combo_bundle_items"
    )
    quantity = models.PositiveIntegerField(default=1)

    class Meta:
        ordering = ["id"]
        unique_together = ("combo_offer", "product")

    def __str__(self):
        return f"{self.quantity}× {self.product.name} in {self.combo_offer.name}"


class Order(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ("pending", "Payment pending"),
        ("paid", "Paid"),
        ("failed", "Payment failed"),
    ]

    PAYMENT_METHOD_CHOICES = [
        ("online", "Online Payment"),
        ("cod", "Cash on Delivery"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("packed", "Packed"),
        ("shipped", "Shipped"),
        ("out_for_delivery", "Out for delivery"),
        ("delivered", "Delivered"),
        ("cancelled", "Cancelled"),
    ]

    product = models.ForeignKey(Product, related_name="orders", on_delete=models.CASCADE)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="orders",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    delivery_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="delivery_orders",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    customer_name = models.CharField(max_length=100, default="Walk-in customer")
    customer_phone = models.CharField(max_length=20, blank=True)
    delivery_address = models.CharField(max_length=255, blank=True)
    delivery_city = models.CharField(max_length=100, blank=True)
    delivery_state = models.CharField(max_length=100, blank=True)
    delivery_postal_code = models.CharField(max_length=20, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    payment_status = models.CharField(
        max_length=12, choices=PAYMENT_STATUS_CHOICES, default="pending"
    )
    payment_method = models.CharField(
        max_length=20, choices=PAYMENT_METHOD_CHOICES, default="online"
    )
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    packing_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    gst_amount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    combo_offer = models.ForeignKey(
        ComboOffer,
        related_name="orders",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    combo_name = models.CharField(max_length=120, blank=True, default="")
    combo_discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    coupon = models.ForeignKey(
        Coupon,
        related_name="orders",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    coupon_code = models.CharField(max_length=50, blank=True, default="")
    payment_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    order_number = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Order Number",
        help_text="Unique randomly generated non-sequential order number.",
    )
    payment_event_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    cashfree_order_id = models.CharField(max_length=100, blank=True, default="")
    cashfree_payment_session_id = models.TextField(blank=True, default="")
    razorpay_order_id = models.CharField(max_length=100, blank=True, default="")
    razorpay_payment_id = models.CharField(max_length=100, blank=True, default="")
    razorpay_signature = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    @property
    def items_subtotal(self):
        sub = (
            self.total_amount
            + self.discount_amount
            + self.combo_discount
            - self.shipping_fee
            - self.packing_fee
            - self.gst_amount
        )
        return sub if sub > 0 else self.total_amount

    @classmethod
    def generate_unique_order_number(cls):
        """
        Generates a unique, non-sequential 6-digit random order number (e.g. '749218').
        Guarantees uniqueness across all orders in the database.
        """
        import secrets
        for _ in range(500):
            candidate = str(secrets.randbelow(900000) + 100000)
            if not cls.objects.filter(order_number=candidate).exists():
                return candidate
        for _ in range(500):
            candidate = str(secrets.randbelow(90000000) + 10000000)
            if not cls.objects.filter(order_number=candidate).exists():
                return candidate
        import uuid
        return str(uuid.uuid4().int)[:8]

    @property
    def display_order_number(self):
        return f"#{self.order_number}" if self.order_number else f"#{self.id}"

    @property
    def order_code(self):
        return self.order_number or str(self.id)

    def save(self, *args, **kwargs):
        if self.status == "returned":
            self.status = "cancelled"
        if not self.order_number:
            self.order_number = self.generate_unique_order_number()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order #{self.order_number or self.pk} - {self.status}"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=8, decimal_places=2)

    @property
    def line_total(self):
        return self.unit_price * self.quantity

    def __str__(self):
        return f"{self.product.name} × {self.quantity}"


class SiteDetails(models.Model):
    # About Us Page fields
    about_kicker = models.CharField(max_length=100, default="About J CSD")
    about_title = models.CharField(max_length=200, default="Better drinks.<br>Less noise.")
    about_lead = models.TextField(
        default="We make refreshing canned drinks for everyday moments. Bold flavours, clean design, and nothing unnecessary."
    )
    about_note = models.TextField(
        default="Pick a flavour, make it yours, and enjoy the moment."
    )
    about_action_text = models.CharField(max_length=100, default="Explore the lineup")
    about_action_url = models.CharField(max_length=200, default="/#shop")

    # Contact Us Page fields
    contact_kicker = models.CharField(max_length=100, default="Get in touch")
    contact_title = models.CharField(max_length=200, default="Let's connect.")
    contact_lead = models.TextField(
        default="Have questions about our flavours, bulk wholesale, or an active order? Reach out via direct channels or send us a quick note."
    )
    support_email = models.CharField(max_length=150, default="support@jcsd.com")
    support_phone = models.CharField(max_length=50, default="+91 80568 38888")
    whatsapp_number = models.CharField(max_length=50, default="+91 80568 38888")
    operating_hours = models.TextField(
        default="Monday – Saturday: 9:00 AM – 8:00 PM IST\nSunday: 10:00 AM – 6:00 PM IST\nEveryday order dispatch & delivery tracking."
    )

    # Shipping & Delivery Rates Configuration
    shipping_fee_local = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("50.00"),
        verbose_name="Selected states shipping fee"
    )
    shipping_fee_other = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("100.00"),
        verbose_name="Other states shipping fee"
    )
    shipping_local_states = models.CharField(
        max_length=255, default="Tamil Nadu, Kerala",
        verbose_name="States eligible for selected rate"
    )

    # Packing Cost Configuration
    packing_free_cans = models.PositiveIntegerField(
        default=6,
        verbose_name="Free packing cans threshold"
    )
    packing_cost_per_batch = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("20.00"),
        verbose_name="Packing cost per batch"
    )
    packing_batch_size = models.PositiveIntegerField(
        default=6,
        verbose_name="Cans per packing batch"
    )

    # GST / Tax Configuration
    gst_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("18.00"),
        verbose_name="GST Rate (%)"
    )

    updated_at = models.DateTimeField(auto_now=True)

    @property
    def whatsapp_link(self):
        digits = "".join(ch for ch in str(self.whatsapp_number) if ch.isdigit())
        if digits:
            return f"https://wa.me/{digits}"
        return "https://wa.me/918056838888"

    @property
    def phone_link(self):
        cleaned = str(self.support_phone).strip()
        if cleaned.startswith("+"):
            digits = "".join(ch for ch in cleaned[1:] if ch.isdigit())
            return f"tel:+{digits}"
        digits = "".join(ch for ch in cleaned if ch.isdigit())
        return f"tel:{digits}" if digits else "tel:+918056838888"

    def calculate_shipping_fee(self, state_name):
        if not state_name:
            return self.shipping_fee_local
        raw_state = state_name.strip().lower()
        local_list = [s.strip().lower() for s in self.shipping_local_states.split(",") if s.strip()]
        if any(ls in raw_state or raw_state in ls for ls in local_list):
            return self.shipping_fee_local
        return self.shipping_fee_other

    def calculate_packing_fee(self, quantity):
        try:
            qty = int(quantity)
        except (ValueError, TypeError):
            qty = 0
        if qty <= 0:
            return Decimal("0.00")
        if qty <= self.packing_free_cans:
            return Decimal("0.00")
        extra = qty - self.packing_free_cans
        batch_size = max(1, self.packing_batch_size)
        batches = (extra + batch_size - 1) // batch_size
        return Decimal(str(batches)) * self.packing_cost_per_batch

    def calculate_gst(self, subtotal):
        try:
            sub = Decimal(str(subtotal))
        except (ValueError, TypeError):
            sub = Decimal("0.00")
        rate = (self.gst_rate or Decimal("18.00")) / Decimal("100")
        return (sub * rate).quantize(Decimal("0.01"))

    def __str__(self):
        return "Store & Site Details"

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class ContactMessage(models.Model):
    name = models.CharField(max_length=150)
    email = models.EmailField()
    subject = models.CharField(max_length=200, default="General inquiry")
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Message from {self.name} - {self.subject}"


class WebsiteView(models.Model):
    """
    Tracks unique daily website views by client WiFi IP address and user.
    If a user visits or logs in multiple times from the same WiFi IP on the same day,
    it counts as ONE unique user view for that day, while recording their hit count,
    first seen time, last active time, and device details.
    """
    ip_address = models.CharField(max_length=64, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="website_views"
    )
    username_display = models.CharField(max_length=150, blank=True, default="Guest")
    user_email = models.CharField(max_length=254, blank=True, default="")
    date = models.DateField(default=timezone.localdate, db_index=True)
    first_visit = models.DateTimeField(auto_now_add=True)
    last_visit = models.DateTimeField(auto_now=True)
    view_count = models.PositiveIntegerField(default=1)
    last_page = models.CharField(max_length=255, blank=True, default="/")
    device = models.CharField(max_length=64, blank=True, default="Desktop")
    user_agent = models.CharField(max_length=255, blank=True, default="")
    session_key = models.CharField(max_length=64, blank=True, default="")

    class Meta:
        ordering = ["-last_visit"]
        constraints = [
            models.UniqueConstraint(fields=["date", "ip_address"], name="unique_daily_ip_view")
        ]

    def __str__(self):
        user_name = self.username_display or "Guest"
        return f"{self.ip_address} ({user_name}) on {self.date} - {self.view_count} hits"

    @classmethod
    def record_visit(cls, request):
        """
        Records a visit from the incoming request.
        Extracts real client IP (WiFi IP) and deduplicates for the day.
        """
        path = getattr(request, "path", "/") or "/"
        # Exclude static, media, internal tooling, and favicon
        if any(path.startswith(prefix) for prefix in [
            "/static/", "/media/", "/admin/", "/favicon.ico", "/__reload__", "/__debug__"
        ]):
            return None

        # Extract client IP (handles WiFi NAT, reverse proxies, Vercel)
        ip = "127.0.0.1"
        cf_ip = request.META.get("HTTP_CF_CONNECTING_IP")
        if cf_ip:
            ip = cf_ip.strip()
        else:
            x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
            if x_forwarded_for:
                ip = x_forwarded_for.split(",")[0].strip()
            elif request.META.get("HTTP_X_REAL_IP"):
                ip = request.META.get("HTTP_X_REAL_IP").strip()
            elif request.META.get("REMOTE_ADDR"):
                ip = request.META.get("REMOTE_ADDR").strip()

        if not ip:
            ip = "127.0.0.1"

        today = timezone.localdate()
        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        user_agent = (request.META.get("HTTP_USER_AGENT") or "")[:250]

        # Extract device & browser
        ua_lower = user_agent.lower()
        os_name = "Desktop"
        if "android" in ua_lower:
            os_name = "Android"
        elif "iphone" in ua_lower or "ipad" in ua_lower or "ios" in ua_lower:
            os_name = "iOS"
        elif "windows" in ua_lower:
            os_name = "Windows"
        elif "macintosh" in ua_lower or "mac os" in ua_lower:
            os_name = "Mac"
        elif "linux" in ua_lower:
            os_name = "Linux"

        browser_name = "Browser"
        if "chrome" in ua_lower and "edg" not in ua_lower and "opr" not in ua_lower:
            browser_name = "Chrome"
        elif "safari" in ua_lower and "chrome" not in ua_lower:
            browser_name = "Safari"
        elif "firefox" in ua_lower:
            browser_name = "Firefox"
        elif "edg" in ua_lower:
            browser_name = "Edge"
        elif "opr" in ua_lower or "opera" in ua_lower:
            browser_name = "Opera"

        device_str = f"{os_name} • {browser_name}"
        session_key = (
            request.session.session_key
            if hasattr(request, "session") and request.session.session_key
            else ""
        )

        try:
            record, created = cls.objects.get_or_create(
                date=today,
                ip_address=ip,
                defaults={
                    "user": user,
                    "username_display": user.username if user else "Guest",
                    "user_email": user.email if user else "",
                    "view_count": 1,
                    "last_page": path[:250],
                    "device": device_str,
                    "user_agent": user_agent,
                    "session_key": session_key or "",
                },
            )
            if not created:
                # User or device viewed again on the same day from the same WiFi IP
                fields_to_update = ["last_visit", "view_count", "last_page"]
                record.view_count += 1
                record.last_page = path[:250]
                record.last_visit = timezone.now()

                # If previously recorded as guest, but now user is authenticated, associate user
                if user and (not record.user or record.user != user):
                    record.user = user
                    record.username_display = user.username
                    record.user_email = user.email or ""
                    fields_to_update.extend(["user", "username_display", "user_email"])

                if device_str and record.device != device_str:
                    record.device = device_str
                    fields_to_update.append("device")

                record.save(update_fields=fields_to_update)

            return record
        except Exception:
            return None