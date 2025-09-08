from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings as dj_settings
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import date

User = get_user_model()

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

class Category(TimeStampedModel):
    name = models.CharField(max_length=120, unique=True)

    def __str__(self):
        return self.name

class Product(TimeStampedModel):
    code = models.CharField(max_length=64, unique=True)
    barcode = models.CharField(max_length=64, unique=True, null=True, blank=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)  # per-product GST/VAT%
    reorder_level = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def stock(self):
        agg = self.stockmove_set.aggregate(total=models.Sum('change'))
        return agg['total'] or 0

class Supplier(TimeStampedModel):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return self.name

class Customer(TimeStampedModel):
    name = models.CharField(max_length=150)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return self.name
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    sms_opt_in   = models.BooleanField(default=True)
    call_opt_in  = models.BooleanField(default=False)

    @property
    def balance(self):
        agg = self.customerledger_set.aggregate(
            d=models.Sum('debit'), c=models.Sum('credit')
        )
        d = agg.get('d') or 0
        c = agg.get('c') or 0
        return d - c  # amount customer owes

class Purchase(TimeStampedModel):
    supplier = models.ForeignKey(Supplier, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"PO-{self.id} {self.date}"

class PurchaseItem(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = models.PositiveIntegerField()
    cost_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def __str__(self):
        return f"{self.product} x {self.qty}"

class Sale(TimeStampedModel):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # pre-tax
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)       # computed from per-product tax
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    PAYMENT_CHOICES = (('cash', 'Cash'), ('card', 'Card'), ('upi', 'UPI'))
    payment_method = models.CharField(max_length=10, choices=PAYMENT_CHOICES, default='cash')
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    is_return = models.BooleanField(default=False)  # credit note; totals stored as negative

    def __str__(self):
        return f"{'CRN' if self.is_return else 'INV'}-{self.id} {self.date}"

class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    qty = models.IntegerField()  # negative for returns
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)  # pre-tax
    tax_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f"{self.product} x {self.qty}"

class StockMove(TimeStampedModel):
    REASONS = (
        ('purchase', 'Purchase'),
        ('sale', 'Sale'),
        ('adjustment', 'Adjustment'),
        ('return', 'Return'),
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    change = models.IntegerField(help_text="Positive for inbound, negative for outbound")
    reason = models.CharField(max_length=20, choices=REASONS)
    ref = models.CharField(max_length=64, blank=True, help_text="Reference id (e.g. INV-12, CRN-2, PO-5)")

    def __str__(self):
        return f"{self.product} {self.change} ({self.reason})"
# --- App-level permissions anchor (no DB table) ---

class AppPermission(models.Model):
    """Anchor model to hold app-wide custom permissions (no table)."""
    class Meta:
        managed = False
        default_permissions = ()
        permissions = [
            ('can_pos', 'Can use POS (sell/return)'),
            ('can_view_reports', 'Can view and download reports'),
            ('can_print_barcodes', 'Can print barcode labels'),
            ('can_adjust_stock', 'Can adjust stock (quick/bulk)'),
            ('can_manage_purchases', 'Can create purchases'),
            ('can_manage_users', 'Can manage users and roles'),
        ]

class CustomerLedger(models.Model):
    customer    = models.ForeignKey('Customer', on_delete=models.CASCADE)
    date        = models.DateField(default=date.today)
    description = models.CharField(max_length=120, blank=True)
    debit       = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # increases balance
    credit      = models.DecimalField(max_digits=12, decimal_places=2, default=0) # decreases balance
    sale        = models.ForeignKey('Sale', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-date','-id']

# --- NEW: SiteSetting (singleton) for bill & notifications ---
class SiteSetting(models.Model):
    singleton_id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    # Org / Bill
    org_name    = models.CharField(max_length=120, default='Your Store')
    org_address = models.TextField(blank=True, default='')
    org_phone   = models.CharField(max_length=32, blank=True, default='')
    org_email   = models.EmailField(blank=True, default='')
    bill_title  = models.CharField(max_length=60, default='Tax Invoice')
    bill_footer = models.CharField(max_length=200, blank=True, default='')
    bill_tax_inclusive = models.BooleanField(default=True)

    # Credit rules
    credit_enforce = models.BooleanField(default=False)  # block if exceeds limit
    credit_alert_threshold = models.DecimalField(
        max_digits=5, decimal_places=2, default=80,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )  # % of limit to trigger alert

    # SMS
    sms_enabled  = models.BooleanField(default=False)
    sms_provider = models.CharField(max_length=20, choices=[
        ('textlocal', 'Textlocal'),
        ('msg91', 'MSG91'),
    ], default='textlocal')
    sms_api_key  = models.CharField(max_length=200, blank=True, default='')
    sms_sender   = models.CharField(max_length=11, blank=True, default='TXTLCL')  # 6-11 chars as per DLT

    # Calls (optional)
    call_enabled = models.BooleanField(default=False)
    call_provider = models.CharField(max_length=20, choices=[
        ('twilio', 'Twilio'),
    ], default='twilio')
    call_sid     = models.CharField(max_length=64, blank=True, default='')
    call_token   = models.CharField(max_length=64, blank=True, default='')
    call_from    = models.CharField(max_length=20, blank=True, default='')

    class Meta:
        permissions = [
            ('can_manage_settings', 'Can manage POS settings'),
        ]

    @staticmethod
    def get():
        obj, _ = SiteSetting.objects.get_or_create(pk=1)
        return obj
