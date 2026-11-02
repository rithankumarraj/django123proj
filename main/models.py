from decimal import Decimal
from django.db import models
from django.conf import settings
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
    available = models.BooleanField(default=True)

    def __str__(self):
        return self.name

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


class Order(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ("pending", "Payment pending"),
        ("paid", "Paid"),
        ("failed", "Payment failed"),
    ]

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("packed", "Packed"),
        ("out_for_delivery", "Out for delivery"),
        ("delivered", "Delivered"),
        ("returned", "Returned"),
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
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    packing_fee = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    gst_amount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    payment_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payment_event_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    @property
    def items_subtotal(self):
        sub = self.total_amount - self.shipping_fee - self.packing_fee - self.gst_amount
        return sub if sub > 0 else self.total_amount

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