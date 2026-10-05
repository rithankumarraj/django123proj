from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import Product


class AdminLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="Username or email",
        widget=forms.TextInput(attrs={"class": "login-input", "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"class": "login-input", "autocomplete": "current-password"}),
    )

    def clean(self):
        identity = self.cleaned_data.get("username", "").strip()
        if "@" in identity:
            users = get_user_model()._default_manager.filter(email__iexact=identity)
            if users.count() == 1:
                self.cleaned_data["username"] = users.get().get_username()
        return super().clean()


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "description", "price", "volume", "image", "available"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "volume": forms.TextInput(attrs={"class": "form-control"}),
            "image": forms.TextInput(attrs={"class": "form-control"}),
            "available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
