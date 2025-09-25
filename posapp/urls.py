from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),

    # Products & Masters
    path('products/', views.product_list, name='product_list'),
    path('products/new/', views.product_create, name='product_create'),
    path('products/<int:pk>/edit/', views.product_update, name='product_update'),
    path('products/<int:pk>/add_stock/', views.product_add_stock, name='product_add_stock'),
    path('stock/add/', views.product_add_stock, name='stock_add'),
    path('stock/bulk/', views.stock_bulk_adjust, name='stock_bulk_adjust'),
    path('stock/bulk/template/', views.stock_bulk_template, name='stock_bulk_template'),
    path('products/export/', views.product_export, name='product_export'),
    path('products/import/', views.product_import, name='product_import'),
    path('products/barcodes/', views.barcode_labels, name='product_barcodes'),

    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/new/', views.supplier_create, name='supplier_create'),

    path('customers/', views.customer_list, name='customer_list'),
    path('customers/new/', views.customer_create, name='customer_create'),

    # Purchases
    path('purchases/new/', views.purchase_create, name='purchase_create'),

    # Sales (POS)
    path('pos/', views.pos_sale_create, name='pos_sale_create'),
    path('invoice/<int:sale_id>/', views.invoice_view, name='invoice_view'),

    # Reports
    path('reports/sales/', views.sales_report, name='sales_report'),
    path('reports/stock/', views.stock_report, name='stock_report'),
    path('reports/purchases/', views.purchase_report, name='purchase_report'),

    path('stock/bulk_adjust/', views.stock_bulk_adjust, name='stock_bulk_adjust'),

    path('sales/', views.sales_list, name='sales_list'),
    path('sales/<int:sale_id>/edit/', views.sale_update, name='sale_update'),
    # ADD to your urlpatterns
    path('security/users/', views.security_users, name='security_users'),
    path('security/users/new/', views.security_user_new, name='security_user_new'),
    path('security/users/<int:user_id>/edit/', views.security_user_edit, name='security_user_edit'),

    path('security/roles/', views.security_roles, name='security_roles'),
    path('security/roles/new/', views.security_role_new, name='security_role_new'),
    path('security/roles/<int:role_id>/edit/', views.security_role_edit, name='security_role_edit'),
    path('settings/', views.settings_general, name='settings_general'),

    path('credit/receive/', views.receive_payment, name='receive_payment'),
    path('credit/charge/', views.customer_charge, name='customer_charge'),
    path('credit/statement/', views.customer_statement, name='customer_statement'),
    path('settings/', views.settings_general, name='settings_general'),
    path('api/customer/<int:customer_id>/balance/', views.customer_balance_api, name='customer_balance_api'),

    path('settings/backup/now/', views.backup_download_now, name='backup_download_now'),

]
