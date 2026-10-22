

# Register your models here.
from django.contrib import admin
from .models import DeliveryProfile, Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "price",
        "volume",
        "available",
    )

    list_filter = (
        "available",
    )

    search_fields = (
        "name",
    )


@admin.register(DeliveryProfile)
class DeliveryProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at")
    search_fields = ("user__username", "user__email")