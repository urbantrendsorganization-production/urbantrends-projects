from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ["phone"]
    list_display = ["phone", "full_name", "email", "is_active", "date_joined"]
    search_fields = ["phone", "full_name", "email"]
    fieldsets = [
        (None, {"fields": ["phone", "password"]}),
        ("Personal", {"fields": ["full_name", "email"]}),
        (
            "Permissions",
            {"fields": ["is_active", "is_staff", "is_superuser", "groups", "user_permissions"]},
        ),
        ("Dates", {"fields": ["last_login", "date_joined"]}),
    ]
    add_fieldsets = [
        (None, {"classes": ["wide"], "fields": ["phone", "full_name", "password1", "password2"]}),
    ]
