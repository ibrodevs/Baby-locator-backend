from django.contrib import admin

from .models import AppLimit, AppUsageSnapshot, DeviceDailySummary, DeviceStatus, LocationUpdate


@admin.register(LocationUpdate)
class LocationUpdateAdmin(admin.ModelAdmin):
    list_display = ("child", "lat", "lng", "address", "battery", "active", "created_at")
    list_filter = ("active", "child")
    search_fields = ("child__username", "address")


@admin.register(DeviceStatus)
class DeviceStatusAdmin(admin.ModelAdmin):
    list_display = (
        "child",
        "device_name",
        "platform",
        "battery",
        "charging",
        "usage_access_granted",
        "synced_at",
    )
    list_filter = ("platform", "usage_access_granted", "charging")
    search_fields = ("child__username", "device_name", "model", "manufacturer")


@admin.register(DeviceDailySummary)
class DeviceDailySummaryAdmin(admin.ModelAdmin):
    list_display = ("child", "usage_date", "total_minutes", "over_limit_apps", "synced_at")
    list_filter = ("usage_date", "child")
    search_fields = ("child__username",)


@admin.register(AppLimit)
class AppLimitAdmin(admin.ModelAdmin):
    list_display = ("child", "app_name", "daily_limit_minutes", "enabled", "updated_at")
    list_filter = ("enabled", "child")
    search_fields = ("child__username", "app_name", "package_name")


@admin.register(AppUsageSnapshot)
class AppUsageSnapshotAdmin(admin.ModelAdmin):
    list_display = ("child", "usage_date", "app_name", "usage_minutes", "last_used_at")
    list_filter = ("usage_date", "child")
    search_fields = ("child__username", "app_name", "package_name")
