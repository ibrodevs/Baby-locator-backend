from rest_framework import serializers

from .models import (
    AppLimit,
    AppUsageSnapshot,
    DeviceDailySummary,
    DeviceStatus,
    LocationUpdate,
    SafeZone,
)


class LocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationUpdate
        fields = ["id", "child", "lat", "lng", "address", "battery", "active", "created_at"]
        read_only_fields = ["id", "child", "created_at"]


class LocationInputSerializer(serializers.Serializer):
    lat = serializers.FloatField()
    lng = serializers.FloatField()
    address = serializers.CharField(required=False, allow_blank=True, default="")
    battery = serializers.IntegerField(required=False, allow_null=True)
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
