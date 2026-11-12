from django.utils import timezone
from .models import WebsiteView


class WebsiteViewTrackerMiddleware:
    """
    Middleware that records daily unique visitor views per client WiFi IP.
    Multiple visits or logins from the same WiFi IP on the same day are
    deduplicated and recorded as 1 unique user view for that day.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Record view on successful GET and POST responses
        if request.method in ("GET", "POST") and response.status_code < 400:
            try:
                WebsiteView.record_visit(request)
            except Exception:
                # Never allow tracking failures to impact the user experience
                pass

        return response

