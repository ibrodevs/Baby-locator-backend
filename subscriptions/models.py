from django.conf import settings
from django.db import models


class RevenueCatWebhookEvent(models.Model):
    event_id = models.CharField(max_length=128, unique=True, db_index=True)
    event_type = models.CharField(max_length=64, db_index=True)
    app_user_id = models.CharField(max_length=128, blank=True, default="", db_index=True)
    environment = models.CharField(max_length=32, blank=True, default="")
    product_id = models.CharField(max_length=128, blank=True, default="")
    entitlement_ids = models.JSONField(default=list, blank=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="revenuecat_webhook_events",
    )
    raw_payload = models.JSONField(default=dict, blank=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.event_type}:{self.event_id}"
