import os
import re
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.core.files.storage import default_storage
from django.utils.text import slugify

from .models import CustomerAddress, CustomerProfile, INDIAN_STATES, Product, ProductCategory, SiteDetails


class CustomerAccountForm(forms.ModelForm):
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={"autocomplete": "email"}),
    )

    class Meta:
        model = get_user_model()
        fields = ("username", "email", "first_name", "last_name")
        widgets = {
            "username": forms.TextInput(attrs={"autocomplete": "username"}),
            "email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
        }

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip()
        if email:
            user_model = get_user_model()
            existing = user_model.objects.filter(email__iexact=email).exclude(pk=self.instance.pk)
            if existing.exists():
                raise forms.ValidationError("An account with this email address already exists.")
        return email


class CustomerProfileForm(forms.ModelForm):
    class Meta:
        model = CustomerProfile
        fields = ("avatar", "phone", "address", "city", "state", "postal_code")
        widgets = {
            "avatar": forms.FileInput(attrs={"accept": "image/*", "id": "id_profile_avatar"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
            "address": forms.TextInput(attrs={"autocomplete": "street-address"}),
            "city": forms.TextInput(attrs={"autocomplete": "address-level2"}),
            "state": forms.TextInput(attrs={"autocomplete": "address-level1"}),
            "postal_code": forms.TextInput(attrs={"autocomplete": "postal-code"}),
        }


class CustomerAddressForm(forms.ModelForm):
    class Meta:
        model = CustomerAddress
        fields = ("full_name", "phone", "address", "city", "state", "postal_code", "is_default")
        widgets = {
            "full_name": forms.TextInput(attrs={"autocomplete": "name", "placeholder": "e.g. Home, Office, or Name"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel", "placeholder": "+91 98765 43210"}),
            "address": forms.TextInput(attrs={"autocomplete": "street-address", "placeholder": "Flat / House no, Street, Area"}),
            "city": forms.TextInput(attrs={"autocomplete": "address-level2", "placeholder": "City"}),
            "state": forms.TextInput(attrs={"autocomplete": "address-level1", "placeholder": "State"}),
            "postal_code": forms.TextInput(attrs={"autocomplete": "postal-code", "placeholder": "PIN code"}),
            "is_default": forms.CheckboxInput(),
        }


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
            elif users.count() > 1:
                self.cleaned_data["username"] = users.first().get_username()
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
    email = forms.EmailField(max_length=254)
    phone = forms.CharField(min_length=7, max_length=25)
    address = forms.CharField(max_length=255)
    city = forms.CharField(max_length=100)
    state = forms.CharField(max_length=100)
    postal_code = forms.CharField(max_length=20, label="ZIP / postal code")

    def clean_phone(self):
        raw = self.cleaned_data.get("phone", "").strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 12 and digits.startswith("91"):
            ten_digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            ten_digits = digits[1:]
        elif len(digits) == 10:
            ten_digits = digits
        else:
            raise forms.ValidationError("Please enter a valid 10-digit mobile number.")
        if raw.startswith("+91"):
            return raw
        return f"+91 {ten_digits}"


class ShippingChargesForm(forms.ModelForm):
    class Meta:
        model = SiteDetails
        fields = [
            "shipping_fee_local",
            "shipping_fee_other",
            "shipping_local_states",
        ]
        labels = {
            "shipping_fee_local": "Selected States Shipping Fee (₹)",
            "shipping_fee_other": "All Other States Shipping Fee (₹)",
            "shipping_local_states": "Selected States / Regions",
        }
        widgets = {
            "shipping_fee_local": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "shipping_fee_other": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "shipping_local_states": forms.HiddenInput(attrs={"id": "id_shipping_local_states"}),
        }


class PackingChargesForm(forms.ModelForm):
    class Meta:
        model = SiteDetails
        fields = [
            "packing_free_cans",
            "packing_cost_per_batch",
            "packing_batch_size",
        ]
        labels = {
            "packing_free_cans": "Free Packing Cans Threshold",
            "packing_cost_per_batch": "Packing Cost Per Additional Batch (₹)",
            "packing_batch_size": "Cans Per Additional Packing Batch",
        }
        widgets = {
            "packing_free_cans": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "packing_cost_per_batch": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "packing_batch_size": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "1"}),
        }


class ShippingSettingsForm(forms.ModelForm):
    class Meta:
        model = SiteDetails
        fields = [
            "shipping_fee_local",
            "shipping_fee_other",
            "shipping_local_states",
            "packing_free_cans",
            "packing_cost_per_batch",
            "packing_batch_size",
        ]
        labels = {
            "shipping_fee_local": "Selected States Shipping Fee (₹)",
            "shipping_fee_other": "All Other States Shipping Fee (₹)",
            "shipping_local_states": "Selected States / Regions",
            "packing_free_cans": "Free Packing Cans Threshold",
            "packing_cost_per_batch": "Packing Cost Per Additional Batch (₹)",
            "packing_batch_size": "Cans Per Additional Packing Batch",
        }
        widgets = {
            "shipping_fee_local": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "shipping_fee_other": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "shipping_local_states": forms.HiddenInput(attrs={"id": "id_shipping_local_states"}),
            "packing_free_cans": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "packing_cost_per_batch": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "0"}),
            "packing_batch_size": forms.NumberInput(attrs={"class": "form-control", "step": "1", "min": "1"}),
        }


class ProductForm(forms.ModelForm):
    image_file = forms.ImageField(
        required=False,
        label="Upload Image",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": "image/*", "id": "id_image_file"}),
    )
    new_category = forms.CharField(
        required=False,
        max_length=60,
        label="New Category Name",
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "id": "id_new_category",
            "placeholder": "Enter new category name (e.g. Sparkling Water, Juice)",
            "autocomplete": "off",
        }),
    )

    class Meta:
        model = Product
        fields = ["name", "category", "description", "price", "volume", "image", "available"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "category": forms.Select(attrs={"class": "form-control", "id": "id_category"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "volume": forms.TextInput(attrs={"class": "form-control"}),
            "image": forms.TextInput(attrs={"class": "form-control", "id": "id_image_path", "placeholder": "main/images/cola.png"}),
            "available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [
            ("cola", "Cola"),
            ("energy_drink", "Energy Drink"),
            ("others", "Others"),
        ]
        extra_cats = ProductCategory.objects.exclude(slug__in=["cola", "energy_drink", "others"]).order_by("name")
        for ec in extra_cats:
            choices.append((ec.slug, ec.name))
        existing_slugs = {c[0] for c in choices}
        if self.instance and self.instance.pk and self.instance.category and self.instance.category not in existing_slugs:
            choices.append((self.instance.category, self.instance.category_display))
        choices.append(("__new__", "+ Add New Category..."))
        self.fields["category"].choices = choices
        self.fields["image"].required = False

    def clean(self):
        cleaned_data = super().clean()
        category = (cleaned_data.get("category") or "").strip()
        new_category = (cleaned_data.get("new_category") or "").strip()

        if category == "__new__" or new_category:
            cat_name = new_category or category
            if not cat_name or cat_name == "__new__":
                self.add_error("new_category", "Please enter a name for the new category.")
            else:
                clean_name = cat_name.strip()
                slug = slugify(clean_name).replace("-", "_")
                if not slug:
                    slug = "custom_category"
                cat_obj, _ = ProductCategory.objects.get_or_create(
                    slug=slug,
                    defaults={"name": clean_name.title()}
                )
                cleaned_data["category"] = cat_obj.slug
        elif category:
            if category not in ["cola", "energy_drink", "others"]:
                slug = slugify(category).replace("-", "_")
                cat_obj, _ = ProductCategory.objects.get_or_create(
                    slug=slug,
                    defaults={"name": category.replace("_", " ").title()}
                )
                cleaned_data["category"] = cat_obj.slug

        image_file = cleaned_data.get("image_file")
        image_path = (cleaned_data.get("image") or "").strip()
        if not self.instance.pk and not image_file and not image_path:
            cleaned_data["image"] = "main/images/cola.png"

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        image_file = self.cleaned_data.get("image_file")
        if image_file:
            base_name, ext = os.path.splitext(image_file.name)
            safe_name = f"{slugify(base_name) or 'product'}{ext.lower()}"
            saved_path = default_storage.save(f"products/{safe_name}", image_file)
            instance.image = f"/media/{saved_path}"
        elif self.cleaned_data.get("image"):
            instance.image = self.cleaned_data["image"].strip()
        elif not instance.image:
            instance.image = "main/images/cola.png"

        if commit:
            instance.save()
        return instance


class AboutDetailsForm(forms.ModelForm):
    class Meta:
        model = SiteDetails
        fields = [
            "about_kicker",
            "about_title",
            "about_lead",
            "about_note",
            "about_action_text",
            "about_action_url",
        ]
        labels = {
            "about_kicker": "Section Kicker / Subtitle",
            "about_title": "Page Heading / Title",
            "about_lead": "Lead Paragraph / Mission",
            "about_note": "Brand Story / Secondary Note",
            "about_action_text": "Action Button Label",
            "about_action_url": "Action Button Destination",
        }
        widgets = {
            "about_kicker": forms.TextInput(attrs={"class": "form-control"}),
            "about_title": forms.TextInput(attrs={"class": "form-control"}),
            "about_lead": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "about_note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "about_action_text": forms.TextInput(attrs={"class": "form-control"}),
            "about_action_url": forms.TextInput(attrs={"class": "form-control"}),
        }


class ContactDetailsForm(forms.ModelForm):
    class Meta:
        model = SiteDetails
        fields = [
            "contact_kicker",
            "contact_title",
            "contact_lead",
            "support_email",
            "support_phone",
            "whatsapp_number",
            "operating_hours",
        ]
        labels = {
            "contact_kicker": "Section Kicker",
            "contact_title": "Contact Heading",
            "contact_lead": "Contact Intro / Lead text",
            "support_email": "Customer Support Email",
            "support_phone": "Customer Support Phone",
            "whatsapp_number": "WhatsApp Hotline Number",
            "operating_hours": "Operating & Support Hours",
        }
        widgets = {
            "contact_kicker": forms.TextInput(attrs={"class": "form-control"}),
            "contact_title": forms.TextInput(attrs={"class": "form-control"}),
            "contact_lead": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "support_email": forms.TextInput(attrs={"class": "form-control"}),
            "support_phone": forms.TextInput(attrs={"class": "form-control"}),
            "whatsapp_number": forms.TextInput(attrs={"class": "form-control"}),
            "operating_hours": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }

