from django.contrib import admin

from orgs.admin import OrgScopedAdmin
from shops.models import (
    Leave,
    OpeningHours,
    Service,
    Shop,
    ShopClosure,
    Staff,
    StaffService,
    WorkingHours,
)


@admin.register(Shop)
class ShopAdmin(OrgScopedAdmin):
    list_display = ["name", "slug", "organization", "is_active", "buffer_minutes"]
    list_filter = ["is_active"]
    search_fields = ["name", "slug"]


@admin.register(Service)
class ServiceAdmin(OrgScopedAdmin):
    list_display = [
        "name",
        "shop",
        "price",
        "deposit_mode",
        "deposit_value",
        "deposit_amount",
        "is_active",
    ]
    list_filter = ["deposit_mode", "is_active", "is_publicly_listed"]
    search_fields = ["name"]
    # Written by shops.money.deposit_amount on save. Editing it by hand would
    # make the stored figure disagree with the rule that produced it.
    readonly_fields = ["deposit_amount"]


@admin.register(Staff)
class StaffAdmin(OrgScopedAdmin):
    list_display = ["display_name", "shop", "is_bookable", "is_active"]
    list_filter = ["is_bookable", "is_active"]


@admin.register(StaffService)
class StaffServiceAdmin(OrgScopedAdmin):
    list_display = ["staff", "service", "duration_override_minutes", "is_offered"]


for model in (OpeningHours, ShopClosure, WorkingHours, Leave):
    admin.site.register(model, OrgScopedAdmin)
