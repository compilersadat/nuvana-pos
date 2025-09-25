from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings as dj_settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models.signals import post_migrate
from django.dispatch import receiver
from decimal import Decimal
from django.utils import timezone

User = get_user_model()
TWO_DEC = Decimal('0.01')


# -------------------------------------------------------------------
# Base
# -------------------------------------------------------------------
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# -------------------------------------------------------------------
# Catalog
# -------------------------------------------------------------------
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
        # total on-hand = sum of StockMove.change
        agg = self.stockmove_set.aggregate(total=models.Sum('change'))
        return agg['total'] or 0


# -------------------------------------------------------------------
# Parties
# -------------------------------------------------------------------
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

    # --- Credit profile ---
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    sms_opt_in   = models.BooleanField(default=True)
    call_opt_in  = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    # --- Credit helpers ---
    @property
    def balance(self) -> Decimal:
        """Outstanding amount (what customer owes us): debits - credits."""
        agg = self.customerledger_set.aggregate(
            d=models.Sum('debit'),
            c=models.Sum('credit'),
        )
        d = Decimal(agg.get('d') or 0)
        c = Decimal(agg.get('c') or 0)
        return (d - c).quantize(TWO_DEC)

    @property
    def available_credit(self) -> Decimal:
        """How much room remains under the limit (can be negative if exceeded)."""
        return (Decimal(self.credit_limit or 0) - self.balance).quantize(TWO_DEC)

    @property
    def is_over_limit(self) -> bool:
        return self.balance > (self.credit_limit or Decimal('0.00'))

    def threshold_reached(self) -> bool:
        """
        Uses SiteSetting.credit_alert_threshold as a PERCENT of limit.
        e.g., 80 means alert at (balance >= 80% of credit_limit).
        If limit is 0, never trigger based on percent.
        """
        try:
            s = SiteSetting.get()
        except Exception:
            return False
        lim = Decimal(self.credit_limit or 0)
        if lim <= 0:
            return False
        pct = Decimal(s.credit_alert_threshold or 0)  # 0-100
        threshold_amt = (lim * pct / Decimal('100')).quantize(TWO_DEC)
        return self.balance >= threshold_amt


# -------------------------------------------------------------------
# Inbound (Purchases)
# -------------------------------------------------------------------
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


# -------------------------------------------------------------------
# Outbound (Sales / Returns)
# -------------------------------------------------------------------
class Sale(TimeStampedModel):
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # pre-tax
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax = models.DecimalField(max_digits=12, decimal_places=2, default=0)       # computed from per-product tax
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    PAYMENT_CHOICES = (('cash', 'Cash'), ('card', 'Card'), ('upi', 'UPI'), ('other', 'Other'))
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


# -------------------------------------------------------------------
# Stock movements
# -------------------------------------------------------------------
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


# -------------------------------------------------------------------
# App-level permissions anchor (no DB table)
# -------------------------------------------------------------------
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
            ('can_manage_settings', 'Can manage POS settings'),
            ('can_manage_users', 'Can manage users and roles'),
            ('can_credit_receive', 'Can receive customer payments'),
            ('can_credit_charge',  'Can post customer charges/fees'),
            ('can_credit_view',    'Can view customer credit statements'),
        ]


# -------------------------------------------------------------------
# Credit Ledger
# -------------------------------------------------------------------
class CustomerLedger(models.Model):
    customer    = models.ForeignKey('Customer', on_delete=models.CASCADE)
    date        = models.DateField(default=timezone.localdate)
    description = models.CharField(max_length=200, blank=True)
    debit       = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # increases balance
    credit      = models.DecimalField(max_digits=12, decimal_places=2, default=0) # decreases balance
    sale        = models.ForeignKey('Sale', null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        ordering = ['-date','-id']
        indexes = [
            models.Index(fields=['customer', 'date']),
            models.Index(fields=['sale']),
        ]

    def __str__(self):
        amt = self.debit or self.credit
        side = 'DR' if self.debit else 'CR'
        return f"{self.customer} {side} {amt} on {self.date}"


# -------------------------------------------------------------------
# Site settings (singleton)
# -------------------------------------------------------------------
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
    credit_alert_threshold = models.DecimalField(        # PERCENT of limit (0-100)
        max_digits=5, decimal_places=2, default=Decimal('80.00'),
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )

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

    def __str__(self):
        return f"Settings ({self.org_name})"

    @staticmethod
    def get():
        obj, _ = SiteSetting.objects.get_or_create(pk=1)
        return obj


# Ensure the singleton exists right after migrations
@receiver(post_migrate)
def ensure_settings_singleton(sender, **kwargs):
    if sender.label == __name__.split('.')[0]:  # only for this app
        SiteSetting.objects.get_or_create(pk=1)
