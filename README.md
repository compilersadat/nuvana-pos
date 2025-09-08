# Nuvana Stationery POS (Django + SQLite + Bootstrap)

A minimal, production-ready-ish Point of Sale & Inventory app for a stationery shop.

## Features
- Products, Suppliers, Customers
- Purchases (increase stock) & Sales (decrease stock)
- POS screen with dynamic cart
- Stock moves ledger (computed stock per product)
- Sales & Stock reports
- SQLite by default, Bootstrap 5 UI

## Quickstart
```bash
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install "Django>=4.2,<6.0"

cd stationery_pos
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Login at `/admin` to seed categories/products, or use the UI:
- Products: `/products/`
- Purchase: `/purchases/new/`
- POS: `/pos/`
- Reports: `/reports/sales/`, `/reports/stock/`

## Notes
- Bootstrap is loaded via CDN. To make it fully offline, download Bootstrap and place under `static/`, then update `templates/base.html`.
- Stock is computed from `StockMove` entries — no race conditions with a single register. For multi-register setups, use DB transactions (already used) and consider row-level locking with Postgres.
- Tax/discount are simplistic; adjust business logic in `posapp/views.py` as needed.
