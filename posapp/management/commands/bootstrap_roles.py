# posapp/management/commands/bootstrap_roles.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType

APP = 'posapp'

ROLES = {
    "Admin": "ALL",  # full access
    "Manager": [
        f"{APP}.can_pos", f"{APP}.can_view_reports", f"{APP}.can_print_barcodes",
        f"{APP}.can_adjust_stock", f"{APP}.can_manage_purchases",
        # Built-ins for CRUD on core models
        f"{APP}.view_product", f"{APP}.add_product", f"{APP}.change_product",
        f"{APP}.view_sale", f"{APP}.add_sale", f"{APP}.change_sale",
        f"{APP}.view_purchase", f"{APP}.add_purchase", f"{APP}.change_purchase",
        f"{APP}.view_customer", f"{APP}.add_customer", f"{APP}.change_customer",
        f"{APP}.view_supplier", f"{APP}.add_supplier", f"{APP}.change_supplier",
    ],
    "Cashier": [
        f"{APP}.can_pos", f"{APP}.can_print_barcodes",
        f"{APP}.view_product", f"{APP}.view_sale", f"{APP}.add_sale",
        f"{APP}.view_customer",
    ],
    "Viewer": [
        f"{APP}.can_view_reports",
        f"{APP}.view_product", f"{APP}.view_sale", f"{APP}.view_purchase",
    ],
}

class Command(BaseCommand):
    help = "Create default RBAC roles (Groups) and assign permissions."

    def handle(self, *args, **opts):
        # All permissions for this app
        all_app_perms = Permission.objects.filter(content_type__app_label=APP)
        all_codenames = set(all_app_perms.values_list('codename', flat=True))

        for role, perms in ROLES.items():
            group, _ = Group.objects.get_or_create(name=role)
            if perms == "ALL":
                group.permissions.set(all_app_perms)
                self.stdout.write(self.style.SUCCESS(f"{role}: assigned ALL ({len(all_codenames)})"))
                continue

            want = set(p.split(".", 1)[-1] for p in perms)
            missing = want - all_codenames
            if missing:
                self.stdout.write(self.style.WARNING(f"{role}: missing permissions {sorted(missing)} (will skip)"))

            assign = Permission.objects.filter(
                content_type__app_label=APP,
                codename__in=list(want & all_codenames)
            )
            group.permissions.set(assign)
            self.stdout.write(self.style.SUCCESS(f"{role}: assigned {assign.count()} permissions"))

        self.stdout.write(self.style.SUCCESS("RBAC bootstrap complete."))
