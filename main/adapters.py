from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.http import HttpResponseForbidden


class AdminGoogleAccountAdapter(DefaultSocialAccountAdapter):
    def _is_authorized_admin(self, sociallogin):
        extra_data = sociallogin.account.extra_data
        email = str(extra_data.get("email", "")).strip().lower()
        return (
            bool(settings.GOOGLE_ADMIN_EMAIL)
            and email == settings.GOOGLE_ADMIN_EMAIL
            and (extra_data.get("email_verified") is True or extra_data.get("verified_email") is True)
        )

    def pre_social_login(self, request, sociallogin):
        if not self._is_authorized_admin(sociallogin):
            raise ImmediateHttpResponse(
                HttpResponseForbidden("This Google account is not authorized for admin access.")
            )

        if sociallogin.is_existing and not sociallogin.user.is_staff:
            sociallogin.user.is_staff = True
            sociallogin.user.save(update_fields=["is_staff"])

    def is_open_for_signup(self, request, sociallogin):
        return self._is_authorized_admin(sociallogin)

    def save_user(self, request, sociallogin, form=None):
        if not self._is_authorized_admin(sociallogin):
            raise ImmediateHttpResponse(
                HttpResponseForbidden("This Google account is not authorized for admin access.")
            )

        user = super().save_user(request, sociallogin, form)
        user.is_staff = True
        user.save(update_fields=["is_staff"])
        return user
