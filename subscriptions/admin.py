from django.contrib import admin

from .models import RevenueCatWebhookEvent


@admin.register(RevenueCatWebhookEvent)
class RevenueCatWebhookEventAdmin(admin.ModelAdmin):
    list_display = ("event_type", "event_id", "app_user_id", "user", "processed_at")
    list_filter = ("event_type", "environment", "processed_at")
    search_fields = ("event_id", "app_user_id", "product_id")
    readonly_fields = ("raw_payload", "processed_at")
