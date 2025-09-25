from decimal import Decimal
from django import forms
from django.contrib.auth.models import User, Group, Permission

from .models import (
    Product, Category, Supplier, Customer,
    Purchase, Sale, SiteSetting
)

# ---------------------------
# Auth / Security Forms
# ---------------------------

class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "autocomplete": "new-password",
            "placeholder": "Set a password"
        }),
        label="Password"
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "autocomplete": "new-password",
            "placeholder": "Confirm password"
        }),
        label="Confirm Password"
    )
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.order_by('name'),
        required=False,
        widget=forms.SelectMultiple(attrs={
            "class": "form-select js-enhance-select",
            "multiple": "multiple",
            "data-placeholder": "Assign groups/roles",
            "data-max-items": "50",
        }),
        label="Groups / Roles",
        help_text="Select one or more roles for this user."
    )
    is_staff = forms.BooleanField(initial=True, required=False, label="Staff access")
    is_active = forms.BooleanField(initial=True, required=False, label="Active")

    class Meta:
        model = User
        fields = ['username', 'email', 'is_staff', 'is_active', 'groups']
        widgets = {
            'username': forms.TextInput(attrs={
                "class": "form-control",
                "autocomplete": "username",
                "placeholder": "Login username"
            }),
            'email': forms.EmailInput(attrs={
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "name@example.com"
            }),
        }

    def clean(self):
        c = super().clean()
        if c.get('password1') != c.get('password2'):
            self.add_error('password2', "Passwords do not match.")
        return c

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
            self.save_m2m()
            user.groups.set(self.cleaned_data.get('groups', []))
        return user


class UserEditForm(forms.ModelForm):
    password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "autocomplete": "new-password",
            "placeholder": "New password (optional)"
        }),
        required=False, label="New Password"
    )
    password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "autocomplete": "new-password",
            "placeholder": "Confirm new password"
        }),
        required=False, label="Confirm New Password"
    )
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.order_by('name'),
        required=False,
        widget=forms.SelectMultiple(attrs={
            "class": "form-select js-enhance-select",
            "multiple": "multiple",
            "data-placeholder": "Assign groups/roles",
            "data-max-items": "50",
        }),
        label="Groups / Roles"
    )
    is_staff = forms.BooleanField(required=False, label="Staff access")
    is_active = forms.BooleanField(required=False, label="Active")

    class Meta:
        model = User
        fields = ['email', 'is_staff', 'is_active', 'groups']
        widgets = {
            'email': forms.EmailInput(attrs={
                "class": "form-control",
                "autocomplete": "email",
                "placeholder": "name@example.com"
            }),
        }

    def clean(self):
        c = super().clean()
        p1, p2 = c.get('password1'), c.get('password2')
        if p1 or p2:
            if p1 != p2:
                self.add_error('password2', "Passwords do not match.")
        return c

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('password1'):
            user.set_password(self.cleaned_data['password1'])
        if commit:
            user.save()
            self.save_m2m()
            user.groups.set(self.cleaned_data.get('groups', []))
        return user


class RoleForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Role name (e.g., Cashier, Manager)"
            })
        }


class RolePermissionForm(forms.Form):
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.filter(content_type__app_label='posapp').order_by('codename'),
        required=False,
        widget=forms.SelectMultiple(attrs={
            "class": "form-select js-enhance-select",
            "multiple": "multiple",
            "data-placeholder": "Select permissions",
            "data-max-items": "200",
        }),
        help_text="Attach permissions to this role."
    )

# ---------------------------
# Master Data Forms
# ---------------------------

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['code','barcode','name','category','unit_price','cost_price','tax_percent','reorder_level','is_active']
        widgets = {
            'code': forms.TextInput(attrs={"class": "form-control", "autofocus": "autofocus", "placeholder": "Unique code (e.g., PEN-001)"}),
            'barcode': forms.TextInput(attrs={"class": "form-control", "placeholder": "EAN-13 / Code128 / custom"}),
            'name': forms.TextInput(attrs={"class": "form-control", "placeholder": "Product name"}),
            'category': forms.Select(attrs={
                "class": "form-select js-enhance-select",
                "data-allow-clear": "true",
                "data-placeholder": "Select a category",
            }),
            'unit_price': forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "Selling price"}),
            'cost_price': forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "Cost price"}),
            'tax_percent': forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "GST %"}),
            'reorder_level': forms.NumberInput(attrs={"class": "form-control", "min": "0", "placeholder": "Warn at qty"}),
            'is_active': forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']
        widgets = {
            'name': forms.TextInput(attrs={"class": "form-control", "placeholder": "Category name"})
        }


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name','phone','email']
        widgets = {
            'name': forms.TextInput(attrs={"class": "form-control", "placeholder": "Supplier name"}),
            'phone': forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone"}),
            'email': forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email"}),
        }


class CustomerForm(forms.ModelForm):
    """Extended for credit system."""
    class Meta:
        model = Customer
        fields = ['name','phone','email','credit_limit','sms_opt_in','call_opt_in']
        widgets = {
            'name': forms.TextInput(attrs={"class": "form-control", "placeholder": "Customer name"}),
            'phone': forms.TextInput(attrs={"class": "form-control", "placeholder": "Phone"}),
            'email': forms.EmailInput(attrs={"class": "form-control", "placeholder": "Email"}),
            'credit_limit': forms.NumberInput(attrs={
                "class": "form-control", "step": "0.01", "min": "0", "placeholder": "0.00"
            }),
            'sms_opt_in': forms.CheckboxInput(attrs={"class": "form-check-input"}),
            'call_opt_in': forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

# ---------------------------
# Transactions
# ---------------------------

class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ['supplier','date','notes']
        widgets = {
            'supplier': forms.Select(attrs={
                "class": "form-select js-enhance-select",
                "data-allow-clear": "true",
                "data-placeholder": "Select supplier",
            }),
            'date': forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            'notes': forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Optional notes"}),
        }


class SaleForm(forms.ModelForm):
    is_return = forms.BooleanField(required=False, label='Return (Credit Note)')
    class Meta:
        model = Sale
        fields = ['customer','date','discount','payment_method','paid_amount','is_return']
        widgets = {
            'customer': forms.Select(attrs={
                "class": "form-select js-enhance-select",
                "data-allow-clear": "true",
                "data-placeholder": "Walk-in (leave empty) or pick customer",
            }),
            'date': forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            'discount': forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "0.00"}),
            'payment_method': forms.Select(attrs={
                "class": "form-select js-enhance-select",
                "data-placeholder": "Payment method"
            }),
            'paid_amount': forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0", "placeholder": "0.00"}),
            'is_return': forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

# ---------------------------
# Stock
# ---------------------------

class StockAdjustForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=Product.objects.filter(is_active=True).order_by('code'),
        required=True,
        widget=forms.Select(attrs={
            "class": "form-select js-enhance-select",
            "data-allow-clear": "true",
            "data-placeholder": "Select product",
        })
    )
    qty = forms.IntegerField(
        min_value=1, initial=1,
        widget=forms.NumberInput(attrs={"class": "form-control", "min": "1"}),
        help_text="Units to add to stock"
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Optional note"}),
        help_text="Optional note for this stock adjustment"
    )

# ---------------------------
# Settings
# ---------------------------

class SiteSettingForm(forms.ModelForm):
    class Meta:
        model = SiteSetting
        fields = [
            # Org/Bill
            'org_name','org_address','org_phone','org_email',
            'bill_title','bill_footer','bill_tax_inclusive',
            # Credit
            'credit_enforce','credit_alert_threshold',
            # SMS
            'sms_enabled','sms_provider','sms_api_key','sms_sender',
            # Calls
            'call_enabled','call_provider','call_sid','call_token','call_from',
        ]
        widgets = {
            'org_name': forms.TextInput(attrs={"class": "form-control", "placeholder": "Your store name"}),
            'org_address': forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Address as shown on bill"}),
            'org_phone': forms.TextInput(attrs={"class": "form-control", "placeholder": "+91 …"}),
            'org_email': forms.EmailInput(attrs={"class": "form-control", "placeholder": "billing@store.com"}),

            'bill_title': forms.TextInput(attrs={"class": "form-control", "placeholder": "e.g., TAX INVOICE"}),
            'bill_footer': forms.Textarea(attrs={"class": "form-control", "rows": 3, "placeholder": "Footer note on invoices"}),
            'bill_tax_inclusive': forms.CheckboxInput(attrs={"class": "form-check-input"}),

            'credit_enforce': forms.CheckboxInput(attrs={"class": "form-check-input"}),
            'credit_alert_threshold': forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0"}),

            'sms_enabled': forms.CheckboxInput(attrs={"class": "form-check-input"}),
            'sms_provider': forms.Select(attrs={
                "class": "form-select js-enhance-select",
                "data-placeholder": "Choose SMS provider"
            }),
            'sms_api_key': forms.TextInput(attrs={"class": "form-control", "placeholder": "API key / token"}),
            'sms_sender': forms.TextInput(attrs={"class": "form-control", "placeholder": "Sender ID (e.g., ACMECO)"}),

            'call_enabled': forms.CheckboxInput(attrs={"class": "form-check-input"}),
            'call_provider': forms.Select(attrs={
                "class": "form-select js-enhance-select",
                "data-placeholder": "Choose call provider"
            }),
            'call_sid': forms.TextInput(attrs={"class": "form-control", "placeholder": "Account SID"}),
            'call_token': forms.TextInput(attrs={"class": "form-control", "placeholder": "Auth token"}),
            'call_from': forms.TextInput(attrs={"class": "form-control", "placeholder": "Caller ID / From number"}),
        }

# ---------------------------
# Credit System – new utility forms
# ---------------------------

class ReceivePaymentForm(forms.Form):
    """
    Record a payment received from a customer.
    Will translate to a CustomerLedger CREDIT (reduces balance).
    """
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.order_by('name'),
        widget=forms.Select(attrs={
            "class": "form-select js-enhance-select",
            "data-allow-clear": "true",
            "data-placeholder": "Select customer",
        })
    )
    date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"})
    )
    amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01", "placeholder": "0.00"})
    )
    reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Txn Ref / UTR / Cheque #"})
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Optional note"})
    )


class CustomerChargeForm(forms.Form):
    """
    Post a manual charge (opening balance, fee, adjustment).
    Will translate to a CustomerLedger DEBIT (increases balance).
    """
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.order_by('name'),
        widget=forms.Select(attrs={
            "class": "form-select js-enhance-select",
            "data-allow-clear": "true",
            "data-placeholder": "Select customer",
        })
    )
    date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"})
    )
    amount = forms.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={"class": "form-control", "step": "0.01", "min": "0.01", "placeholder": "0.00"})
    )
    reason = forms.CharField(
        label="Reason / Description",
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Opening balance / Adjustment / Fee"})
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Optional note"})
    )


class CustomerStatementFilterForm(forms.Form):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.order_by('name'),
        required=False,
        widget=forms.Select(attrs={
            "class": "form-select js-enhance-select",
            "data-allow-clear": "true",
            "data-placeholder": "All customers",
        })
    )
    start = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
    end   = forms.DateField(required=False, widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}))
