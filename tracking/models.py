from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from uuid import uuid4


class LocationUpdate(models.Model):
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="locations",
    )
    lat = models.FloatField()
    lng = models.FloatField()
    address = models.CharField(max_length=255, blank=True)
    battery = models.IntegerField(null=True, blank=True)
    charging = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.child.username} @ {self.lat:.4f},{self.lng:.4f}"


class SafeZone(models.Model):
    SCHEDULE_ALWAYS = "always"
    SCHEDULE_DAYS = "days"
    SCHEDULE_CHOICES = [
        (SCHEDULE_ALWAYS, "Always"),
        (SCHEDULE_DAYS, "Specific days"),
    ]

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="safe_zones",
    )
    name = models.CharField(max_length=100)
    lat = models.FloatField()
    lng = models.FloatField()
    radius = models.FloatField(default=200.0)  # in meters
    active = models.BooleanField(default=True)
    schedule_type = models.CharField(
        max_length=16,
        choices=SCHEDULE_CHOICES,
        default=SCHEDULE_ALWAYS,
    )
    active_days = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        normalized_days = []
        for day in self.active_days or []:
            try:
                value = int(day)
            except (TypeError, ValueError) as exc:
                raise ValidationError({"active_days": "Days must be numbers from 1 to 7."}) from exc
            if value < 1 or value > 7:
                raise ValidationError({"active_days": "Days must be between 1 and 7."})
            if value not in normalized_days:
                normalized_days.append(value)

        if self.schedule_type == self.SCHEDULE_ALWAYS:
            self.active_days = []
        else:
            if not normalized_days:
                raise ValidationError(
                    {"active_days": "Select at least one weekday for scheduled zones."}
                )
            self.active_days = normalized_days

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def is_active_on(self, reference_dt=None):
        if not self.active:
            return False
        if self.schedule_type == self.SCHEDULE_ALWAYS:
            return True
        if not self.active_days:
            return False

        if reference_dt is None:
            current_date = timezone.localdate()
        elif hasattr(reference_dt, "date"):
            if timezone.is_aware(reference_dt):
                current_date = timezone.localtime(reference_dt).date()
            else:
                current_date = reference_dt.date()
        else:
            current_date = reference_dt

        return current_date.isoweekday() in {int(day) for day in self.active_days}

    def __str__(self):
        return f"{self.name} ({self.parent.username})"


class DeviceStatus(models.Model):
    child = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_status",
    )
    device_name = models.CharField(max_length=120, blank=True)
    manufacturer = models.CharField(max_length=120, blank=True)
    model = models.CharField(max_length=120, blank=True)
    platform = models.CharField(max_length=32, blank=True)
    os_version = models.CharField(max_length=64, blank=True)
    timezone = models.CharField(max_length=64, blank=True)
    battery = models.IntegerField(null=True, blank=True)
    charging = models.BooleanField(default=False)
    usage_access_granted = models.BooleanField(default=False)
    synced_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.child.username} device"


class DeviceDailySummary(models.Model):
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="daily_usage_summaries",
    )
    usage_date = models.DateField()
    total_minutes = models.PositiveIntegerField(default=0)
    over_limit_apps = models.PositiveIntegerField(default=0)
    synced_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-usage_date"]
        unique_together = [("child", "usage_date")]

    def __str__(self):
        return f"{self.child.username} {self.usage_date}: {self.total_minutes}m"


class AppLimit(models.Model):
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="app_limits",
    )
    package_name = models.CharField(max_length=255)
    app_name = models.CharField(max_length=120)
    daily_limit_minutes = models.PositiveIntegerField(default=60)
    enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["app_name", "package_name"]
        unique_together = [("child", "package_name")]

    def __str__(self):
        return f"{self.child.username}: {self.app_name}"


class BlockedApp(models.Model):
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="blocked_apps",
    )
    package_name = models.CharField(max_length=255)
    app_name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("child", "package_name")]
        ordering = ["app_name"]

    def __str__(self):
        return f"{self.child.username}: blocked {self.app_name}"


class AppUsageSnapshot(models.Model):
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="app_usage_snapshots",
    )
    usage_date = models.DateField()
    package_name = models.CharField(max_length=255)
    app_name = models.CharField(max_length=120)
    usage_minutes = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-usage_date", "-usage_minutes", "app_name"]
        unique_together = [("child", "usage_date", "package_name")]

    def __str__(self):
        return f"{self.child.username}: {self.app_name} {self.usage_date}"


class RemoteDeviceCommand(models.Model):
    TYPE_LOUD = "loud"
    TYPE_LOUD_STOP = "loud_stop"
    TYPE_AROUND_START = "around_start"
    TYPE_AROUND_STOP = "around_stop"
    TYPE_SYNC_BLOCKED_APPS = "sync_blocked_apps"
    TYPE_CHOICES = [
        (TYPE_LOUD, "Loud"),
        (TYPE_LOUD_STOP, "Loud Stop"),
        (TYPE_AROUND_START, "Around Start"),
        (TYPE_AROUND_STOP, "Around Stop"),
        (TYPE_SYNC_BLOCKED_APPS, "Sync Blocked Apps"),
    ]

    STATUS_PENDING = "pending"
    STATUS_DELIVERED = "delivered"
    STATUS_COMPLETED = "completed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_DELIVERED, "Delivered"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_FAILED, "Failed"),
    ]

    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="device_commands",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="issued_device_commands",
    )
    command_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
    )
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.child.username}: {self.command_type} ({self.status})"


class Alert(models.Model):
    """Persistent server-side alert for parent notification."""

    TYPE_BATTERY_LOW = "battery_low"
    TYPE_SAFE_ZONE_EXIT = "safe_zone_exit"
    TYPE_SOS = "sos"
    TYPE_CHAT_MESSAGE = "chat_message"
    TYPE_TASK_ASSIGNED = "task_assigned"
    TYPE_CHOICES = [
        (TYPE_BATTERY_LOW, "Battery Low"),
        (TYPE_SAFE_ZONE_EXIT, "Safe Zone Exit"),
        (TYPE_SOS, "SOS"),
        (TYPE_CHAT_MESSAGE, "Chat Message"),
        (TYPE_TASK_ASSIGNED, "Task Assigned"),
    ]

    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="alerts",
    )
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parent_alerts",
    )
    alert_type = models.CharField(max_length=32, choices=TYPE_CHOICES)
    title = models.CharField(max_length=200)
    message = models.CharField(max_length=500, blank=True)
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.child.username}: {self.alert_type} ({self.created_at})"


class AroundAudioClip(models.Model):
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="around_audio_clips",
    )
    session_token = models.CharField(max_length=64, default="", db_index=True)
    audio = models.FileField(upload_to="around_audio/")
    duration_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    @staticmethod
    def new_session_token():
        return uuid4().hex

    def __str__(self):
        return f"{self.child.username}: around audio {self.id}"
