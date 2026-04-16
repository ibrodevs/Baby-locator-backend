from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "role", "display_name", "parent", "is_staff")
    list_filter = ("role",)
    fieldsets = UserAdmin.fieldsets + (
        ("Kid Security", {"fields": ("role", "display_name", "parent")}),
    )
