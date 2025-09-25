from datetime import date, timedelta
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import FieldDoesNotExist
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Sum, F, DecimalField, ExpressionWrapper, Q, Value, Subquery, OuterRef, Count,Case, When

)
from django.db.models.functions import Coalesce, Cast
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    ProductForm, SiteSettingForm, SupplierForm, CustomerForm,
    PurchaseForm, SaleForm, StockAdjustForm,
    UserCreateForm, UserEditForm, RoleForm, RolePermissionForm,
    # NEW credit forms
    ReceivePaymentForm, CustomerChargeForm, CustomerStatementFilterForm,
)
from .models import (
    Product, SiteSetting, Supplier, Customer, Purchase, PurchaseItem,
    Sale, SaleItem, StockMove, Category, CustomerLedger
)
import csv, io, json
from django.contrib.auth.models import User, Group, Permission

# PDF / Barcode libs
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.graphics.barcode import code128, createBarcodeDrawing
from reportlab.graphics import renderPDF
from reportlab.lib.utils import simpleSplit


# -------------------------------------------------------------------
# Helpers: credit enforcement, ledger posting, (optional) SMS notifier
# -------------------------------------------------------------------

def _send_sms_if_enabled(customer: Customer, message: str):
    """Lightweight SMS hook. Replace with real gateway call if needed."""
    s = SiteSetting.get()
    if not (s.sms_enabled and customer and customer.sms_opt_in and customer.phone):
        return
    # Integrate your gateway here (Textlocal / MSG91). For now, log via messages.
    # e.g., requests.post(...)  — intentionally omitted.
    # messages.info(request, f"SMS to {customer.phone}: {message}")  # if you pass request
    # Since we may not have request in helpers, simply no-op here.


def _enforce_credit_or_block(customer: Customer, will_add_debit: Decimal):
    """
    Returns None if allowed, else a human-readable error string.
    - customer.balance = debits - credits
    - will_add_debit is the additional debit we’re about to post (>= 0)
    """
    if not customer or will_add_debit <= 0:
        return None
    s = SiteSetting.get()
    if not s.credit_enforce:
        return None

    cur = customer.balance or Decimal('0.00')
    limit = customer.credit_limit or Decimal('0.00')
    if limit <= 0:
        return "Customer has no credit limit."

    new_bal = cur + will_add_debit
    if new_bal > limit:
        over = new_bal - limit
        return (
            f"Sale blocked: credit limit exceeded. "
            f"Limit ₹{limit:.2f}, current ₹{cur:.2f}, new balance ₹{new_bal:.2f} (over by ₹{over:.2f})."
        )
    return None


def _maybe_credit_alert(customer: Customer, added_debit: Decimal):
    """Show a warning (and optionally SMS) when balance crosses threshold% of limit."""
    if not customer or added_debit <= 0:
        return
    s = SiteSetting.get()
    limit = customer.credit_limit or Decimal('0.00')
    if limit <= 0:
        return
    cur = customer.balance or Decimal('0.00')
    after = cur + added_debit
    pct = (after / limit * 100) if limit > 0 else 0
    if pct >= (s.credit_alert_threshold or Decimal('80')):
        msg = (
            f"Credit alert for {customer.name}: "
            f"₹{after:.2f} / ₹{limit:.2f} ({pct:.0f}%)."
        )
        # UI warning (caller typically adds a messages.warning)
        _send_sms_if_enabled(customer, msg)


def _post_ledger_for_sale(sale: Sale):
    """
    Post a single CustomerLedger line from the signed totals of a sale.
    - sale.total is SIGNED (+ for sale, - for return)
    - due = sale.total - sale.paid_amount
      > 0  => customer owes store => DEBIT
      < 0  => store owes customer => CREDIT
    """
    if not sale.customer:
        return
    due = (sale.total or Decimal('0')) - (sale.paid_amount or Decimal('0'))
    if due == 0:
        return
    if due > 0:
        CustomerLedger.objects.create(
            customer=sale.customer, date=sale.date,
            description=f"{'INV' if not sale.is_return else 'CRN'}-{sale.id}",
            debit=due, credit=0, sale=sale
        )
    else:
        CustomerLedger.objects.create(
            customer=sale.customer, date=sale.date,
            description=f"{'INV' if not sale.is_return else 'CRN'}-{sale.id}",
            debit=0, credit=abs(due), sale=sale
        )


# --------------------------
# Dashboard (unchanged logic)
# --------------------------
@login_required
def dashboard(request):
    today = date.today()

    # ===== Basic KPIs =====
    total_sales_today = (
        Sale.objects.filter(date=today)
        .aggregate(s=Coalesce(Sum('total'), Value(Decimal('0.00'))))['s']
    )
    total_products = Product.objects.count()

    # Low stock count & details
    low_stock_qs = (
        Product.objects.select_related('category')
        .annotate(stock_sum=Coalesce(Sum('stockmove__change'), Value(0)))
    )
    low_stock = low_stock_qs.filter(stock_sum__lte=F('reorder_level')).count()
    low_stock_details = (
        low_stock_qs.filter(stock_sum__lte=F('reorder_level'))
        .order_by('stock_sum', 'code')[:15]
    )

    # ===== Top selling & customers (last 30 days) =====
    start_30 = today - timedelta(days=30)

    top_products = (
        SaleItem.objects
        .filter(sale__is_return=False, sale__date__gte=start_30)
        .values('product__id', 'product__code', 'product__name')
        .annotate(
            total_qty=Coalesce(Sum('qty'), Value(0)),
            revenue=Coalesce(
                Sum(
                    ExpressionWrapper(
                        F('qty') * F('unit_price'),
                        output_field=DecimalField(max_digits=14, decimal_places=2)
                    )
                ),
                Value(Decimal('0.00'))
            ),
        )
        .order_by('-total_qty')[:10]
    )

    # Subqueries to find each customer's most purchased product (qty) in last 30 days
    top_prod_base = (
        SaleItem.objects
        .filter(sale__is_return=False, sale__date__gte=start_30, sale__customer=OuterRef('customer_id'))
        .values('product__id')
        .annotate(qty_sum=Coalesce(Sum('qty'), Value(0)))
        .order_by('-qty_sum', 'product__id')
    )
    top_prod_name_sq = top_prod_base.values('product__name')[:1]
    top_prod_code_sq = top_prod_base.values('product__code')[:1]
    top_prod_qty_sq  = top_prod_base.values('qty_sum')[:1]

    top_customers = (
        Sale.objects.filter(is_return=False, date__gte=start_30)
        .values('customer_id', 'customer__name')
        .annotate(
            invoices=Count('id'),
            total=Coalesce(Sum('total'), Value(Decimal('0.00'))),
            top_product=Subquery(top_prod_name_sq),
            top_product_code=Subquery(top_prod_code_sq),
            top_product_qty=Subquery(top_prod_qty_sq),
        )
        .order_by('-total')[:10]
    )

    # ===== Credit overview =====
    s = SiteSetting.get()
    threshold = s.credit_alert_threshold or Decimal('80')
    # Note: DO NOT annotate a field named "balance" (conflicts with @property). Use "bal".
    customers_balanced = (
        Customer.objects
        .annotate(
            debit_sum=Coalesce(Sum('customerledger__debit'),  Value(Decimal('0.00'))),
            credit_sum=Coalesce(Sum('customerledger__credit'), Value(Decimal('0.00')))
        )
        .annotate(
            bal=ExpressionWrapper(
                F('debit_sum') - F('credit_sum'),
                output_field=DecimalField(max_digits=14, decimal_places=2)
            )
        )
    )

    # Total outstanding = sum of positive balances
    total_outstanding = (
        customers_balanced.filter(bal__gt=0)
        .aggregate(t=Coalesce(Sum('bal'), Value(Decimal('0.00'))))['t']
    )

    # Nearing threshold: balance/limit >= threshold% (only where limit > 0 and bal > 0)
    nearing_threshold_count = (
        customers_balanced
        .filter(credit_limit__gt=0, bal__gt=0)
        .annotate(
            usage_pct=ExpressionWrapper(
                (F('bal') * Value(100.0)) / F('credit_limit'),
                output_field=DecimalField(max_digits=7, decimal_places=2)
            )
        )
        .filter(usage_pct__gte=threshold)
        .count()
    )

    # Over limit list (top 10 by excess)
    over_limit_list = (
        customers_balanced
        .filter(credit_limit__gt=0, bal__gt=F('credit_limit'))
        .annotate(
            excess=ExpressionWrapper(
                F('bal') - F('credit_limit'),
                output_field=DecimalField(max_digits=14, decimal_places=2)
            )
        )
        .values('id', 'name', 'bal', 'credit_limit', 'excess')
        .order_by('-excess')[:10]
    )

    # Top debtors (balances > 0) with usage % for table
    top_debtors = (
        customers_balanced
        .annotate(
            usage_pct=Case(
                When(credit_limit__gt=0,
                     then=ExpressionWrapper(
                         (F('bal') * Value(100.0)) / F('credit_limit'),
                         output_field=DecimalField(max_digits=7, decimal_places=2)
                     )),
                default=Value(0),
                output_field=DecimalField(max_digits=7, decimal_places=2)
            )
        )
        .filter(bal__gt=0)
        .values('id', 'name', 'bal', 'credit_limit', 'usage_pct')
        .order_by('-bal')[:10]
    )

    credit_kpis = {
        'total_outstanding': total_outstanding or Decimal('0.00'),
        'nearing_threshold': nearing_threshold_count,
        'customers_over_limit': len(over_limit_list),
    }

    return render(request, 'dashboard.html', {
        # Core KPIs
        'total_sales_today': total_sales_today or Decimal('0.00'),
        'total_products': total_products,
        'low_stock': low_stock,
        'low_stock_details': low_stock_details,
        'top_products': top_products,
        'top_customers': top_customers,
        # Credit
        'credit_kpis': credit_kpis,
        'credit_threshold': threshold,       # used for label "≥ {{ credit_threshold }}%"
        'top_debtors': top_debtors,
        'over_limit_list': over_limit_list,
    })

# --------------------------
# Pager Helper (unchanged)
# --------------------------

def _pager_ctx(request, queryset, default_size=25):
    try:
        page_size = int(request.GET.get('page_size') or default_size)
    except (TypeError, ValueError):
        page_size = default_size
    if page_size not in (10, 25, 50, 100, 200):
        page_size = default_size

    paginator = Paginator(queryset, page_size)
    page_number = request.GET.get('page') or 1
    page_obj = paginator.get_page(page_number)

    qs_copy = request.GET.copy()
    qs_copy.pop('page', None)
    base_qs = qs_copy.urlencode()
    return page_obj, page_size, base_qs


# -------------
# Masters (same)
# -------------

@login_required
def product_list(request):
    q = (request.GET.get('q') or '').strip()
    products = Product.objects.select_related('category').all().order_by('code')
    if q:
        products = products.filter(
            Q(name__icontains=q) | Q(code__icontains=q) | Q(barcode__icontains=q)
        )

    page_obj, page_size, base_qs = _pager_ctx(request, products)
    return render(request, 'products/list.html', {
        'q': q,
        'page_obj': page_obj,
        'page_size': page_size,
        'base_qs': base_qs,
    })


@login_required
def product_create(request):
    if request.method == 'POST':
        form = ProductForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product created.')
            return redirect('product_list')
    else:
        form = ProductForm()
    return render(request, 'products/form.html', {'form': form, 'title': 'New Product'})


@login_required
def product_update(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == 'POST':
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            form.save()
            messages.success(request, 'Product updated.')
            return redirect('product_list')
    else:
        form = ProductForm(instance=product)
    return render(request, 'products/form.html', {'form': form, 'title': 'Edit Product'})


@login_required
def product_export(request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="products.csv"'
    writer = csv.writer(response)
    writer.writerow(['code','barcode','name','category','unit_price','cost_price','tax_percent','reorder_level','is_active'])
    for p in Product.objects.select_related('category').all():
        writer.writerow([
            p.code or '', p.barcode or '', p.name,
            (p.category.name if p.category else ''),
            p.unit_price, p.cost_price, p.tax_percent, p.reorder_level, int(p.is_active)
        ])
    return response


@login_required
def product_import(request):
    if request.method != 'POST' or 'file' not in request.FILES:
        messages.error(request, 'Upload a CSV file.')
        return redirect('product_list')
    f = io.TextIOWrapper(request.FILES['file'].file, encoding='utf-8')
    reader = csv.DictReader(f)
    count = 0
    for row in reader:
        code = (row.get('code') or '').strip()
        if not code:
            continue
        barcode = (row.get('barcode') or '').strip() or None
        name = (row.get('name') or '').strip()
        cat_name = (row.get('category') or '').strip() or None
        unit_price = Decimal(row.get('unit_price') or '0')
        cost_price = Decimal(row.get('cost_price') or '0')
        tax_percent = Decimal(row.get('tax_percent') or '0')
        reorder_level = int(row.get('reorder_level') or 0)
        is_active = (row.get('is_active') or '1') in ('1','true','True','yes','YES')
        category = None
        if cat_name:
            category, _ = Category.objects.get_or_create(name=cat_name)
        Product.objects.update_or_create(
            code=code,
            defaults={
                'barcode': barcode, 'name': name, 'category': category,
                'unit_price': unit_price, 'cost_price': cost_price,
                'tax_percent': tax_percent, 'reorder_level': reorder_level,
                'is_active': is_active
            }
        )
        count += 1
    messages.success(request, f'Imported {count} products.')
    return redirect('product_list')


@login_required
def supplier_list(request):
    suppliers = Supplier.objects.all().order_by('name')
    page_obj, page_size, base_qs = _pager_ctx(request, suppliers)
    return render(request, 'suppliers/list.html', {
        'page_obj': page_obj,
        'page_size': page_size,
        'base_qs': base_qs,
    })


@login_required
def supplier_create(request):
    if request.method == 'POST':
        form = SupplierForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Supplier created.')
            return redirect('supplier_list')
    else:
        form = SupplierForm()
    return render(request, 'suppliers/form.html', {'form': form, 'title': 'New Supplier'})


@login_required
def customer_list(request):
    customers = Customer.objects.all().order_by('name')
    page_obj, page_size, base_qs = _pager_ctx(request, customers)
    return render(request, 'customers/list.html', {
        'page_obj': page_obj,
        'page_size': page_size,
        'base_qs': base_qs,
    })


@login_required
def customer_create(request):
    if request.method == 'POST':
        form = CustomerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Customer created.')
            return redirect('customer_list')
    else:
        form = CustomerForm()
    return render(request, 'customers/form.html', {'form': form, 'title': 'New Customer'})


# ----------------
# Stock Adjustments
# ----------------

@login_required
@permission_required('posapp.can_adjust_stock', raise_exception=True)
def product_add_stock(request, pk=None):
    product = None
    if pk:
        product = get_object_or_404(Product, pk=pk)
    initial = {}
    if product:
        initial['product'] = product.id
    if request.method == 'POST':
        form = StockAdjustForm(request.POST)
        if form.is_valid():
            product = form.cleaned_data['product']
            qty = form.cleaned_data['qty']
            note = form.cleaned_data.get('note') or ''
            StockMove.objects.create(product=product, change=qty, reason='adjustment', ref=note[:64])
            messages.success(request, f"Added {qty} to stock for {product.code} — new stock: {product.stock}")
            return redirect('product_list')
    else:
        form = StockAdjustForm(initial=initial)
    return render(request, 'products/add_stock.html', {'form': form, 'product': product})


# -------- Purchases --------

@login_required
@permission_required('posapp.can_manage_purchases', raise_exception=True)
@transaction.atomic
def purchase_create(request):
    products = Product.objects.filter(is_active=True)
    if request.method == 'POST':
        form = PurchaseForm(request.POST)
        items_json = request.POST.get('items_json','[]')
        try:
            items = json.loads(items_json)
        except Exception:
            items = []
        if form.is_valid() and items:
            purchase = form.save(commit=False)
            purchase.total = Decimal('0.00')
            purchase.save()
            total = Decimal('0.00')
            for it in items:
                product = get_object_or_404(Product, pk=it['product_id'])
                qty = int(it['qty'])
                price_val = it.get('cost_price', it.get('unit_price', 0))
                cost_price = Decimal(str(price_val))
                line_total = cost_price * qty
                PurchaseItem.objects.create(
                    purchase=purchase, product=product, qty=qty,
                    cost_price=cost_price, line_total=line_total
                )
                StockMove.objects.create(product=product, change=qty, reason='purchase', ref=f"PO-{purchase.id}")
                total += line_total
            purchase.total = total
            purchase.save()
            messages.success(request, f'Purchase PO-{purchase.id} saved.')
            return redirect('purchase_create')
        else:
            messages.error(request, 'Please add at least one item.')
    else:
        form = PurchaseForm(initial={'date': date.today()})
    return render(request, 'purchases/new.html', {'form': form, 'products': products})


# -------- POS Sale / Return (CREDIT-AWARE) --------

@login_required
@permission_required('posapp.can_pos', raise_exception=True)
@transaction.atomic
def pos_sale_create(request):
    products = (
        Product.objects.filter(is_active=True)
        .annotate(stock_sum=Coalesce(Sum('stockmove__change'), 0))
        .filter(stock_sum__gt=1)
    )

    if request.method == 'POST':
        form = SaleForm(request.POST)
        vals = request.POST.getlist('items_json')
        items_json = next((v for v in reversed(vals) if (v or '').strip()), '[]')
        try:
            items = json.loads(items_json)
        except Exception:
            items = []

        if form.is_valid() and items:
            sale = form.save(commit=False)

            # --- HARD STOCK CHECK (normal sales only) ---
            if not sale.is_return:
                req_by_pid = {}
                for it in items:
                    try:
                        pid = int(it.get('product_id'))
                        qty = int(it.get('qty') or 0)
                    except Exception:
                        continue
                    req_by_pid[pid] = req_by_pid.get(pid, 0) + qty

                if req_by_pid:
                    stock_rows = (
                        StockMove.objects
                        .filter(product_id__in=req_by_pid.keys())
                        .values('product_id')
                        .annotate(s=Coalesce(Sum('change'), 0))
                    )
                    stock_map = {r['product_id']: int(r['s'] or 0) for r in stock_rows}
                    labels = {p.id: f"{p.code} — {p.name}"
                              for p in Product.objects.filter(id__in=req_by_pid.keys()).only('id','code','name')}

                    insufficient = []
                    for pid, want in req_by_pid.items():
                        have = stock_map.get(pid, 0)
                        if want > have:
                            insufficient.append(f"{labels.get(pid, f'ID {pid}')} (requested {want}, in stock {have})")

                    if insufficient:
                        messages.error(request, "Not enough stock for:\n" + "\n".join(insufficient))
                        return render(request, 'sales/pos.html', {
                            'form': form,
                            'products': products,
                            'items_json': items_json,
                        })

            # --- totals (pre-sign) ---
            subtotal = Decimal('0.00')
            tax_total = Decimal('0.00')
            for it in items:
                product = get_object_or_404(Product, pk=it['product_id'])
                qty = int(it['qty'])
                unit_price = Decimal(str(it.get('unit_price') or it.get('price') or 0))
                line_total = unit_price * qty
                tax_amount = (line_total * (product.tax_percent or 0) / Decimal('100')).quantize(Decimal('0.01'))
                subtotal += line_total
                tax_total += tax_amount

            sale.subtotal = subtotal
            sale.tax = tax_total
            sale.total = (subtotal - sale.discount) + tax_total

            # --- CREDIT ENFORCEMENT (only for normal sale & with customer) ---
            will_add_debit = Decimal('0.00')
            if not sale.is_return and sale.customer:
                due_if_sale = sale.total - (sale.paid_amount or Decimal('0'))
                if due_if_sale > 0:
                    will_add_debit = due_if_sale
                    msg = _enforce_credit_or_block(sale.customer, will_add_debit)
                    if msg:
                        messages.error(request, msg)
                        return render(request, 'sales/pos.html', {
                            'form': form, 'products': products, 'items_json': items_json
                        })

            # sign & save sale
            sign = Decimal('-1') if sale.is_return else Decimal('1')
            sale.subtotal *= sign
            sale.tax *= sign
            sale.total *= sign
            sale.created_by = request.user
            sale.save()

            # items + stock
            for it in items:
                product = get_object_or_404(Product, pk=it['product_id'])
                qty = int(it['qty'])
                unit_price = Decimal(str(it.get('unit_price') or it.get('price') or 0))
                line_total = unit_price * qty
                tax_amount = (line_total * (product.tax_percent or 0) / Decimal('100')).quantize(Decimal('0.01'))
                SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    qty=(qty * (-1 if sale.is_return else 1)),
                    unit_price=unit_price,
                    line_total=line_total * sign,
                    tax_percent=(product.tax_percent or 0),
                    tax_amount=tax_amount * sign
                )
                StockMove.objects.create(
                    product=product,
                    change=(qty if sale.is_return else -qty),
                    reason=('return' if sale.is_return else 'sale'),
                    ref=f"{'CRN' if sale.is_return else 'INV'}-{sale.id}"
                )

            # ledger posting & alert
            _post_ledger_for_sale(sale)
            if will_add_debit > 0:
                _maybe_credit_alert(sale.customer, will_add_debit)
                messages.warning(request, f"Credit used: ₹{will_add_debit:.2f}. New balance ₹{(sale.customer.balance):.2f}.")

            messages.success(request, f"{'Return' if sale.is_return else 'Sale'} {'CRN' if sale.is_return else 'INV'}-{sale.id} saved.")
            return redirect('invoice_view', sale_id=sale.id)

        # invalid
        messages.error(request, 'Form invalid or no items.')
        return render(request, 'sales/pos.html', {'form': form, 'products': products, 'items_json': items_json})

    # GET
    form = SaleForm(initial={'date': date.today()})
    return render(request, 'sales/pos.html', {'form': form, 'products': products})


@login_required
@permission_required('posapp.view_sale', raise_exception=True)
def invoice_view(request, sale_id):
    sale = get_object_or_404(Sale.objects.select_related('customer'), pk=sale_id)
    items = SaleItem.objects.filter(sale=sale).select_related('product')
    s = SiteSetting.get()
    return render(request, 'sales/invoice.html', {
        "sale": sale, "items": items,
        "org_name": s.org_name, "org_address": s.org_address,
        "org_phone": s.org_phone, "org_email": s.org_email,
        "bill_title": s.bill_title, "bill_footer": s.bill_footer,
        "bill_tax_inclusive": s.bill_tax_inclusive,
    })


# -------- Reports (unchanged) --------
@login_required
@permission_required('posapp.can_view_reports', raise_exception=True)
def sales_report(request):
    start = request.GET.get('start')
    end = request.GET.get('end')
    qs = Sale.objects.all()
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    total = qs.aggregate(s=Sum('total'))['s'] or Decimal('0.00')
    by_day = qs.values('date').annotate(total=Sum('total')).order_by('date')
    return render(request, 'reports/sales.html', {'sales': qs.order_by('-date','-id')[:200], 'total': total, 'by_day': by_day, 'start': start, 'end': end})


@login_required
@permission_required('posapp.can_view_reports', raise_exception=True)
def stock_report(request):
    change_field = None
    StockMoveModel = None
    try:
        from .models import StockMove as _StockMove
        StockMoveModel = _StockMove
        for cand in ("delta", "change", "qty", "quantity", "amount"):
            try:
                f = StockMoveModel._meta.get_field(cand)
                if f.get_internal_type() in {
                    "IntegerField", "PositiveIntegerField", "SmallIntegerField",
                    "PositiveSmallIntegerField", "BigIntegerField",
                    "DecimalField", "FloatField"
                }:
                    change_field = cand
                    break
            except FieldDoesNotExist:
                continue
    except Exception:
        pass

    qs = (
        Product.objects
        .annotate(
            purchased=Coalesce(Sum('purchaseitem__qty'), 0),
            sold=Coalesce(Sum('saleitem__qty', filter=Q(saleitem__sale__is_return=False)), 0),
            returned=Coalesce(Sum('saleitem__qty', filter=Q(saleitem__sale__is_return=True)), 0),
        )
    )
    if change_field:
        qs = qs.annotate(adjusted=Coalesce(Sum(f'stockmove__{change_field}'), 0))
    else:
        qs = qs.annotate(adjusted=Value(0))

    qs = qs.annotate(
        stock_sum=F('purchased') - F('sold') + F('returned') + F('adjusted'),
        valuation=ExpressionWrapper(
            Cast(Coalesce(F('stock_sum'), 0), DecimalField(max_digits=14, decimal_places=2)) *
            Coalesce(F('cost_price'), Decimal('0')),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
    ).order_by('code')

    total_valuation = qs.aggregate(total=Coalesce(Sum('valuation'), Decimal('0')))['total']

    if request.GET.get('format') == 'pdf':
        return render(request, 'reports/stock_pdf.html', {
            'products': qs,
            'total_valuation': total_valuation,
        })

    page_obj, page_size, base_qs = _pager_ctx(request, qs)
    return render(request, 'reports/stock.html', {
        'page_obj': page_obj,
        'page_size': page_size,
        'base_qs': base_qs,
        'total_valuation': total_valuation,
    })


# -------- Purchases report (same) --------

def _report_pdf_response(title, headers, rows, footer_lines=None, col_widths=None):
    resp = HttpResponse(content_type='application/pdf')
    safe_title = title.lower().replace(' ', '_')
    resp['Content-Disposition'] = f'attachment; filename="{safe_title}.pdf"'

    c = canvas.Canvas(resp, pagesize=A4)
    page_w, page_h = A4
    left, right, top, bottom = 15*mm, 15*mm, 15*mm, 15*mm

    y = page_h - top
    c.setFont('Helvetica-Bold', 14)
    c.drawString(left, y, title)
    y -= 8*mm

    ncols = len(headers)
    if not col_widths:
        total_w = page_w - left - right
        col_widths = [total_w / ncols] * ncols

    def draw_header(y_pos):
        c.setFont('Helvetica-Bold', 9)
        x = left
        for i, h in enumerate(headers):
            c.drawString(x, y_pos, str(h))
            x += col_widths[i]
        return y_pos - 5*mm

    def draw_row(y_pos, row_vals):
        import re
        c.setFont('Helvetica', 9)
        x = left
        for i, val in enumerate(row_vals):
            text = str(val)
            if re.match(r'^-?\d+(?:\.\d+)?$', text.replace(',', '')) or text.strip().startswith('₹'):
                c.drawRightString(x + col_widths[i] - 2, y_pos, text)
            else:
                c.drawString(x, y_pos, text)
            x += col_widths[i]
        return y_pos - 5*mm

    y = draw_header(y)
    for r in rows:
        if y < bottom + 20:
            c.showPage()
            y = page_h - top
            c.setFont('Helvetica-Bold', 14)
            c.drawString(left, y, title)
            y -= 8*mm
            y = draw_header(y)
        y = draw_row(y, r)

    if footer_lines:
        y -= 6*mm
        c.setFont('Helvetica-Bold', 10)
        for line in footer_lines:
            if y < bottom + 12:
                c.showPage()
                y = page_h - top
            c.drawString(left, y, str(line))
            y -= 5*mm

    c.showPage()
    c.save()
    return resp


@login_required
@permission_required('posapp.can_view_reports', raise_exception=True)
def purchase_report(request):
    start = request.GET.get('start')
    end = request.GET.get('end')
    qs = Purchase.objects.select_related('supplier').all()
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    total = qs.aggregate(s=Sum('total'))['s'] or Decimal('0.00')

    if request.GET.get('format') == 'pdf':
        headers = ['Date','PO','Supplier','Total','Notes']
        rows = []
        for p in qs.order_by('date','id'):
            rows.append([str(p.date), f'PO-{p.id}', p.supplier.name if p.supplier else '', f'₹ {p.total}', (p.notes or '')[:40]])
        title = 'Purchase Report' + (f" ({start} to {end})" if start or end else '')
        return _report_pdf_response(title, headers, rows, footer_lines=[f"Total: ₹ {total}"])
    return render(request, 'reports/purchases.html', {
        'purchases': qs.order_by('-date','-id')[:200],
        'total': total, 'start': start, 'end': end
    })


@login_required
@permission_required('posapp.view_sale', raise_exception=True)
def sales_list(request):
    start = request.GET.get('start')
    end = request.GET.get('end')
    q = (request.GET.get('q') or '').strip()

    qs = Sale.objects.select_related('customer').all()
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    if q:
        inv_id = None
        try:
            inv_id = int(q.replace('INV-', '').replace('CRN-', '').strip())
        except Exception:
            inv_id = None
        if inv_id:
            qs = qs.filter(id=inv_id) | qs.filter(customer__name__icontains=q)
        else:
            qs = qs.filter(customer__name__icontains=q)

    qs = qs.order_by('-date', '-id')
    total = qs.aggregate(s=Sum('total'))['s'] or Decimal('0.00')

    page_obj, page_size, base_qs = _pager_ctx(request, qs)
    return render(request, 'sales/list.html', {
        'page_obj': page_obj, 'page_size': page_size, 'base_qs': base_qs,
        'start': start, 'end': end, 'q': q, 'total': total,
    })


# -------- Update existing sale (rebuild ledger & stock) --------

@login_required
@permission_required('posapp.can_pos', raise_exception=True)
@transaction.atomic
def sale_update(request, sale_id):
    sale = get_object_or_404(Sale, pk=sale_id)
    products = (
        Product.objects.filter(is_active=True)
        .annotate(stock_sum=Coalesce(Sum('stockmove__change'), 0))
    )

    if request.method == 'POST':
        form = SaleForm(request.POST, instance=sale)
        items_json = request.POST.get('items_json', '[]')
        try:
            items = json.loads(items_json)
        except Exception:
            items = []

        if form.is_valid() and items:
            # wipe previous postings
            StockMove.objects.filter(ref__in=[f"INV-{sale.id}", f"CRN-{sale.id}"]).delete()
            SaleItem.objects.filter(sale=sale).delete()
            CustomerLedger.objects.filter(sale=sale).delete()

            sale = form.save(commit=False)

            subtotal = Decimal('0.00')
            tax_total = Decimal('0.00')
            for it in items:
                product = get_object_or_404(Product, pk=it['product_id'])
                qty = int(it['qty'])
                unit_price = Decimal(str(it.get('unit_price') or it.get('price') or 0))
                line_total = unit_price * qty
                tax_amount = (line_total * (product.tax_percent or 0) / Decimal('100')).quantize(Decimal('0.01'))
                subtotal += line_total
                tax_total += tax_amount

            sale.subtotal = subtotal
            sale.tax = tax_total
            sale.total = (subtotal - sale.discount) + tax_total

            # (Optional) credit enforcement on edit if changing totals upward
            will_add_debit = Decimal('0.00')
            if not sale.is_return and sale.customer:
                due_if_sale = sale.total - (sale.paid_amount or Decimal('0'))
                if due_if_sale > 0:
                    will_add_debit = due_if_sale
                    msg = _enforce_credit_or_block(sale.customer, will_add_debit)
                    if msg:
                        messages.error(request, msg)
                        return render(request, 'sales/pos.html', {
                            'form': form, 'products': products, 'editing': True,
                            'sale': sale, 'prefill_items': json.dumps([])
                        })

            sign = Decimal('-1') if sale.is_return else Decimal('1')
            sale.subtotal *= sign
            sale.tax *= sign
            sale.total *= sign
            sale.save()

            for it in items:
                product = get_object_or_404(Product, pk=it['product_id'])
                qty = int(it['qty'])
                unit_price = Decimal(str(it.get('unit_price') or it.get('price') or 0))
                line_total = unit_price * qty
                tax_amount = (line_total * (product.tax_percent or 0) / Decimal('100')).quantize(Decimal('0.01'))

                SaleItem.objects.create(
                    sale=sale,
                    product=product,
                    qty=(qty * (-1 if sale.is_return else 1)),
                    unit_price=unit_price,
                    line_total=line_total * sign,
                    tax_percent=(product.tax_percent or 0),
                    tax_amount=tax_amount * sign
                )
                StockMove.objects.create(
                    product=product,
                    change=(qty if sale.is_return else -qty),
                    reason=('return' if sale.is_return else 'sale'),
                    ref=f"{'CRN' if sale.is_return else 'INV'}-{sale.id}"
                )

            _post_ledger_for_sale(sale)
            if will_add_debit > 0:
                _maybe_credit_alert(sale.customer, will_add_debit)
                messages.warning(request, f"Credit used: ₹{will_add_debit:.2f}. New balance ₹{(sale.customer.balance):.2f}.")

            messages.success(request, f"{'Return' if sale.is_return else 'Sale'} {'CRN' if sale.is_return else 'INV'}-{sale.id} updated.")
            return redirect('invoice_view', sale_id=sale.id)
        else:
            messages.error(request, 'Form invalid or no items.')
    else:
        form = SaleForm(instance=sale)

    prefill = []
    for it in SaleItem.objects.filter(sale=sale).select_related('product'):
        p = it.product
        display = f"{p.code} - {p.name}" + (f" ({p.barcode})" if p.barcode else "")
        prefill.append({
            "display": display,
            "qty": abs(int(it.qty or 0)),
            "unit_price": float(it.unit_price or 0),
        })

    return render(request, 'sales/pos.html', {
        'form': form,
        'products': products,
        'editing': True,
        'sale': sale,
        'prefill_items': json.dumps(prefill),
    })


# --------------------------
# Security (users & roles)
# --------------------------

@permission_required('posapp.can_manage_users', raise_exception=True)
def security_users(request):
    q = request.GET.get('q', '').strip()
    users = User.objects.all().order_by('username')
    if q:
        users = users.filter(username__icontains=q) | users.filter(email__icontains=q)
    page = Paginator(users, int(request.GET.get('ps', 25))).get_page(request.GET.get('page'))
    return render(request, 'security/users_list.html', {'page': page, 'q': q})


@permission_required('posapp.can_manage_users', raise_exception=True)
def security_user_new(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            u = form.save()
            messages.success(request, f"User '{u.username}' created.")
            return redirect('security_users')
    else:
        form = UserCreateForm()
    return render(request, 'security/user_form.html', {'form': form, 'title': 'New User'})


@permission_required('posapp.can_manage_users', raise_exception=True)
def security_user_edit(request, user_id):
    user = get_object_or_404(User, pk=user_id)
    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f"User '{user.username}' updated.")
            return redirect('security_users')
    else:
        form = UserEditForm(instance=user, initial={'groups': user.groups.all()})
    return render(request, 'security/user_form.html', {'form': form, 'title': f'Edit User — {user.username}'})


@permission_required('posapp.can_manage_users', raise_exception=True)
def security_roles(request):
    roles = Group.objects.annotate(users_count=Count('user')).order_by('name')
    return render(request, 'security/roles_list.html', {'roles': roles})


@permission_required('posapp.can_manage_users', raise_exception=True)
def security_role_new(request):
    if request.method == 'POST':
        form = RoleForm(request.POST)
        perm_form = RolePermissionForm(request.POST)
        if form.is_valid() and perm_form.is_valid():
            g = form.save()
            g.permissions.set(perm_form.cleaned_data['permissions'])
            messages.success(request, f"Role '{g.name}' created.")
            return redirect('security_roles')
    else:
        form = RoleForm()
        perm_form = RolePermissionForm()
    return render(request, 'security/role_form.html', {'form': form, 'perm_form': perm_form, 'title': 'New Role'})


@permission_required('posapp.can_manage_users', raise_exception=True)
def security_role_edit(request, role_id):
    g = get_object_or_404(Group, pk=role_id)
    if request.method == 'POST':
        form = RoleForm(request.POST, instance=g)
        perm_form = RolePermissionForm(request.POST)
        if form.is_valid() and perm_form.is_valid():
            form.save()
            g.permissions.set(perm_form.cleaned_data['permissions'])
            messages.success(request, f"Role '{g.name}' updated.")
            return redirect('security_roles')
    else:
        form = RoleForm(instance=g)
        perm_form = RolePermissionForm(initial={'permissions': g.permissions.filter(content_type__app_label='posapp')})
    return render(request, 'security/role_form.html', {'form': form, 'perm_form': perm_form, 'title': f'Edit Role — {g.name}'})


# --- LIVE balance for POS UI ---
@login_required
def customer_balance_api(request, customer_id):
    c = get_object_or_404(Customer, pk=customer_id)
    return JsonResponse({
        'balance': str(c.balance or 0),
        'credit_limit': str(c.credit_limit or 0),
        'phone': c.phone or '',
        'sms_opt_in': bool(c.sms_opt_in),
        'call_opt_in': bool(c.call_opt_in),
    })


# --- Settings (RBAC-protected) ---
@permission_required('posapp.can_manage_settings', raise_exception=True)
def settings_general(request):
    s = SiteSetting.get()
    if request.method == 'POST':
        form = SiteSettingForm(request.POST, instance=s)
        if form.is_valid():
            form.save()
            messages.success(request, 'Settings saved.')
            return redirect('settings_general')
    else:
        form = SiteSettingForm(instance=s)
    return render(request, 'settings/general.html', {'form': form, 'title': 'POS Settings'})


# -------------------------
# CREDIT: Payments & Charges
# -------------------------

@login_required
@permission_required('posapp.can_credit_receive', raise_exception=True)
def receive_payment(request):
    """Record a payment received from a customer (ledger CREDIT)."""
    if request.method == 'POST':
        form = ReceivePaymentForm(request.POST)
        print("recieved",form.errors)
        if form.is_valid():
            c = form.cleaned_data['customer']
            amt = form.cleaned_data['amount']
            dt  = form.cleaned_data['date']
            ref = form.cleaned_data.get('reference') or ''
            CustomerLedger.objects.create(
                customer=c, date=dt, description=f"Payment {ref}".strip(), debit=0, credit=amt
            )
            messages.success(request, f"Payment ₹{amt:.2f} recorded for {c.name}. New balance ₹{c.balance:.2f}.")
            return redirect('receive_payment')
    else:
        form = ReceivePaymentForm(initial={'date': date.today()})
    return render(request, 'credit/receive_payment.html', {'form': form, 'title': 'Receive Payment'})



@login_required
@permission_required('posapp.can_credit_charge', raise_exception=True)
def customer_charge(request):
    """Manual charge (opening balance / adjustment) (ledger DEBIT)."""
    if request.method == 'POST':
        form = CustomerChargeForm(request.POST)
        if form.is_valid():
            c = form.cleaned_data['customer']
            amt = form.cleaned_data['amount']
            dt  = form.cleaned_data['date']
            reason = form.cleaned_data['reason']
            # Optional: enforce credit here too
            msg = _enforce_credit_or_block(c, amt)
            if msg:
                messages.error(request, msg)
            else:
                CustomerLedger.objects.create(
                    customer=c, date=dt, description=reason[:120], debit=amt, credit=0
                )
                _maybe_credit_alert(c, amt)
                messages.success(request, f"Charge ₹{amt:.2f} posted to {c.name}. New balance ₹{c.balance:.2f}.")
                return redirect('customer_charge')
    else:
        form = CustomerChargeForm(initial={'date': date.today()})
    return render(request, 'credit/customer_charge.html', {'form': form, 'title': 'Customer Charge / Opening Balance'})


@login_required
@permission_required('posapp.can_credit_view', raise_exception=True)
def customer_statement(request):
    """Simple customer statement with date filters."""
    form = CustomerStatementFilterForm(request.GET or None)
    qs = CustomerLedger.objects.select_related('customer').all().order_by('-date', '-id')

    customer = None
    if form.is_valid():
        customer = form.cleaned_data.get('customer')
        start = form.cleaned_data.get('start')
        end   = form.cleaned_data.get('end')
        if customer:
            qs = qs.filter(customer=customer)
        if start:
            qs = qs.filter(date__gte=start)
        if end:
            qs = qs.filter(date__lte=end)

    total_debit = qs.aggregate(s=Coalesce(Sum('debit'), Decimal('0')))['s']
    total_credit = qs.aggregate(s=Coalesce(Sum('credit'), Decimal('0')))['s']
    closing = (total_debit - total_credit) if (customer or True) else Decimal('0')

    return render(request, 'credit/statement.html', {
        'form': form, 'lines': qs,
        'total_debit': total_debit, 'total_credit': total_credit,
        'closing': closing, 'customer': customer,
    })


# --------------------------
# Barcodes (unchanged layout)
# --------------------------

def _ean13_normalize(value: str):
    digits = ''.join(ch for ch in (value or '') if ch.isdigit())
    if len(digits) == 12:
        odd = sum(int(digits[i]) for i in range(0, 12, 2))
        even = sum(int(digits[i]) for i in range(1, 12, 2))
        check = (10 - ((odd + 3 * even) % 10)) % 10
        return digits + str(check)
    if len(digits) == 13:
        base = digits[:12]
        odd = sum(int(base[i]) for i in range(0, 12, 2))
        even = sum(int(base[i]) for i in range(1, 12, 2))
        check = (10 - ((odd + 3 * even) % 10)) % 10
        return base + str(check)
    return None


@login_required
@permission_required('posapp.can_print_barcodes', raise_exception=True)
def barcode_labels(request):
    from .models import Product  # local import to avoid circulars

    if request.method == 'GET':
        products = Product.objects.order_by('code').all()
        return render(request, 'products/barcodes.html', {'products': products})

    ids = request.POST.getlist('product_id')
    qtys = request.POST.getlist('qty')
    tpl = request.POST.get('tpl', 'a4_3x8')
    sym = request.POST.get('sym', 'code128')

    presets = {
        'a4_3x8': dict(cols=3, rows=8, margins=(10, 10, 10, 13)),
        'a4_3x7': dict(cols=3, rows=7, margins=(10, 10, 10, 13)),
        'a4_4x12': dict(cols=4, rows=12, margins=(8, 8, 8, 12)),
        'a4_5x13': dict(cols=5, rows=13, margins=(6, 6, 6, 10)),
    }
    if tpl == 'custom':
        try:
            cols = int(request.POST.get('cols') or 3)
            rows = int(request.POST.get('rows') or 8)
            ml = float(request.POST.get('ml') or 10)
            mr = float(request.POST.get('mr') or 10)
            mt = float(request.POST.get('mt') or 10)
            mb = float(request.POST.get('mb') or 13)
            preset = dict(cols=cols, rows=rows, margins=(ml, mr, mt, mb))
        except Exception:
            preset = presets['a4_3x8']
    else:
        preset = presets.get(tpl, presets['a4_3x8'])

    cols, rows = int(preset['cols']), int(preset['rows'])
    ml, mr, mt, mb = (float(x) for x in preset['margins'])

    items = []
    for pid, q in zip(ids, qtys):
        try:
            p = Product.objects.get(pk=int(pid))
            qn = max(0, int(q))
        except Exception:
            continue
        if qn <= 0:
            continue
        raw = p.barcode or p.code
        code_to_use = _ean13_normalize(raw) if sym == 'ean13' else raw
        if sym == 'ean13' and not code_to_use:
            code_to_use = raw
        items.extend([(p, code_to_use)] * qn)

    if not items:
        messages.error(request, 'Select at least one product with quantity.')
        return redirect('product_barcodes')

    page_w, page_h = A4
    left_margin, right_margin = ml * mm, mr * mm
    top_margin, bottom_margin = mt * mm, mb * mm

    label_w = (page_w - left_margin - right_margin) / cols
    label_h = (page_h - top_margin - bottom_margin) / rows
    inner_pad = 3 * mm

    resp = HttpResponse(content_type='application/pdf')
    resp['Content-Disposition'] = 'attachment; filename="barcodes.pdf"'
    c = canvas.Canvas(resp, pagesize=A4)
    c.setTitle("Barcode Labels")

    per_page = cols * rows

    for i, (p, code_val) in enumerate(items):
        cell = i % per_page
        row = cell // cols
        col = cell % cols

        if i and cell == 0:
            c.showPage()

        lx = left_margin + col * label_w
        ly = page_h - top_margin - (row + 1) * label_h

        c.saveState()
        c.setLineWidth(0.6)
        c.setDash(1, 2)
        c.rect(lx, ly, label_w, label_h, stroke=1, fill=0)
        c.restoreState()

        name_font, name_size = 'Helvetica', 8
        name_max_w = label_w - 2 * inner_pad
        name_lines = simpleSplit(p.name or '', name_font, name_size, name_max_w)[:2]

        c.setFont(name_font, name_size)
        y_text = ly + label_h - inner_pad - name_size
        for line in name_lines:
            c.drawCentredString(lx + label_w / 2.0, y_text, line)
            y_text -= (name_size + 1)

        barcode_top = y_text - 2
        min_bar_h = 10 * mm
        bar_y = ly + inner_pad + 16
        barcode_height = max(min_bar_h, barcode_top - bar_y)

        try:
            if sym == 'ean13' and _ean13_normalize(code_val):
                code_norm = _ean13_normalize(code_val)
                d = createBarcodeDrawing('EAN13', value=code_norm, barHeight=barcode_height, humanReadable=False)
                avail_w = label_w - 2 * inner_pad
                scale = min(1.0, avail_w / float(d.width)) if d.width else 1.0
                dx = lx + (label_w - d.width * scale) / 2.0
                c.saveState()
                c.translate(dx, bar_y)
                c.scale(scale, 1.0)
                renderPDF.draw(d, c, 0, 0)
                c.restoreState()
                c.setFont('Helvetica', 8)
                c.drawCentredString(lx + label_w / 2.0, ly + inner_pad + 2, code_norm)
            else:
                tentative_bw = max(0.18, (label_w - 2 * inner_pad) / 220.0)
                b = code128.Code128(str(code_val), barHeight=barcode_height, barWidth=tentative_bw)
                bw = float(b.width)
                bx = lx + (label_w - bw) / 2.0
                b.drawOn(c, bx, bar_y)
                c.setFont('Helvetica', 8)
                c.drawCentredString(lx + label_w / 2.0, ly + inner_pad + 2, str(code_val))
        except Exception:
            c.setFont('Helvetica', 8)
            c.drawCentredString(lx + label_w / 2.0, ly + label_h / 2.0, str(code_val))

    c.save()
    return resp

# --- Bulk stock adjust (CSV) ---
@login_required
@permission_required('posapp.can_adjust_stock', raise_exception=True)
def stock_bulk_adjust(request):
    """
    Upload a CSV to adjust stock in bulk.

    Accepts headers (case-insensitive):
      - code OR barcode  (identify product, at least one required)
      - delta            (signed int; add/remove this quantity)
      - new_stock        (int; set absolute stock; aliases: set_to, target)
      - note             (optional)
    """
    from .models import Product, StockMove  # local to avoid import cycles

    # Optional: sample CSV
    if request.GET.get('sample'):
        resp = HttpResponse(content_type='text/csv')
        resp['Content-Disposition'] = 'attachment; filename="stock_adjust_sample.csv"'
        resp.write('code,barcode,delta,new_stock,note\n')
        resp.write('PEN001,8901234567890,10,,Initial load\n')
        resp.write('NOTE001,,,-5,Damage write-off\n')
        return resp

    results, not_found, errors = [], [], []

    if request.method == 'POST' and 'file' in request.FILES:
        f = io.TextIOWrapper(request.FILES['file'].file, encoding='utf-8', newline='')
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            messages.error(request, 'CSV appears to have no header row.')
            return redirect('stock_bulk_adjust')

        headers = { (h or '').strip().lower(): h for h in reader.fieldnames }

        for row in reader:
            code = (row.get(headers.get('code','')) or '').strip() if 'code' in headers else ''
            barcode = (row.get(headers.get('barcode','')) or '').strip() if 'barcode' in headers else ''
            note = (row.get(headers.get('note','')) or '').strip() if 'note' in headers else ''
            delta_raw = (row.get(headers.get('delta','')) or '').strip() if 'delta' in headers else ''

            new_stock_raw = None
            for k in ('new_stock','set_to','target'):
                if k in headers:
                    new_stock_raw = (row.get(headers.get(k,'')) or '').strip()
                    if new_stock_raw:
                        break

            # find product
            p = None
            if code:
                p = Product.objects.filter(code=code).first()
            if not p and barcode:
                p = Product.objects.filter(barcode=barcode).first()
            if not p:
                not_found.append({'code': code, 'barcode': barcode})
                continue

            # current stock
            stock_now = p.stockmove_set.aggregate(s=Sum('change'))['s'] or 0

            # compute change
            change = None
            if delta_raw:
                try:
                    change = int(float(delta_raw))
                except Exception:
                    errors.append({'code': p.code, 'barcode': p.barcode, 'error': f'Invalid delta: {delta_raw}'})
                    continue
            elif new_stock_raw:
                try:
                    target = int(float(new_stock_raw))
                except Exception:
                    errors.append({'code': p.code, 'barcode': p.barcode, 'error': f'Invalid new_stock: {new_stock_raw}'})
                    continue
                change = target - stock_now
            else:
                # nothing to do on this row
                continue

            if change == 0:
                results.append({'code': p.code, 'barcode': p.barcode, 'old': stock_now, 'change': 0, 'new': stock_now, 'note': note})
                continue

            StockMove.objects.create(product=p, change=change, reason='adjustment', ref=(note or 'CSV bulk')[:64])
            new_qty = stock_now + change
            results.append({'code': p.code, 'barcode': p.barcode, 'old': stock_now, 'change': change, 'new': new_qty, 'note': note})

        return render(request, 'products/stock_bulk_adjust.html', {
            'results': results,
            'not_found': not_found,
            'errors': errors,
        })

    # GET: render upload form
    return render(request, 'products/stock_bulk_adjust.html')

# --- Bulk stock CSV template (download) ---
from django.contrib.auth.decorators import login_required, permission_required
from django.http import HttpResponse
import csv, io

@login_required
@permission_required('posapp.can_adjust_stock', raise_exception=True)
def stock_bulk_template(request):
    """
    Download a CSV template for bulk stock adjustments.

    Columns:
      code, barcode, delta, new_stock, note

    - Provide either code or barcode to identify the product.
    - Use 'delta' to add/remove units (signed integer).
    - Or use 'new_stock' to set absolute stock (integer).
    - 'note' is optional.
    """
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(['code','barcode','delta','new_stock','note'])
    w.writerow(['PEN001','8901234567890','10','', 'Initial load'])
    w.writerow(['NOTE001','', '', '25', 'Set absolute stock to 25'])
    w.writerow(['GLUE10','', '-2','', 'Damaged / write-off'])
    data = buf.getvalue()
    buf.close()

    resp = HttpResponse(data, content_type='text/csv')
    resp['Content-Disposition'] = 'attachment; filename="stock_adjust_template.csv"'
    return resp

from django.http import FileResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required, permission_required
from pathlib import Path
from posapp.utils.backups import create_db_backup

@login_required
@permission_required('posapp.can_manage_settings', raise_exception=True)  # or a new 'can_backup_db'
def backup_download_now(request):
    # Create a fresh backup and stream it
    fpath = create_db_backup()
    return FileResponse(
        open(fpath, "rb"),
        as_attachment=True,
        filename=fpath.name,
        content_type="application/gzip"
    )
