from django import forms
from .models import Product, Category, Supplier, Customer, Purchase, Sale, SiteSetting

from django.contrib.auth.models import User, Group, Permission

class UserCreateForm(forms.ModelForm):
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password")
    password2 = forms.CharField(widget=forms.PasswordInput, label="Confirm Password")
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(), required=False, widget=forms.SelectMultiple(attrs={'size': 6})
    )
    is_staff = forms.BooleanField(initial=True, required=False)
    is_active = forms.BooleanField(initial=True, required=False)

    class Meta:
        model = User
        fields = ['username', 'email', 'is_staff', 'is_active', 'groups']

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
    password1 = forms.CharField(widget=forms.PasswordInput, required=False, label="New Password")
    password2 = forms.CharField(widget=forms.PasswordInput, required=False, label="Confirm New Password")
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(), required=False, widget=forms.SelectMultiple(attrs={'size': 6})
    )
    is_staff = forms.BooleanField(required=False)
    is_active = forms.BooleanField(required=False)

    class Meta:
        model = User
        fields = ['email', 'is_staff', 'is_active', 'groups']

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

class RolePermissionForm(forms.Form):
    # Show only this app’s permissions (cleaner UI). Add others if you like.
    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.filter(content_type__app_label='posapp').order_by('codename'),
        required=False,
        widget=forms.SelectMultiple(attrs={'size': 12})
    )


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['code','barcode','name','category','unit_price','cost_price','tax_percent','reorder_level','is_active']

class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ['name']

class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ['name','phone','email']

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['name','phone','email']

class PurchaseForm(forms.ModelForm):
    class Meta:
        model = Purchase
        fields = ['supplier','date','notes']

class SaleForm(forms.ModelForm):
    is_return = forms.BooleanField(required=False, label='Return (Credit Note)')
    class Meta:
        model = Sale
        fields = ['customer','date','discount','payment_method','paid_amount','is_return']

class StockAdjustForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.filter(is_active=True), required=True)
    qty = forms.IntegerField(min_value=1, initial=1, help_text="Units to add to stock")
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows':2}), help_text="Optional note for this stock adjustment")

# NEW: Settings form
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
            'org_address': forms.Textarea(attrs={'rows': 3}),
        }
