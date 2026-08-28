from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = (
        "username",
        "role",
        "display_name",
        "is_premium",
        "premium_entitlement",
        "parent",
        "is_staff",
    )
    list_filter = ("role", "is_premium")
    fieldsets = UserAdmin.fieldsets + (
        (
            "Family security",
            {
                "fields": (
                    "role",
                    "display_name",
                    "parent",
                    "is_premium",
                    "premium_entitlement",
                    "premium_product_id",
                    "premium_expires_at",
                )
            },
        ),
    )

