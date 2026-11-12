from django.utils import timezone
from .models import ComboOffer, ContactMessage, Coupon, DeliveryProfile, Product, SiteDetails, WebsiteView
from .views import CART_SESSION_KEY, WISHLIST_SESSION_KEY, _cart_items


def navbar_context(request):
    """
    Context processor to provide common variables (cart_count, wishlist_count,
    is_delivery_user, site_details, unread_messages_count, and admin counts) across all templates.
    """
    cart_count = 0
    wishlist_count = 0
    is_delivery_user = False
    unread_messages_count = 0
    total_coupons_count = 0
    total_combos_count = 0
    today_views_count = 0
    site_details = None

    try:
        site_details = SiteDetails.get_solo()
    except Exception:
        site_details = None

    if hasattr(request, "session"):
        try:
            cart_count = sum(item["quantity"] for item in _cart_items(request))
        except Exception:
            cart_count = 0

        try:
            wishlist = request.session.get(WISHLIST_SESSION_KEY, [])
            if isinstance(wishlist, list):
                product_ids = []
                for raw_id in wishlist:
                    try:
                        pid = int(raw_id)
                        if pid > 0 and pid not in product_ids:
                            product_ids.append(pid)
                    except (TypeError, ValueError):
                        continue
                if product_ids:
                    wishlist_count = Product.objects.filter(id__in=product_ids, available=True).count()
        except Exception:
            wishlist_count = 0

    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        try:
            is_delivery_user = DeliveryProfile.objects.filter(user=user, is_approved=True).exists()
        except Exception:
            is_delivery_user = False

        if getattr(user, "is_staff", False):
            try:
                unread_messages_count = ContactMessage.objects.filter(is_read=False).count()
            except Exception:
                unread_messages_count = 0
            try:
                total_coupons_count = Coupon.objects.count()
            except Exception:
                total_coupons_count = 0
            try:
                total_combos_count = ComboOffer.objects.count()
            except Exception:
                total_combos_count = 0
            try:
                today_views_count = WebsiteView.objects.filter(date=timezone.localdate()).count()
            except Exception:
                today_views_count = 0

    return {
        "cart_count": cart_count,
        "wishlist_count": wishlist_count,
        "is_delivery_user": is_delivery_user,
        "unread_messages_count": unread_messages_count,
        "total_coupons_count": total_coupons_count,
        "total_combos_count": total_combos_count,
        "today_views_count": today_views_count,
        "site_details": site_details,
        "details": site_details,
    }

