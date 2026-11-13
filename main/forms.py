from decimal import Decimal
import os
import re
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.core.files.storage import default_storage
from django.utils.text import slugify

from .models import (
    ComboOffer,
    Coupon,
    CustomerAddress,
    CustomerProfile,
    DeliveryProfile,
    INDIAN_STATES,
    Product,
    ProductCategory,
    SiteDetails,
)


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
    email = forms.EmailField(required=True)
    phone = forms.CharField(required=False, max_length=20, label="Phone Number", widget=forms.TextInput(attrs={"placeholder": "+91 98765 43210"}))
    address = forms.CharField(required=False, max_length=255, label="Residential Address", widget=forms.TextInput(attrs={"placeholder": "Door / Flat No., Street, Area, City"}))
    aadhar_number = forms.CharField(required=False, max_length=30, label="Aadhaar Number", widget=forms.TextInput(attrs={"placeholder": "12-digit Aadhaar"}))
    driving_license = forms.CharField(required=False, max_length=50, label="Driving Licence", widget=forms.TextInput(attrs={"placeholder": "DL number"}))
    vehicle_type = forms.ChoiceField(choices=DeliveryProfile.VEHICLE_CHOICES, required=False, initial="bike", label="Vehicle Type")
    vehicle_number = forms.CharField(required=False, max_length=40, label="Vehicle Registration Number", widget=forms.TextInput(attrs={"placeholder": "e.g. TN 58 AB 1234"}))
    serviceable_pincodes = forms.CharField(
        required=False,
        label="Serviceable PIN Codes",
        widget=forms.TextInput(attrs={"placeholder": "e.g. 625018, 625001"}),
        help_text="Comma-separated PIN codes this driver can deliver to",
    )
    is_approved = forms.BooleanField(required=False, initial=True, label="Approve Immediately")

    class Meta(UserCreationForm.Meta):
        fields = (
            "username",
            "email",
            "first_name",
            "last_name",
            "phone",
            "address",
            "aadhar_number",
            "driving_license",
            "vehicle_type",
            "vehicle_number",
            "serviceable_pincodes",
            "is_approved",
        )

    def clean_email(self):
        email = self.cleaned_data["email"].strip()
        if get_user_model()._default_manager.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email already exists.")
        return email

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            dp, _ = DeliveryProfile.objects.get_or_create(user=user)
            dp.phone = self.cleaned_data.get("phone", "")
            dp.address = self.cleaned_data.get("address", "")
            dp.aadhar_number = self.cleaned_data.get("aadhar_number", "")
            dp.driving_license = self.cleaned_data.get("driving_license", "")
            dp.vehicle_type = self.cleaned_data.get("vehicle_type", "bike")
            dp.vehicle_number = self.cleaned_data.get("vehicle_number", "")
            dp.serviceable_pincodes = self.cleaned_data.get("serviceable_pincodes", "")
            dp.is_approved = self.cleaned_data.get("is_approved", True)
            dp.status = "approved" if dp.is_approved else "pending"
            dp.save()
        return user


class DeliveryPartnerApplicationForm(forms.Form):
    first_name = forms.CharField(
        max_length=100,
        label="First Name",
        widget=forms.TextInput(attrs={"placeholder": "First Name", "autocomplete": "given-name"}),
    )
    last_name = forms.CharField(
        max_length=100,
        required=False,
        label="Last Name",
        widget=forms.TextInput(attrs={"placeholder": "Last Name", "autocomplete": "family-name"}),
    )
    username = forms.CharField(
        max_length=150,
        label="Choose a Username",
        widget=forms.TextInput(attrs={"placeholder": "e.g. rahul_delivery", "autocomplete": "username"}),
    )
    email = forms.EmailField(
        label="Email Address",
        widget=forms.EmailInput(attrs={"placeholder": "you@example.com", "autocomplete": "email"}),
    )
    phone = forms.CharField(
        max_length=20,
        label="Mobile Phone Number",
        widget=forms.TextInput(attrs={"placeholder": "+91 98765 43210", "autocomplete": "tel"}),
    )
    address = forms.CharField(
        max_length=255,
        label="Full Residential Address",
        widget=forms.TextInput(attrs={"placeholder": "Door / Flat No., Street, Area, City"}),
        help_text="Your residential address for partner verification.",
    )
    aadhar_number = forms.CharField(
        max_length=25,
        label="Aadhaar Card Number",
        widget=forms.TextInput(attrs={"placeholder": "12-digit Aadhaar (e.g. 1234 5678 9012)"}),
        help_text="Government issued 12-digit Aadhaar number for identity verification.",
    )
    driving_license = forms.CharField(
        max_length=50,
        label="Driving Licence Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g. TN-58-2022-0001234"}),
        help_text="Valid driving licence for operating your delivery vehicle.",
    )
    vehicle_type = forms.ChoiceField(
        choices=DeliveryProfile.VEHICLE_CHOICES,
        initial="bike",
        label="Vehicle Type",
    )
    vehicle_number = forms.CharField(
        max_length=40,
        label="Vehicle Registration Number",
        widget=forms.TextInput(attrs={"placeholder": "e.g. TN 58 AB 1234"}),
        help_text="Vehicle plate / registration number.",
    )
    serviceable_pincodes = forms.CharField(
        label="PIN Codes You Can Deliver To",
        widget=forms.TextInput(attrs={"placeholder": "e.g. 625018, 625001, 625020"}),
        help_text="Comma-separated 6-digit postal codes. You will only see and pick orders for these PIN codes.",
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Create secure password"}),
        min_length=4,
        label="Password",
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Re-enter password"}),
        min_length=4,
        label="Confirm Password",
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        user_model = get_user_model()
        if user_model.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("This username is already taken. Please choose another.")
        return username

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        user_model = get_user_model()
        if user_model.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email

    def clean_phone(self):
        raw = self.cleaned_data.get("phone", "").strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) < 10:
            raise forms.ValidationError("Please enter a valid 10-digit mobile number.")
        return raw

    def clean_aadhar_number(self):
        raw = self.cleaned_data.get("aadhar_number", "").strip()
        digits = re.sub(r"\D", "", raw)
        if len(digits) != 12:
            raise forms.ValidationError("Aadhaar number must contain exactly 12 digits.")
        return raw

    def clean_serviceable_pincodes(self):
        raw = self.cleaned_data.get("serviceable_pincodes", "").strip()
        codes = re.findall(r"\b\d{6}\b", raw)
        if not codes:
            codes = [c.strip() for c in re.split(r"[,;\s]+", raw) if c.strip()]
        if not codes:
            raise forms.ValidationError("Please enter at least one valid 6-digit PIN code (e.g. 625018).")
        return ", ".join(sorted(list(dict.fromkeys(codes))))

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password")
        p2 = cleaned_data.get("password_confirm")
        if p1 and p2 and p1 != p2:
            self.add_error("password_confirm", "Passwords do not match.")
        return cleaned_data


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
        fields = ["name", "category", "description", "cost_price", "price", "volume", "image", "available_pincodes", "available"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Fresh Lime"}),
            "category": forms.Select(attrs={"class": "form-control", "id": "id_category"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4, "placeholder": "Enter product description..."}),
            "cost_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "id": "id_cost_price", "placeholder": "60.00"}),
            "price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "id": "id_price", "placeholder": "90.00"}),
            "volume": forms.TextInput(attrs={"class": "form-control", "placeholder": "330 ml"}),
            "image": forms.TextInput(attrs={"class": "form-control", "id": "id_image_path", "placeholder": "main/images/cola.png"}),
            "available_pincodes": forms.Textarea(attrs={"class": "form-control", "id": "id_available_pincodes", "rows": 3, "placeholder": "e.g. 625018, 625001 (leave empty for all PIN codes, or enter 200+ PINs)"}),
            "available": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            if not self.initial.get("cost_price"):
                self.initial["cost_price"] = Decimal("60.00")
            if not self.initial.get("price"):
                self.initial["price"] = Decimal("90.00")
            if not self.initial.get("volume"):
                self.initial["volume"] = "330 ml"
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
        self.fields["cost_price"].required = False

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

        cost_price = cleaned_data.get("cost_price")
        if cost_price is None or cost_price == "":
            cleaned_data["cost_price"] = Decimal("60.00")

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


class DailyPromoPopupForm(forms.ModelForm):
    class Meta:
        model = SiteDetails
        fields = [
            "popup_enabled",
            "popup_offer_type",
            "popup_combo",
            "popup_coupon",
            "popup_title",
            "popup_message",
            "popup_badge_text",
        ]
        labels = {
            "popup_enabled": "Enable Daily Promotional Popup",
            "popup_offer_type": "Featured Offer Type",
            "popup_combo": "Featured Combo Offer",
            "popup_coupon": "Featured Coupon Code",
            "popup_title": "Custom Heading",
            "popup_message": "Custom Description",
            "popup_badge_text": "Badge / Tag Text",
        }
        widgets = {
            "popup_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "popup_offer_type": forms.Select(attrs={"class": "form-control"}),
            "popup_combo": forms.Select(attrs={"class": "form-control"}),
            "popup_coupon": forms.Select(attrs={"class": "form-control"}),
            "popup_title": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. Special Deal of the Day!"}),
            "popup_message": forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Leave empty to use the offer's default description"}),
            "popup_badge_text": forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g. TODAY'S SPECIAL"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["popup_combo"].queryset = ComboOffer.objects.filter(is_active=True).order_by("-created_at")
        self.fields["popup_coupon"].queryset = Coupon.objects.filter(is_active=True).order_by("-created_at")
        self.fields["popup_combo"].required = False
        self.fields["popup_coupon"].required = False
        self.fields["popup_title"].required = False
        self.fields["popup_message"].required = False
        self.fields["popup_badge_text"].required = False


class CouponForm(forms.ModelForm):
    applicable_categories = forms.ModelMultipleChoiceField(
        queryset=ProductCategory.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "category-checkbox"}),
        help_text="Select specific categories or leave unselected for all categories.",
    )

    class Meta:
        model = Coupon
        fields = [
            "code",
            "discount_type",
            "discount_value",
            "min_order_amount",
            "usage_limit",
            "expire_date",
            "applicable_categories",
            "is_active",
        ]
        labels = {
            "code": "Coupon Code",
            "discount_type": "Discount Type",
            "discount_value": "Discount Value",
            "min_order_amount": "Minimum Order Amount (₹)",
            "usage_limit": "Usage Limit",
            "expire_date": "Expiry Date",
            "applicable_categories": "Selective Categories",
            "is_active": "Coupon is Active",
        }
        widgets = {
            "code": forms.TextInput(attrs={
                "class": "form-control",
                "id": "id_coupon_code",
                "placeholder": "e.g. SUMMER20",
                "style": "text-transform: uppercase; font-family: monospace; font-weight: 700; letter-spacing: 0.05em;",
                "required": True,
            }),
            "discount_type": forms.Select(attrs={
                "class": "form-control",
                "id": "id_coupon_discount_type",
                "required": True,
            }),
            "discount_value": forms.NumberInput(attrs={
                "class": "form-control",
                "id": "id_coupon_discount_value",
                "step": "0.01",
                "min": "0.01",
                "placeholder": "e.g. 20 for 20% or 50 for ₹50",
                "required": True,
            }),
            "min_order_amount": forms.NumberInput(attrs={
                "class": "form-control",
                "id": "id_coupon_min_order",
                "step": "0.01",
                "min": "0",
                "placeholder": "0.00",
            }),
            "usage_limit": forms.NumberInput(attrs={
                "class": "form-control",
                "id": "id_coupon_usage_limit",
                "min": "1",
                "placeholder": "Leave empty for unlimited",
            }),
            "expire_date": forms.DateInput(attrs={
                "class": "form-control",
                "id": "id_coupon_expire_date",
                "type": "date",
            }),
            "is_active": forms.CheckboxInput(attrs={
                "class": "form-check-input",
                "id": "id_coupon_is_active",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for slug, name in [("cola", "Cola"), ("energy_drink", "Energy Drink"), ("others", "Others")]:
            ProductCategory.objects.get_or_create(slug=slug, defaults={"name": name})
        self.fields["applicable_categories"].queryset = ProductCategory.objects.all().order_by("name")
        if not self.instance.pk and "is_active" in self.fields:
            self.fields["is_active"].initial = True

    def clean_code(self):
        code = self.cleaned_data.get("code", "").strip().upper()
        if not code:
            raise forms.ValidationError("Coupon code is required.")
        qs = Coupon.objects.filter(code__iexact=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Coupon code '{code}' already exists.")
        return code

    def clean(self):
        cleaned_data = super().clean()
        dtype = cleaned_data.get("discount_type")
        dval = cleaned_data.get("discount_value")
        if dtype == "percentage" and dval is not None:
            if dval > 100:
                self.add_error("discount_value", "Percentage discount cannot exceed 100%.")
            if dval <= 0:
                self.add_error("discount_value", "Discount value must be greater than 0.")
        elif dtype == "fixed" and dval is not None:
            if dval <= 0:
                self.add_error("discount_value", "Discount value must be greater than 0.")
        return cleaned_data


class ComboOfferForm(forms.ModelForm):
    class Meta:
        model = ComboOffer
        fields = [
            "name",
            "image",
            "discount_type",
            "discount_value",
            "max_discount_cap",
            "usage_limit",
            "expire_date",
            "show_in_announcement",
            "announcement_text",
            "description",
            "is_active",
        ]
        labels = {
            "name": "Combo Bundle Name",
            "image": "Combo Pack Image",
            "discount_type": "Discount Type",
            "discount_value": "Discount Value",
            "max_discount_cap": "Max Discount CAP (₹)",
            "usage_limit": "Usage Limit",
            "expire_date": "Expiry Date",
            "show_in_announcement": "Show in Announcement Bar",
            "announcement_text": "Announcement Banner Text",
            "description": "Offer Description",
            "is_active": "Offer is Active",
        }
        widgets = {
            "name": forms.TextInput(attrs={
                "class": "form-control",
                "id": "id_combo_name",
                "placeholder": "e.g. Lime Blast, Cans of Assortment",
                "required": True,
            }),
            "image": forms.FileInput(attrs={
                "class": "form-control",
                "id": "id_combo_image",
                "accept": "image/*",
            }),
            "discount_type": forms.Select(attrs={
                "class": "form-control",
                "id": "id_combo_discount_type",
                "required": True,
            }),
            "discount_value": forms.NumberInput(attrs={
                "class": "form-control",
                "id": "id_combo_discount_value",
                "step": "0.01",
                "min": "0.01",
                "placeholder": "e.g. 15 for 15% or 50 for ₹50",
                "required": True,
            }),
            "max_discount_cap": forms.NumberInput(attrs={
                "class": "form-control",
                "id": "id_combo_max_cap",
                "step": "0.01",
                "min": "0",
                "placeholder": "e.g. 100.00 (optional)",
            }),
            "usage_limit": forms.NumberInput(attrs={
                "class": "form-control",
                "id": "id_combo_usage_limit",
                "min": "1",
                "placeholder": "Leave empty for unlimited",
            }),
            "expire_date": forms.DateInput(attrs={
                "class": "form-control",
                "id": "id_combo_expire_date",
                "type": "date",
            }),
            "description": forms.Textarea(attrs={
                "class": "form-control",
                "id": "id_combo_description",
                "rows": 2,
                "placeholder": "e.g. Mix and match our signature flavours for the ultimate tasting experience!",
            }),
            "is_active": forms.CheckboxInput(attrs={
                "class": "form-check-input",
                "id": "id_combo_is_active",
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            if "is_active" in self.fields:
                self.fields["is_active"].initial = True

    def clean_name(self):
        name = self.cleaned_data.get("name", "").strip()
        if not name:
            raise forms.ValidationError("Combo name is required.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        dtype = cleaned_data.get("discount_type")
        dval = cleaned_data.get("discount_value")
        if dtype == "percentage" and dval is not None:
            if dval > 100:
                self.add_error("discount_value", "Percentage discount cannot exceed 100%.")
            if dval <= 0:
                self.add_error("discount_value", "Discount value must be greater than 0.")
        elif dtype == "fixed" and dval is not None:
            if dval <= 0:
                self.add_error("discount_value", "Discount value must be greater than 0.")
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.offer_type = "bundle"
        uploaded = self.cleaned_data.get("image")
        if uploaded:
            try:
                uploaded.seek(0)
                data = uploaded.read()
                if data:
                    import base64
                    mime = getattr(uploaded, "content_type", "image/png") or "image/png"
                    instance.image_data_url = f"data:{mime};base64,{base64.b64encode(data).decode('utf-8')}"
            except Exception:
                pass
        if commit:
            instance.save()
            self.save_m2m()
        return instance

