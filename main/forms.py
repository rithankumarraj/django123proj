from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from .models import Product


class EmailAuthenticationForm(AuthenticationForm):
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


class AdminLoginForm(EmailAuthenticationForm):
    pass


class CustomerRegistrationForm(UserCreationForm):
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={"class": "login-input", "autocomplete": "email"})
    )
    first_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "login-input", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        widget=forms.TextInput(attrs={"class": "login-input", "autocomplete": "family-name"}),
    )

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email", "first_name", "last_name")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].widget.attrs.update(
            {"class": "login-input", "autocomplete": "username"}
        )
        self.fields["password1"].widget.attrs.update(
            {"class": "login-input", "autocomplete": "new-password"}
        )
        self.fields["password2"].widget.attrs.update(
            {"class": "login-input", "autocomplete": "new-password"}
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if get_user_model()._default_manager.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class DeliveryAccountForm(UserCreationForm):
    email = forms.EmailField()

    class Meta(UserCreationForm.Meta):
        fields = ("username", "email", "first_name", "last_name")

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if get_user_model()._default_manager.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email


class DeliveryAddressForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    address = forms.CharField(max_length=255)
    city = forms.CharField(max_length=100)
    state = forms.CharField(max_length=100)
    postal_code = forms.CharField(max_length=20, label="ZIP / postal code")


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
