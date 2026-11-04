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
    status = models.CharField(max_length=16, default="pending", db_index=True)
    error = models.CharField(max_length=200, blank=True, default="")

    def __str__(self):
        return f"{self.event_type}:{self.event_id}"


class CustomerEntitlement(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="store_entitlements")
    product_id = models.CharField(max_length=200)
    expires_at = models.DateTimeField(null=True, blank=True)
    lifetime = models.BooleanField(default=False)
    revoked = models.BooleanField(default=False)
    updated_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "product_id"], name="unique_customer_product")]


class LiteAccessGrant(models.Model):
    """Server-owned family license; HTTP headers cannot create this permission."""
    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="lite_access_grant")
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    source = models.CharField(max_length=32, default="admin")
    updated_at = models.DateTimeField(auto_now=True)
