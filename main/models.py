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
        default="multiple_products",
    )
    applicable_categories = models.ManyToManyField(
        ProductCategory,
        blank=True,
        related_name="combo_offers",
        help_text="Selective categories this combo applies to. Leave empty for all categories.",
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
        default=Decimal("6.00"),
        help_text="Minimum order amount (default 6).",
    )
    min_quantity = models.PositiveIntegerField(
        default=6,
        help_text="Minimum items quantity required (default 6).",
    )
    min_distinct_products = models.PositiveIntegerField(
        default=6,
        help_text="Minimum distinct products required for assortment (default 6).",
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
    times_used = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    description = models.TextField(
        blank=True,
        default="Mix and match any 6 different cans to unlock the Cans of Assortment combo offer!",
    )
    badge_text = models.CharField(
        max_length=100,
        default="Cans of Assortment",
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
        if self.discount_type == "percentage":
            val = int(self.discount_value) if self.discount_value == int(self.discount_value) else self.discount_value
            cap_str = f" (Capped at ₹{self.max_discount_cap})" if self.max_discount_cap else ""
            return f"{val}% OFF{cap_str}"
        val = int(self.discount_value) if self.discount_value == int(self.discount_value) else self.discount_value
        return f"₹{val} OFF"

    @property
    def categories_display(self):
        cats = list(self.applicable_categories.all())
        if not cats:
            return "All Categories"
        return ", ".join(c.name for c in cats)

    @property
    def offer_type_display(self):
        return dict(self.OFFER_TYPE_CHOICES).get(self.offer_type, self.offer_type.replace("_", " ").title())

    @property
    def image_url(self):
        if self.image:
            try:
                return self.image.url
            except Exception:
                pass
        return "/static/main/images/combos/cans_of_assortment.jpg"

    def evaluate_cart(self, cart_items, subtotal=None):
        if not self.is_valid_status:
            return False, Decimal("0.00"), {}

        cats = list(self.applicable_categories.all())
        cat_slugs = {c.slug.lower() for c in cats}
        cat_names = {c.name.lower() for c in cats}

        eligible_items = []
        eligible_subtotal = Decimal("0.00")
        for it in cart_items:
            prod = it.get("product")
            if not prod:
                continue
            prod_cat = (getattr(prod, "category", "") or "").lower().strip()
            prod_cat_slug = (getattr(prod, "category_slug", "") or "").lower().strip()
            if (
                not cats
                or prod_cat in cat_slugs
                or prod_cat in cat_names
                or prod_cat_slug in cat_slugs
            ):
                eligible_items.append(it)
                qty = it.get("quantity", 1)
                price = getattr(prod, "price", Decimal("0.00"))
                eligible_subtotal += Decimal(str(price)) * int(qty)

        if not eligible_items:
            return False, Decimal("0.00"), {}

        total_eligible_qty = sum(it.get("quantity", 1) for it in eligible_items)
        distinct_eligible_count = len({it["product"].id for it in eligible_items})

        qualifies = False
        if self.offer_type == "multiple_products":
            if (
                total_eligible_qty >= self.min_quantity
                and distinct_eligible_count >= self.min_distinct_products
                and eligible_subtotal >= self.min_order_amount
            ):
                qualifies = True
        elif self.offer_type == "single_quantity":
            has_single_meet = any(it.get("quantity", 1) >= self.min_quantity for it in eligible_items)
            if (has_single_meet or total_eligible_qty >= self.min_quantity) and eligible_subtotal >= self.min_order_amount:
                qualifies = True
        elif self.offer_type == "price_based":
            if eligible_subtotal >= self.min_order_amount:
                qualifies = True

        if not qualifies:
            return False, Decimal("0.00"), {}

        if self.discount_type == "percentage":
            discount = (eligible_subtotal * (self.discount_value / Decimal("100"))).quantize(Decimal("0.01"))
            if self.max_discount_cap and self.max_discount_cap > Decimal("0.00"):
                discount = min(discount, self.max_discount_cap)
        else:
            discount = min(eligible_subtotal, self.discount_value)

        discount = max(Decimal("0.00"), discount)
        return True, discount, {
            "combo_id": self.id,
            "name": self.name,
            "badge_text": self.badge_text or self.name,
            "distinct_count": distinct_eligible_count,
            "total_qty": total_eligible_qty,
            "eligible_product_ids": [it["product"].id for it in eligible_items],
        }


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

    def save(self, *args, **kwargs):
        if self.status == "returned":
            self.status = "cancelled"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Order #{self.pk} - {self.status}"


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