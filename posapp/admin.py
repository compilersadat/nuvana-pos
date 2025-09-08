from django.contrib import admin
from .models import Category, Product, Supplier, Customer, Purchase, PurchaseItem, Sale, SaleItem, StockMove

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ['name']

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['code','barcode','name','category','unit_price','cost_price','tax_percent','stock','is_active']
    list_filter = ['category','is_active']
    search_fields = ['code','barcode','name']

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    search_fields = ['name','phone','email']

@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    search_fields = ['name','phone','email']

class PurchaseItemInline(admin.TabularInline):
    model = PurchaseItem
    extra = 0

@admin.register(Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ['id','supplier','date','total']
    inlines = [PurchaseItemInline]

class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 0

@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['id','customer','date','total','payment_method','paid_amount','is_return']
    inlines = [SaleItemInline]

@admin.register(StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ['product','change','reason','ref','created_at']
    list_filter = ['reason']
