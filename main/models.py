from django.db import models
from django.conf import settings
import uuid


class Product(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=8, decimal_places=2, default=90)
    volume = models.CharField(max_length=20, default="330 ml")
    image = models.CharField(max_length=255)
    available = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class DeliveryProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="delivery_profile",
        on_delete=models.CASCADE,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Delivery profile for {self.user.get_username()}"


class CustomerProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        related_name="customer_profile",
        on_delete=models.CASCADE,
    )
    phone = models.CharField(max_length=20, blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    def __str__(self):
        return f"Customer profile for {self.user.get_username()}"


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
    ]

    product = models.ForeignKey(Product, related_name="orders", on_delete=models.CASCADE)
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="orders",
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
    payment_reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    payment_event_id = models.CharField(max_length=100, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

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
                