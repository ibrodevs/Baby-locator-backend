from rest_framework import serializers

from .models import (
    Alert,
    AppLimit,
    AppUsageSnapshot,
    AroundAudioClip,
    BlockedApp,
    DeviceDailySummary,
    DeviceStatus,
    LocationUpdate,
    RemoteDeviceCommand,
    SafeZone,
)


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationUpdate
        fields = [
            "id",
            "child",
            "lat",
            "lng",
            "address",
            "battery",
            "charging",
            "active",
            "created_at",
        ]
        read_only_fields = ["id", "child", "created_at"]


class LocationInputSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    address = serializers.CharField(required=False, allow_blank=True, default="")
    battery = serializers.IntegerField(required=False, allow_null=True)
    charging = serializers.BooleanField(required=False, default=False)
    active = serializers.BooleanField(required=False, default=True)


class SafeZoneSerializer(serializers.ModelSerializer):
    schedule_type = serializers.ChoiceField(
        choices=SafeZone.SCHEDULE_CHOICES,
        required=False,
    )
    active_days = serializers.ListField(
        child=serializers.IntegerField(min_value=1, max_value=7),
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = SafeZone
        fields = [
            "id",
            "parent",
            "name",
            "lat",
            "lng",
            "radius",
            "active",
            "schedule_type",
            "active_days",
            "created_at",
        ]
        read_only_fields = ["id", "parent", "created_at"]

    def validate(self, attrs):
        schedule_type = attrs.get(
            "schedule_type",
            getattr(self.instance, "schedule_type", SafeZone.SCHEDULE_ALWAYS),
        )
        active_days = attrs.get(
            "active_days",
            getattr(self.instance, "active_days", []),
        )

        if schedule_type == SafeZone.SCHEDULE_ALWAYS:
            attrs["active_days"] = []
        elif not active_days:
            raise serializers.ValidationError(
                {"active_days": "Select at least one weekday."}
            )
        else:
            attrs["active_days"] = sorted({int(day) for day in active_days})

        return attrs


class DeviceStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceStatus
        fields = [
            "id",
            "child",
            "device_name",
            "manufacturer",
            "model",
            "platform",
            "os_version",
            "timezone",
            "battery",
            "charging",
            "usage_access_granted",
            "synced_at",
        ]
        read_only_fields = ["id", "child", "synced_at"]


class DeviceDailySummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceDailySummary
        fields = [
            "id",
            "child",
            "usage_date",
            "total_minutes",
            "over_limit_apps",
            "synced_at",
        ]
        read_only_fields = ["id", "child", "synced_at"]


class AppLimitSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppLimit
        fields = [
            "id",
            "child",
            "package_name",
            "app_name",
            "daily_limit_minutes",
            "enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "child", "created_at", "updated_at"]


class AppLimitWriteSerializer(serializers.Serializer):
    package_name = serializers.CharField()
    app_name = serializers.CharField(required=False, allow_blank=True, default="")
    daily_limit_minutes = serializers.IntegerField(min_value=0)
    enabled = serializers.BooleanField(required=False, default=True)


class AppUsageSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppUsageSnapshot
        fields = [
            "id",
            "child",
            "usage_date",
            "package_name",
            "app_name",
            "usage_minutes",
            "last_used_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "child", "created_at", "updated_at"]


class AppUsageSyncItemSerializer(serializers.Serializer):
    package_name = serializers.CharField()
    app_name = serializers.CharField(required=False, allow_blank=True, default="")
    usage_minutes = serializers.IntegerField(min_value=0)
    last_used_at = serializers.DateTimeField(required=False, allow_null=True)


class DeviceUsageDaySerializer(serializers.Serializer):
    date = serializers.DateField()
    total_minutes = serializers.IntegerField(min_value=0, required=False)
    apps = AppUsageSyncItemSerializer(many=True, required=False)


class DeviceStatsSyncSerializer(serializers.Serializer):
    device_name = serializers.CharField(required=False, allow_blank=True)
    manufacturer = serializers.CharField(required=False, allow_blank=True)
    model = serializers.CharField(required=False, allow_blank=True)
    platform = serializers.CharField(required=False, allow_blank=True)
    os_version = serializers.CharField(required=False, allow_blank=True)
    timezone = serializers.CharField(required=False, allow_blank=True)
    battery = serializers.IntegerField(required=False, allow_null=True, min_value=0, max_value=100)
    charging = serializers.BooleanField(required=False)
    usage_access_granted = serializers.BooleanField(required=False, default=False)
    days = DeviceUsageDaySerializer(many=True, required=False)


class RemoteDeviceCommandSerializer(serializers.ModelSerializer):
    class Meta:
        model = RemoteDeviceCommand
        fields = [
            "id",
            "child",
            "created_by",
            "command_type",
            "payload",
            "status",
            "error_message",
            "created_at",
            "delivered_at",
            "completed_at",
        ]
        read_only_fields = fields


class RemoteDeviceCommandActionSerializer(serializers.Serializer):
    command_type = serializers.ChoiceField(choices=RemoteDeviceCommand.TYPE_CHOICES)
    payload = serializers.JSONField(required=False)


class RemoteDeviceCommandCompleteSerializer(serializers.Serializer):
    success = serializers.BooleanField(required=False, default=True)
    error_message = serializers.CharField(required=False, allow_blank=True, default="")


class AlertSerializer(serializers.ModelSerializer):
    child_name = serializers.SerializerMethodField()

    class Meta:
        model = Alert
        fields = [
            "id",
            "child",
            "parent",
            "alert_type",
            "title",
            "message",
            "read",
            "child_name",
            "created_at",
        ]
        read_only_fields = fields

    def get_child_name(self, obj):
        return obj.child.display_name or obj.child.username


class AroundAudioClipSerializer(serializers.ModelSerializer):
    audio_url = serializers.SerializerMethodField()

    class Meta:
        model = AroundAudioClip
        fields = [
            "id",
            "child",
            "session_token",
            "audio_url",
            "duration_seconds",
            "created_at",
        ]
        read_only_fields = fields

    def get_audio_url(self, obj):
        request = self.context.get("request")
        if not obj.audio:
            return ""
        url = obj.audio.url
        return request.build_absolute_uri(url) if request else url


class BlockedAppSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockedApp
        fields = ["id", "package_name", "app_name", "created_at"]
        read_only_fields = fields


class BlockAppSerializer(serializers.Serializer):
    package_name = serializers.CharField(max_length=255)
    app_name = serializers.CharField(max_length=120)
