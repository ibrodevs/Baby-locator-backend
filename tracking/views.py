import calendar
import logging
import math
import mimetypes
import re
from datetime import date as dt_date
from datetime import timedelta

from django.db import transaction
from django.http import FileResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import UserSerializer

from .live_audio import live_audio_broker
from .models import (
    Alert,
    AppIcon,
    AppLimit,
    AppUsageSnapshot,
    AroundAudioClip,
    BlockedApp,
    DeviceDailySummary,
    DeviceStatus,
    LocationUpdate,
    MonitorSession,
    RemoteDeviceCommand,
    SafeZone,
    SignalingMessage,
)
from .fcm import send_command_push, send_notification_push
from .serializers import (
    AlertSerializer,
    AppLimitSerializer,
    AppLimitWriteSerializer,
    AroundAudioClipSerializer,
    BlockAppSerializer,
    BlockedAppSerializer,
    DeviceStatsSyncSerializer,
    LocationInputSerializer,
    LocationSerializer,
    RemoteDeviceCommandActionSerializer,
    RemoteDeviceCommandCompleteSerializer,
    RemoteDeviceCommandSerializer,
    SafeZoneSerializer,
)

logger = logging.getLogger(__name__)

LIVE_AUDIO_DEFAULT_SAMPLE_RATE = 16000
LIVE_AUDIO_DEFAULT_CHANNELS = 1
LIVE_AUDIO_FORMAT = "pcm_s16le"


def _haversine_m(lat1, lng1, lat2, lng2):
    """Return distance in metres between two lat/lng points."""
    R = 6371000
    rlat1, rlat2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _resolve_child_for_request(request, child_id):
    child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
    if request.user.role == User.ROLE_PARENT and child.parent_id != request.user.id:
        return None
    if request.user.role == User.ROLE_CHILD and request.user.id != child.id:
        return None
    return child


def _ensure_parent_child_relationship(parent, child):
    return (
        parent.role == User.ROLE_PARENT
        and child.role == User.ROLE_CHILD
        and child.parent_id == parent.id
    )


def _parse_selected_date(raw_value, fallback):
    if not raw_value:
        return fallback
    parsed = parse_date(raw_value)
    return parsed or fallback


def _sanitize_address(value):
    address = (value or "").strip()
    if not address:
        return ""
    coordinate_pattern = r"^-?\d+(?:\.\d+)?,\s*-?\d+(?:\.\d+)?$"
    if re.fullmatch(coordinate_pattern, address):
        return ""
    return address


def _coerce_positive_int(value, default):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _parse_selected_month(raw_value, fallback):
    if not raw_value:
        return fallback
    try:
        year_str, month_str = raw_value.split("-", 1)
        return dt_date(int(year_str), int(month_str), 1)
    except (TypeError, ValueError):
        return fallback


def _match_zone_for_location(zones, location):
    for zone in zones:
        if not zone.is_active_on(location.created_at):
            continue
        if _haversine_m(location.lat, location.lng, zone.lat, zone.lng) <= zone.radius:
            return zone
    return None


class SafeZoneViewSet(viewsets.ModelViewSet):
    """CRUD for Parent's Safe Zones."""

    serializer_class = SafeZoneSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Parents see only their zones. Children see zones of their parent.
        if self.request.user.role == User.ROLE_PARENT:
            return SafeZone.objects.filter(parent=self.request.user)
        elif self.request.user.role == User.ROLE_CHILD and self.request.user.parent:
            return SafeZone.objects.filter(parent=self.request.user.parent)
        return SafeZone.objects.none()

    def perform_create(self, serializer):
        serializer.save(parent=self.request.user)


class ShareLocationView(APIView):
    """Child posts their current location."""

    BATTERY_LOW_THRESHOLD = 20
    # Suppress duplicate battery_low alerts for 30 minutes.
    BATTERY_ALERT_COOLDOWN = timedelta(minutes=30)
    # Suppress duplicate safe zone exit alerts for 10 minutes per zone.
    ZONE_EXIT_COOLDOWN = timedelta(minutes=10)

    def post(self, request):
        if request.user.role != User.ROLE_CHILD:
            return Response({"detail": "children only"}, status=403)
        s = LocationInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        address = _sanitize_address(s.validated_data.get("address", ""))
        loc = LocationUpdate.objects.create(
            child=request.user,
            lat=s.validated_data["lat"],
            lng=s.validated_data["lng"],
            address=address,
            battery=s.validated_data.get("battery"),
            charging=s.validated_data.get("charging", False),
            active=s.validated_data.get("active", True),
        )

        # --- Generate alerts for the parent ---
        parent = request.user.parent
        if parent:
            self._check_battery_alert(request.user, parent, loc)
            self._check_zone_exit_alert(request.user, parent, loc)

        return Response(LocationSerializer(loc).data, status=201)

    def _check_battery_alert(self, child, parent, loc):
        if loc.battery is None or loc.battery > self.BATTERY_LOW_THRESHOLD:
            return
        cutoff = timezone.now() - self.BATTERY_ALERT_COOLDOWN
        already = Alert.objects.filter(
            child=child,
            parent=parent,
            alert_type=Alert.TYPE_BATTERY_LOW,
            created_at__gte=cutoff,
        ).exists()
        if already:
            return
        child_name = child.display_name or child.username
        Alert.objects.create(
            child=child,
            parent=parent,
            alert_type=Alert.TYPE_BATTERY_LOW,
            title=f"{child_name}: низкий заряд батареи",
            message=f"Уровень заряда {loc.battery}%",
        )

    def _check_zone_exit_alert(self, child, parent, loc):
        zones = list(SafeZone.objects.filter(parent=parent, active=True))
        if not zones:
            return
        # Check if child is currently inside any zone
        current_zone = _match_zone_for_location(zones, loc)
        if current_zone is not None:
            return  # Still inside a zone, no alert needed.

        # Check previous location to see if they WERE in a zone
        prev_loc = (
            child.locations.filter(created_at__lt=loc.created_at)
            .order_by("-created_at")
            .first()
        )
        if prev_loc is None:
            return
        prev_zone = _match_zone_for_location(zones, prev_loc)
        if prev_zone is None:
            return  # Was not in a zone before either

        # Child just left prev_zone — check cooldown
        cutoff = timezone.now() - self.ZONE_EXIT_COOLDOWN
        already = Alert.objects.filter(
            child=child,
            parent=parent,
            alert_type=Alert.TYPE_SAFE_ZONE_EXIT,
            message__contains=prev_zone.name,
            created_at__gte=cutoff,
        ).exists()
        if already:
            return
        child_name = child.display_name or child.username
        Alert.objects.create(
            child=child,
            parent=parent,
            alert_type=Alert.TYPE_SAFE_ZONE_EXIT,
            title=f"{child_name}: вышел из безопасной зоны",
            message=f"Покинул зону «{prev_zone.name}»",
        )


class ChildLatestLocationView(APIView):
    """Parent fetches latest location of a specific child."""

    def get(self, request, child_id):
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)
        loc = child.locations.first()
        if not loc:
            return Response({"detail": "no location yet"}, status=404)
        device_status = getattr(child, "device_status", None)
        data = LocationSerializer(loc).data
        if data.get("battery") is None and device_status:
            data["battery"] = device_status.battery
        if "charging" not in data:
            data["charging"] = device_status.charging if device_status else False
        elif data.get("charging") is None and device_status:
            data["charging"] = device_status.charging
        return Response(data)


class ChildLocationHistoryView(APIView):
    def get(self, request, child_id):
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)
        qs = child.locations.all()[:100]
        return Response(LocationSerializer(qs, many=True).data)


class AllChildrenLocationsView(APIView):
    """Parent fetches latest location of ALL their children in one call."""

    def get(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)

        children = request.user.children.all().order_by("id")
        result = []
        for child in children:
            loc = child.locations.first()
            device_status = getattr(child, "device_status", None)
            location_data = LocationSerializer(loc).data if loc else None
            battery = (
                location_data.get("battery")
                if location_data is not None and location_data.get("battery") is not None
                else (device_status.battery if device_status else None)
            )
            charging = (
                location_data.get("charging")
                if location_data is not None and location_data.get("charging") is not None
                else (device_status.charging if device_status else False)
            )
            entry = {
                "child": UserSerializer(child, context={"request": request}).data,
                "location": location_data,
                "battery": battery,
                "charging": charging,
            }
            result.append(entry)
        return Response(result)


class ChildActivityView(APIView):
    """Derive activity events from location history for a child."""
    permission_classes = [IsAuthenticated]

    def get(self, request, child_id):
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        # Get today's locations (oldest first for timeline derivation)
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        locations = list(
            child.locations.filter(created_at__gte=today).order_by("created_at")
        )

        # Get parent's safe zones for matching
        parent = child.parent if child.parent else request.user
        zones = list(SafeZone.objects.filter(parent=parent))

        events = []
        last_address = None
        last_battery = None
        last_zone_name = None
        last_charging = None

        for loc in locations:
            ts = loc.created_at.isoformat()

            # Check if inside a safe zone
            matched_zone = _match_zone_for_location(zones, loc)
            current_zone = matched_zone.name if matched_zone else None

            # Zone enter/leave events
            if current_zone and current_zone != last_zone_name:
                events.append({
                    "type": "arrived",
                    "icon": "check_circle",
                    "title": f"Arrived at {current_zone}",
                    "subtitle": loc.address or f"{loc.lat:.4f}, {loc.lng:.4f}",
                    "zone_name": current_zone,
                    "time": ts,
                })
            elif last_zone_name and not current_zone:
                events.append({
                    "type": "left",
                    "icon": "logout",
                    "title": f"Left {last_zone_name}",
                    "subtitle": loc.address or f"{loc.lat:.4f}, {loc.lng:.4f}",
                    "zone_name": last_zone_name,
                    "time": ts,
                })
            elif not current_zone and loc.address and loc.address != last_address:
                events.append({
                    "type": "moved",
                    "icon": "location_on",
                    "title": "Location Update",
                    "subtitle": loc.address,
                    "time": ts,
                })

            last_zone_name = current_zone
            if loc.address:
                last_address = loc.address

            if loc.charging and last_charging is not True:
                events.append({
                    "type": "charging",
                    "icon": "bolt",
                    "title": "Phone Charging",
                    "subtitle": (
                        f"Телефон поставлен на зарядку · {loc.battery}%"
                        if loc.battery is not None
                        else "Телефон поставлен на зарядку"
                    ),
                    "time": ts,
                })

            # Battery events
            if loc.battery is not None and last_battery is not None:
                if loc.battery > last_battery + 5 and not loc.charging:
                    events.append({
                        "type": "charging",
                        "icon": "bolt",
                        "title": "Phone Charging",
                        "subtitle": f"Battery reached {loc.battery}%",
                        "time": ts,
                    })
                elif loc.battery < last_battery - 20:
                    events.append({
                        "type": "battery_low",
                        "icon": "battery_alert",
                        "title": "Battery Low",
                        "subtitle": f"Battery dropped to {loc.battery}%",
                        "time": ts,
                    })
            if loc.battery is not None:
                last_battery = loc.battery
            last_charging = loc.charging

        # If no events today, show current status
        if not events and locations:
            latest = locations[-1]
            matched_zone = _match_zone_for_location(zones, latest)
            events.append({
                "type": "current",
                "icon": "location_on",
                "title": "Current Location",
                "subtitle": latest.address or "Location shared",
                "zone_name": matched_zone.name if matched_zone else None,
                "time": latest.created_at.isoformat(),
            })
            if latest.battery is not None:
                events.append({
                    "type": "battery",
                    "icon": "battery_std",
                    "title": "Battery Status",
                    "subtitle": f"Battery at {latest.battery}%",
                    "time": latest.created_at.isoformat(),
                })

        return Response(events)


class ChildSafetyScoreView(APIView):
    """Calculate daily safety score: % of location updates inside safe zones."""
    permission_classes = [IsAuthenticated]

    def get(self, request, child_id):
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        locations = list(child.locations.filter(created_at__gte=today))

        parent = child.parent if child.parent else request.user
        zones = list(SafeZone.objects.filter(parent=parent))

        if not locations or not zones:
            return Response({
                "score": 0,
                "in_zone_pct": 0,
                "total_updates": len(locations),
                "in_zone_updates": 0,
            })

        in_zone = 0
        for loc in locations:
            if _match_zone_for_location(zones, loc) is not None:
                in_zone += 1

        pct = round(in_zone / len(locations) * 100) if locations else 0
        # Score is weighted: zone compliance is 80% of score, having updates is 20%
        score = min(100, pct)
        latest_zone = _match_zone_for_location(zones, locations[-1]) if locations else None

        return Response({
            "score": score,
            "in_zone_pct": pct,
            "total_updates": len(locations),
            "in_zone_updates": in_zone,
            "outside_zone_updates": len(locations) - in_zone,
            "current_zone_name": latest_zone.name if latest_zone else None,
        })


class ChildDeviceStatsSyncView(APIView):
    """Child device uploads live device information and app usage history."""
    permission_classes = [IsAuthenticated]
    MAX_DAILY_USAGE_MINUTES = 24 * 60

    def post(self, request):
        if request.user.role != User.ROLE_CHILD:
            return Response({"detail": "children only"}, status=403)

        serializer = DeviceStatsSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        device_status, _ = DeviceStatus.objects.get_or_create(child=request.user)
        for field in [
            "device_name",
            "manufacturer",
            "model",
            "platform",
            "os_version",
            "timezone",
            "battery",
            "charging",
            "usage_access_granted",
            "location_service_enabled",
            "location_permission_granted",
            "background_location_granted",
            "microphone_granted",
            "notifications_granted",
            "accessibility_enabled",
            "battery_optimization_disabled",
        ]:
            if field in data:
                setattr(device_status, field, data[field])
        device_status.save()

        days = data.get("days", [])
        if not days:
            return Response({"detail": "device synced", "days_synced": 0})

        usage_dates = [day["date"] for day in days]
        active_limits = {
            limit.package_name: limit
            for limit in request.user.app_limits.filter(enabled=True)
        }

        summaries = []
        snapshots = []
        icon_updates = {}
        for day in days:
            raw_apps = day.get("apps", [])
            apps = []
            for app in raw_apps:
                icon_b64 = app.get("icon_b64")
                if icon_b64:
                    icon_updates[app["package_name"]] = icon_b64
                apps.append({
                    **app,
                    "usage_minutes": min(
                        max(int(app["usage_minutes"]), 0),
                        self.MAX_DAILY_USAGE_MINUTES,
                    ),
                })

            requested_total = day.get("total_minutes")
            if requested_total is None:
                requested_total = sum(app["usage_minutes"] for app in apps)
            total_minutes = min(
                max(int(requested_total), 0),
                self.MAX_DAILY_USAGE_MINUTES,
            )
            over_limit_apps = 0
            for app in apps:
                limit = active_limits.get(app["package_name"])
                if limit and app["usage_minutes"] > limit.daily_limit_minutes:
                    over_limit_apps += 1
                snapshots.append(
                    AppUsageSnapshot(
                        child=request.user,
                        usage_date=day["date"],
                        package_name=app["package_name"],
                        app_name=app.get("app_name") or app["package_name"],
                        usage_minutes=app["usage_minutes"],
                        last_used_at=app.get("last_used_at"),
                    )
                )
            summaries.append(
                DeviceDailySummary(
                    child=request.user,
                    usage_date=day["date"],
                    total_minutes=total_minutes,
                    over_limit_apps=over_limit_apps,
                )
            )

        with transaction.atomic():
            AppUsageSnapshot.objects.filter(
                child=request.user,
                usage_date__in=usage_dates,
            ).delete()
            DeviceDailySummary.objects.filter(
                child=request.user,
                usage_date__in=usage_dates,
            ).delete()
            DeviceDailySummary.objects.bulk_create(summaries)
            if snapshots:
                AppUsageSnapshot.objects.bulk_create(snapshots)
            for package_name, icon_b64 in icon_updates.items():
                AppIcon.objects.update_or_create(
                    child=request.user,
                    package_name=package_name,
                    defaults={"icon_b64": icon_b64},
                )

        # Auto-block apps that exceed their enabled daily limits
        today_str = timezone.localdate()
        today_apps = [s for s in snapshots if s.usage_date == today_str]
        newly_blocked = False
        for snapshot in today_apps:
            limit = active_limits.get(snapshot.package_name)
            if limit and snapshot.usage_minutes > limit.daily_limit_minutes:
                _, created = BlockedApp.objects.get_or_create(
                    child=request.user,
                    package_name=snapshot.package_name,
                    defaults={"app_name": snapshot.app_name},
                )
                if created:
                    newly_blocked = True

        if newly_blocked:
            # Send updated blocked list to the child device
            blocked_packages = list(
                request.user.blocked_apps.values_list("package_name", flat=True)
            )
            parent = request.user.parent
            if parent:
                cmd = RemoteDeviceCommand.objects.create(
                    child=request.user,
                    created_by=parent,
                    command_type=RemoteDeviceCommand.TYPE_SYNC_BLOCKED_APPS,
                    payload={"blocked_packages": blocked_packages},
                )
                if request.user.fcm_token:
                    send_command_push(
                        request.user.fcm_token,
                        RemoteDeviceCommand.TYPE_SYNC_BLOCKED_APPS,
                        {"command_id": cmd.id},
                    )

        return Response(
            {
                "detail": "device synced",
                "days_synced": len(days),
                "apps_synced": len(snapshots),
            }
        )


class ChildStatsSummaryView(APIView):
    """Full stats payload for the parent Stats screen."""
    permission_classes = [IsAuthenticated]

    def get(self, request, child_id):
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        today = timezone.localdate()
        selected_date = _parse_selected_date(
            request.query_params.get("date"),
            today,
        )
        selected_month = _parse_selected_month(
            request.query_params.get("month"),
            dt_date(selected_date.year, selected_date.month, 1),
        )
        month_last_day = calendar.monthrange(
            selected_month.year,
            selected_month.month,
        )[1]
        month_end = dt_date(selected_month.year, selected_month.month, month_last_day)
        week_start = selected_date - timedelta(days=6)

        latest_location = child.locations.first()
        device_status = getattr(child, "device_status", None)
        limits = list(child.app_limits.all())
        limits_by_package = {limit.package_name: limit for limit in limits}
        icons_by_package = {
            icon.package_name: icon.icon_b64
            for icon in child.app_icons.all()
        }

        month_summaries = {
            summary.usage_date: summary
            for summary in child.daily_usage_summaries.filter(
                usage_date__gte=min(week_start, selected_month),
                usage_date__lte=max(selected_date, month_end),
            )
        }
        month_snapshots = list(
            child.app_usage_snapshots.filter(
                usage_date__gte=selected_month,
                usage_date__lte=month_end,
            )
        )

        over_limit_dates = set()
        for snapshot in month_snapshots:
            limit = limits_by_package.get(snapshot.package_name)
            if limit and limit.enabled and snapshot.usage_minutes > limit.daily_limit_minutes:
                over_limit_dates.add(snapshot.usage_date)

        selected_apps = {}
        for snapshot in month_snapshots:
            if snapshot.usage_date != selected_date:
                continue
            selected_apps[snapshot.package_name] = {
                "package_name": snapshot.package_name,
                "app_name": snapshot.app_name,
                "usage_minutes": snapshot.usage_minutes,
                "last_used_at": snapshot.last_used_at.isoformat() if snapshot.last_used_at else None,
            }

        for limit in limits:
            item = selected_apps.setdefault(
                limit.package_name,
                {
                    "package_name": limit.package_name,
                    "app_name": limit.app_name,
                    "usage_minutes": 0,
                    "last_used_at": None,
                },
            )
            item["limit_id"] = limit.id
            item["daily_limit_minutes"] = limit.daily_limit_minutes
            item["limit_enabled"] = limit.enabled
            item["exceeded"] = item["usage_minutes"] > limit.daily_limit_minutes if limit.enabled else False

        for item in selected_apps.values():
            limit = limits_by_package.get(item["package_name"])
            item.setdefault("limit_id", limit.id if limit else None)
            item.setdefault("daily_limit_minutes", limit.daily_limit_minutes if limit else None)
            item.setdefault("limit_enabled", limit.enabled if limit else False)
            item["exceeded"] = (
                item["usage_minutes"] > item["daily_limit_minutes"]
                if item["limit_enabled"] and item["daily_limit_minutes"] is not None
                else False
            )

        selected_summary = month_summaries.get(selected_date)
        total_limit_minutes = sum(
            limit.daily_limit_minutes
            for limit in limits
            if limit.enabled and limit.daily_limit_minutes > 0
        )
        today_used_minutes = selected_summary.total_minutes if selected_summary else 0
        goal_progress = (
            min(today_used_minutes / total_limit_minutes, 1)
            if total_limit_minutes > 0
            else None
        )

        # Recalculate over_limit_apps dynamically from current limits
        over_limit_count = sum(
            1 for app in selected_apps.values()
            if app.get("exceeded", False)
        )

        weekly = []
        for offset in range(7):
            day = week_start + timedelta(days=offset)
            summary = month_summaries.get(day)
            weekly.append(
                {
                    "date": day.isoformat(),
                    "label": day.strftime("%a").upper(),
                    "total_minutes": summary.total_minutes if summary else 0,
                    "is_selected": day == selected_date,
                    "is_today": day == today,
                }
            )

        calendar_days = []
        day_cursor = selected_month
        while day_cursor <= month_end:
            summary = month_summaries.get(day_cursor)
            calendar_days.append(
                {
                    "date": day_cursor.isoformat(),
                    "day": day_cursor.day,
                    "total_minutes": summary.total_minutes if summary else 0,
                    "has_data": summary is not None,
                    "over_limit": day_cursor in over_limit_dates,
                    "is_selected": day_cursor == selected_date,
                    "is_today": day_cursor == today,
                }
            )
            day_cursor += timedelta(days=1)

        for item in selected_apps.values():
            icon = icons_by_package.get(item["package_name"])
            if icon:
                item["icon_b64"] = icon

        apps = sorted(
            selected_apps.values(),
            key=lambda item: (-item["usage_minutes"], item["app_name"].lower()),
        )

        # Build all_known_apps: unique apps ever seen on this child's device
        all_snapshots = (
            child.app_usage_snapshots
            .values("package_name", "app_name")
            .distinct()
        )
        known_packages_in_apps = {a["package_name"] for a in apps}
        all_known_apps = sorted(
            [
                {
                    "package_name": s["package_name"],
                    "app_name": s["app_name"],
                    "icon_b64": icons_by_package.get(s["package_name"]),
                }
                for s in all_snapshots
                if s["package_name"] not in known_packages_in_apps
            ],
            key=lambda x: x["app_name"].lower(),
        )

        return Response(
            {
                "child": UserSerializer(child, context={"request": request}).data,
                "selected_date": selected_date.isoformat(),
                "selected_month": selected_month.strftime("%Y-%m"),
                "device": {
                    "device_name": device_status.device_name if device_status else "",
                    "manufacturer": device_status.manufacturer if device_status else "",
                    "model": device_status.model if device_status else "",
                    "platform": device_status.platform if device_status else "",
                    "os_version": device_status.os_version if device_status else "",
                    "timezone": device_status.timezone if device_status else "",
                    "usage_access_granted": device_status.usage_access_granted if device_status else False,
                    "location_service_enabled": device_status.location_service_enabled if device_status else False,
                    "location_permission_granted": device_status.location_permission_granted if device_status else False,
                    "background_location_granted": device_status.background_location_granted if device_status else False,
                    "microphone_granted": device_status.microphone_granted if device_status else False,
                    "notifications_granted": device_status.notifications_granted if device_status else False,
                    "accessibility_enabled": device_status.accessibility_enabled if device_status else False,
                    "battery_optimization_disabled": device_status.battery_optimization_disabled if device_status else False,
                    "charging": device_status.charging if device_status else False,
                    "battery": (
                        latest_location.battery
                        if latest_location and latest_location.battery is not None
                        else (device_status.battery if device_status else None)
                    ),
                    "active": latest_location.active if latest_location else False,
                    "last_seen_at": latest_location.created_at.isoformat() if latest_location else None,
                    "last_sync_at": device_status.synced_at.isoformat() if device_status else None,
                    "address": latest_location.address if latest_location else "",
                },
                "usage": {
                    "selected_total_minutes": today_used_minutes,
                    "selected_total_limit_minutes": total_limit_minutes,
                    "goal_progress": goal_progress,
                    "over_limit_apps": over_limit_count,
                },
                "weekly": weekly,
                "calendar": calendar_days,
                "apps": apps,
                "all_known_apps": all_known_apps,
            }
        )


class ChildAppLimitView(APIView):
    """Create or update a child's daily app limit."""
    permission_classes = [IsAuthenticated]

    def post(self, request, child_id):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        child = get_object_or_404(
            User,
            id=child_id,
            role=User.ROLE_CHILD,
            parent=request.user,
        )
        serializer = AppLimitWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        app_limit, _ = AppLimit.objects.update_or_create(
            child=child,
            package_name=data["package_name"],
            defaults={
                "app_name": data.get("app_name") or data["package_name"],
                "daily_limit_minutes": data["daily_limit_minutes"],
                "enabled": data["enabled"],
            },
        )

        if app_limit.enabled:
            today_snapshot = (
                child.app_usage_snapshots.filter(
                    usage_date=timezone.localdate(),
                    package_name=app_limit.package_name,
                )
                .order_by("-usage_minutes", "-last_used_at", "-updated_at")
                .first()
            )
            if (
                today_snapshot is not None
                and today_snapshot.usage_minutes > app_limit.daily_limit_minutes
            ):
                blocked, created = BlockedApp.objects.get_or_create(
                    child=child,
                    package_name=app_limit.package_name,
                    defaults={"app_name": today_snapshot.app_name or app_limit.app_name},
                )
                if created or blocked.app_name != (today_snapshot.app_name or app_limit.app_name):
                    blocked.app_name = today_snapshot.app_name or app_limit.app_name
                    blocked.save(update_fields=["app_name"])
                BlockedAppsView._send_sync_command(child, request.user)

        return Response(AppLimitSerializer(app_limit).data)


class ChildDeviceCommandCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, child_id):
        child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
        if not _ensure_parent_child_relationship(request.user, child):
            return Response({"detail": "forbidden"}, status=403)

        serializer = RemoteDeviceCommandActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data.get("payload") or {}

        if serializer.validated_data["command_type"] == RemoteDeviceCommand.TYPE_AROUND_START:
            payload.setdefault("session_token", AroundAudioClip.new_session_token())

        command = RemoteDeviceCommand.objects.create(
            child=child,
            created_by=request.user,
            command_type=serializer.validated_data["command_type"],
            payload=payload,
        )

        # Send FCM push to wake the child device even if the app is killed.
        if child.fcm_token and command.command_type in (
            RemoteDeviceCommand.TYPE_LOUD,
            RemoteDeviceCommand.TYPE_LOUD_STOP,
            RemoteDeviceCommand.TYPE_AROUND_START,
            RemoteDeviceCommand.TYPE_AROUND_STOP,
            RemoteDeviceCommand.TYPE_WEBRTC_MONITOR_START,
            RemoteDeviceCommand.TYPE_WEBRTC_MONITOR_STOP,
        ):
            send_command_push(
                child.fcm_token,
                command.command_type,
                extra_data=payload,
            )

        return Response(RemoteDeviceCommandSerializer(command).data, status=201)


class PendingDeviceCommandsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != User.ROLE_CHILD:
            return Response([])

        commands = list(
            request.user.device_commands.filter(
                status=RemoteDeviceCommand.STATUS_PENDING,
            ).order_by("created_at", "id")[:10]
        )
        if commands:
            now = timezone.now()
            RemoteDeviceCommand.objects.filter(
                id__in=[command.id for command in commands],
                status=RemoteDeviceCommand.STATUS_PENDING,
            ).update(
                status=RemoteDeviceCommand.STATUS_DELIVERED,
                delivered_at=now,
            )
            for command in commands:
                command.status = RemoteDeviceCommand.STATUS_DELIVERED
                command.delivered_at = now

        return Response(RemoteDeviceCommandSerializer(commands, many=True).data)


class CompleteDeviceCommandView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, command_id):
        command = get_object_or_404(RemoteDeviceCommand, id=command_id)
        if request.user.role != User.ROLE_CHILD or command.child_id != request.user.id:
            return Response({"detail": "forbidden"}, status=403)

        serializer = RemoteDeviceCommandCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        success = serializer.validated_data["success"]
        command.status = (
            RemoteDeviceCommand.STATUS_COMPLETED
            if success
            else RemoteDeviceCommand.STATUS_FAILED
        )
        command.error_message = serializer.validated_data.get("error_message", "")
        command.completed_at = timezone.now()
        command.save(update_fields=["status", "error_message", "completed_at"])
        if command.status == RemoteDeviceCommand.STATUS_FAILED:
            logger.warning(
                "Device command failed: child_id=%s command_id=%s type=%s error=%s",
                command.child_id,
                command.id,
                command.command_type,
                command.error_message,
            )
        return Response(RemoteDeviceCommandSerializer(command).data)


class AroundAudioUploadView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        if request.user.role != User.ROLE_CHILD:
            return Response({"detail": "children only"}, status=403)

        session_token = (request.data.get("session_token") or "").strip()
        if not session_token:
            return Response({"detail": "session_token is required"}, status=400)

        uploaded = request.FILES.get("audio")
        if uploaded is None:
            return Response({"detail": "audio file is required"}, status=400)

        duration_seconds = int(request.data.get("duration_seconds") or 0)
        clip = AroundAudioClip.objects.create(
            child=request.user,
            session_token=session_token,
            audio=uploaded,
            duration_seconds=max(duration_seconds, 0),
        )
        logger.info(
            "Around audio uploaded: child_id=%s session=%s clip_id=%s duration=%ss",
            request.user.id,
            session_token,
            clip.id,
            clip.duration_seconds,
        )
        return Response(
            AroundAudioClipSerializer(clip, context={"request": request}).data,
            status=201,
        )


class LatestAroundAudioView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, child_id):
        child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
        if not _ensure_parent_child_relationship(request.user, child):
            return Response({"detail": "forbidden"}, status=403)

        session_token = (request.query_params.get("session_token") or "").strip()
        if not session_token:
            return Response({"detail": "session_token is required"}, status=400)

        qs = child.around_audio_clips.filter(session_token=session_token)
        after_id = request.query_params.get("after_id")
        if after_id:
            try:
                qs = qs.filter(id__gt=int(after_id))
            except (TypeError, ValueError):
                return Response({"detail": "invalid after_id"}, status=400)
        clip = qs.order_by("id").first()
        if clip is None:
            return Response(status=204)
        return Response(
            AroundAudioClipSerializer(clip, context={"request": request}).data,
        )


class AroundAudioStreamView(APIView):
    """Stream the actual audio file for a clip (parent only)."""
    permission_classes = [IsAuthenticated]

    def get(self, request, clip_id):
        clip = get_object_or_404(AroundAudioClip, id=clip_id)
        child = clip.child
        if not _ensure_parent_child_relationship(request.user, child):
            return Response({"detail": "forbidden"}, status=403)
        if not clip.audio:
            return Response({"detail": "no audio"}, status=404)
        content_type, _ = mimetypes.guess_type(clip.audio.name)
        return FileResponse(
            clip.audio.open("rb"),
            content_type=content_type or "audio/mp4",
        )


class AroundAudioLiveUploadView(APIView):
    """Child -> backend: one long-lived HTTP upload with raw PCM chunks."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.ROLE_CHILD:
            return Response({"detail": "children only"}, status=403)

        session_token = (request.query_params.get("session_token") or "").strip()
        if not session_token:
            return Response({"detail": "session_token is required"}, status=400)

        sample_rate = _coerce_positive_int(
            request.headers.get("X-Audio-Sample-Rate"),
            LIVE_AUDIO_DEFAULT_SAMPLE_RATE,
        )
        channels = _coerce_positive_int(
            request.headers.get("X-Audio-Channels"),
            LIVE_AUDIO_DEFAULT_CHANNELS,
        )

        session = live_audio_broker.get_or_create(
            session_token,
            child_id=request.user.id,
            sample_rate=sample_rate,
            channels=channels,
            audio_format=LIVE_AUDIO_FORMAT,
        )
        # Read the request body incrementally and forward each piece to
        # the broker as it arrives. The deployment's nginx is configured
        # with `proxy_request_buffering off` (see DEPLOY_NGINX.md), so
        # `wsgi.input.read(...)` returns data the moment the child
        # flushes a chunk over its long-lived POST.
        chunk_count = 0
        byte_count = 0
        try:
            stream = request.META["wsgi.input"]
            while True:
                chunk = stream.read(4096)
                if not chunk:
                    break
                chunk_count += 1
                byte_count += len(chunk)
                live_audio_broker.publish(
                    session_token,
                    child_id=request.user.id,
                    data=bytes(chunk),
                )
        except Exception:  # noqa: BLE001 — never let a broken upload kill the broker
            logger.exception(
                "Around live audio upload errored: child_id=%s session=%s",
                request.user.id,
                session_token,
            )
        # Do NOT call broker.finish() — the session stays open across
        # client reconnects. It is implicitly closed only when nothing
        # touches it and it gets evicted.

        logger.info(
            "Around live audio upload finished: child_id=%s session=%s chunks=%s bytes=%s",
            request.user.id,
            session_token,
            chunk_count,
            byte_count,
        )
        return Response(
            {
                "status": "ok",
                "session_token": session_token,
                "sample_rate": session.sample_rate,
                "channels": session.channels,
                "format": session.format,
                "bytes_received": byte_count,
                "chunks_received": chunk_count,
            }
        )


class AroundAudioLiveStreamView(APIView):
    """Parent <- backend: one long-lived HTTP download of raw PCM chunks."""

    permission_classes = [IsAuthenticated]

    def get(self, request, child_id):
        child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
        if not _ensure_parent_child_relationship(request.user, child):
            return Response({"detail": "forbidden"}, status=403)

        session_token = (request.query_params.get("session_token") or "").strip()
        if not session_token:
            return Response({"detail": "session_token is required"}, status=400)

        session = live_audio_broker.get_or_create(
            session_token,
            child_id=child.id,
            sample_rate=LIVE_AUDIO_DEFAULT_SAMPLE_RATE,
            channels=LIVE_AUDIO_DEFAULT_CHANNELS,
            audio_format=LIVE_AUDIO_FORMAT,
        )

        response = StreamingHttpResponse(
            streaming_content=live_audio_broker.iter_chunks(
                session_token,
                child_id=child.id,
            ),
            content_type="application/octet-stream",
        )
        response["Cache-Control"] = "no-store"
        response["X-Accel-Buffering"] = "no"
        response["Content-Encoding"] = "identity"
        response["X-Audio-Sample-Rate"] = str(session.sample_rate)
        response["X-Audio-Channels"] = str(session.channels)
        response["X-Audio-Format"] = session.format
        return response


class ActivateMonitoringView(APIView):
    """
    Parent creates a MonitorSession and sends FCM push to wake the child.
    Returns session_token that both sides use for signaling.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)

        child_id = request.data.get("child_id")
        if not child_id:
            return Response({"detail": "child_id required"}, status=400)

        child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
        if not _ensure_parent_child_relationship(request.user, child):
            return Response({"detail": "forbidden"}, status=403)

        # Close any stale sessions for this parent-child pair.
        MonitorSession.objects.filter(
            parent=request.user,
            child=child,
        ).exclude(status=MonitorSession.STATUS_CLOSED).update(
            status=MonitorSession.STATUS_CLOSED,
        )

        session = MonitorSession.objects.create(
            parent=request.user,
            child=child,
            session_token=MonitorSession.new_token(),
        )

        # Create a polling-backed command so the child picks it up even if FCM
        # is unavailable / delayed. The background service polls every 2s.
        RemoteDeviceCommand.objects.create(
            child=child,
            created_by=request.user,
            command_type=RemoteDeviceCommand.TYPE_WEBRTC_MONITOR_START,
            payload={"session_token": session.session_token},
        )

        if child.fcm_token:
            send_command_push(
                child.fcm_token,
                "webrtc_monitor_start",
                extra_data={"session_token": session.session_token},
            )

        return Response({
            "session_token": session.session_token,
        })


class DeactivateMonitoringView(APIView):
    """Parent closes the MonitorSession and notifies the child via FCM."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)

        session_token = (request.data.get("session_token") or "").strip()
        child_id = request.data.get("child_id")

        if session_token:
            MonitorSession.objects.filter(
                session_token=session_token,
                parent=request.user,
            ).exclude(status=MonitorSession.STATUS_CLOSED).update(
                status=MonitorSession.STATUS_CLOSED,
            )

        if child_id:
            child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
            RemoteDeviceCommand.objects.create(
                child=child,
                created_by=request.user,
                command_type=RemoteDeviceCommand.TYPE_WEBRTC_MONITOR_STOP,
                payload={"session_token": session_token},
            )
            if child.fcm_token:
                send_command_push(
                    child.fcm_token,
                    "webrtc_monitor_stop",
                    extra_data={
                        "session_token": session_token,
                    },
                )

        return Response({"detail": "ok"})


class MonitorSignalSendView(APIView):
    """
    Post a signaling message (SDP offer/answer or ICE candidate).
    Both parent and child call this endpoint.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        session_token = (request.data.get("session_token") or "").strip()
        msg_type = (request.data.get("type") or "").strip()
        payload = request.data.get("payload")

        if not session_token or not msg_type or payload is None:
            return Response(
                {"detail": "session_token, type, and payload are required"},
                status=400,
            )

        session = get_object_or_404(
            MonitorSession,
            session_token=session_token,
        )

        # Determine sender role from the authenticated user.
        if request.user.id == session.parent_id:
            sender_role = "parent"
        elif request.user.id == session.child_id:
            sender_role = "child"
        else:
            return Response({"detail": "forbidden"}, status=403)

        if session.status == MonitorSession.STATUS_CLOSED:
            return Response({"detail": "session closed"}, status=410)

        # Mark session active once the child sends an offer.
        if (
            sender_role == "child"
            and msg_type == "offer"
            and session.status == MonitorSession.STATUS_WAITING
        ):
            session.status = MonitorSession.STATUS_ACTIVE
            session.save(update_fields=["status"])

        SignalingMessage.objects.create(
            session=session,
            sender_role=sender_role,
            msg_type=msg_type,
            payload=payload,
        )

        return Response({"detail": "ok"}, status=201)


class MonitorSignalPollView(APIView):
    """
    Poll for new signaling messages from the other peer.
    Returns messages addressed to the caller (i.e. sent by the *other* role).

    Query params:
      - session_token (required)
      - after_id (optional) — only return messages with id > after_id
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        session_token = (request.query_params.get("session_token") or "").strip()
        if not session_token:
            return Response({"detail": "session_token required"}, status=400)

        session = get_object_or_404(
            MonitorSession,
            session_token=session_token,
        )

        if request.user.id == session.parent_id:
            other_role = "child"
        elif request.user.id == session.child_id:
            other_role = "parent"
        else:
            return Response({"detail": "forbidden"}, status=403)

        qs = session.messages.filter(sender_role=other_role)

        after_id = request.query_params.get("after_id")
        if after_id:
            try:
                qs = qs.filter(id__gt=int(after_id))
            except (TypeError, ValueError):
                return Response({"detail": "invalid after_id"}, status=400)

        messages = list(qs[:50])

        return Response({
            "session_status": session.status,
            "messages": [
                {
                    "id": m.id,
                    "type": m.msg_type,
                    "payload": m.payload,
                }
                for m in messages
            ],
        })


class SosView(APIView):
    """Child sends an SOS alert to their parent."""
    permission_classes = [IsAuthenticated]

    SOS_COOLDOWN = timedelta(seconds=30)

    def post(self, request):
        if request.user.role != User.ROLE_CHILD:
            return Response({"detail": "children only"}, status=403)

        parent = request.user.parent
        if not parent:
            return Response({"detail": "no parent linked"}, status=400)

        # Cooldown to prevent spam
        cutoff = timezone.now() - self.SOS_COOLDOWN
        already = Alert.objects.filter(
            child=request.user,
            parent=parent,
            alert_type=Alert.TYPE_SOS,
            created_at__gte=cutoff,
        ).exists()
        if already:
            return Response({"detail": "SOS already sent recently"}, status=429)

        child_name = request.user.display_name or request.user.username
        address = request.data.get("address", "")
        lat = request.data.get("lat")
        lng = request.data.get("lng")

        location_text = f" Местоположение: {address}" if address else ""
        if lat and lng and not address:
            location_text = f" Координаты: {lat}, {lng}"

        alert = Alert.objects.create(
            child=request.user,
            parent=parent,
            alert_type=Alert.TYPE_SOS,
            title=f"SOS от {child_name}!",
            message=f"{child_name} нужна помощь!{location_text}",
        )

        # Send FCM push to parent
        if parent.fcm_token:
            send_notification_push(
                parent.fcm_token,
                notification_type="sos",
                title=f"🚨 SOS от {child_name}!",
                body=f"{child_name} нужна помощь!{location_text}",
                extra_data={
                    "child_id": request.user.id,
                    "child_name": child_name,
                    "alert_id": alert.id,
                },
            )

        return Response({"detail": "sos sent", "alert_id": alert.id}, status=201)


class ParentAlertsView(APIView):
    """Parent fetches unread alerts for all their children."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        alerts = request.user.parent_alerts.filter(read=False).order_by("-created_at")[:50]
        return Response(AlertSerializer(alerts, many=True).data)


class AlertReadView(APIView):
    """Mark an alert as read."""
    permission_classes = [IsAuthenticated]

    def post(self, request, alert_id):
        alert = get_object_or_404(Alert, id=alert_id, parent=request.user)
        alert.read = True
        alert.save(update_fields=["read"])
        return Response({"detail": "ok"})


class AlertReadAllView(APIView):
    """Mark all alerts as read."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        request.user.parent_alerts.filter(read=False).update(read=True)
        return Response({"detail": "ok"})


class BlockedAppsView(APIView):
    """
    GET  /api/children/<child_id>/blocked-apps/ — list blocked apps
    POST /api/children/<child_id>/blocked-apps/ — block an app
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, child_id):
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)
        apps = BlockedApp.objects.filter(child=child)
        return Response(BlockedAppSerializer(apps, many=True).data)

    def post(self, request, child_id):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        s = BlockAppSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        blocked, created = BlockedApp.objects.get_or_create(
            child=child,
            package_name=s.validated_data["package_name"],
            defaults={"app_name": s.validated_data["app_name"]},
        )
        if blocked.app_name != s.validated_data["app_name"]:
            blocked.app_name = s.validated_data["app_name"]
            blocked.save(update_fields=["app_name"])

        # Send command to child to refresh blocked apps list.
        self._send_sync_command(child, request.user)

        return Response(
            BlockedAppSerializer(blocked).data,
            status=201 if created else 200,
        )

    @staticmethod
    def _send_sync_command(child, parent):
        blocked_packages = list(
            child.blocked_apps.values_list("package_name", flat=True)
        )
        cmd = RemoteDeviceCommand.objects.create(
            child=child,
            created_by=parent,
            command_type=RemoteDeviceCommand.TYPE_SYNC_BLOCKED_APPS,
            payload={"blocked_packages": blocked_packages},
        )
        if child.fcm_token:
            send_command_push(
                child.fcm_token,
                RemoteDeviceCommand.TYPE_SYNC_BLOCKED_APPS,
                {"command_id": cmd.id},
            )


class UnblockAppView(APIView):
    """DELETE /api/children/<child_id>/blocked-apps/<blocked_id>/"""
    permission_classes = [IsAuthenticated]

    def delete(self, request, child_id, blocked_id):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        blocked = get_object_or_404(BlockedApp, id=blocked_id, child=child)
        blocked.delete()

        # Send updated list to child.
        BlockedAppsView._send_sync_command(child, request.user)

        return Response(status=204)
