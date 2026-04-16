import calendar
import math
from datetime import date as dt_date
from datetime import timedelta

from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from accounts.serializers import UserSerializer

from .models import AppLimit, AppUsageSnapshot, DeviceDailySummary, DeviceStatus, LocationUpdate, SafeZone
from .serializers import (
    AppLimitSerializer,
    AppLimitWriteSerializer,
    DeviceStatsSyncSerializer,
    LocationInputSerializer,
    LocationSerializer,
    SafeZoneSerializer,
)


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


def _parse_selected_date(raw_value, fallback):
    if not raw_value:
        return fallback
    parsed = parse_date(raw_value)
    return parsed or fallback


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
    # ... (unchanged)
    """Child posts their current location."""

    def post(self, request):
        if request.user.role != User.ROLE_CHILD:
            return Response({"detail": "children only"}, status=403)
        s = LocationInputSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        loc = LocationUpdate.objects.create(
            child=request.user,
            lat=s.validated_data["lat"],
            lng=s.validated_data["lng"],
            address=s.validated_data.get("address", ""),
            battery=s.validated_data.get("battery"),
            active=s.validated_data.get("active", True),
        )
        return Response(LocationSerializer(loc).data, status=201)


class ChildLatestLocationView(APIView):
    """Parent fetches latest location of a specific child."""

    def get(self, request, child_id):
        child = _resolve_child_for_request(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)
        loc = child.locations.first()
        if not loc:
            return Response({"detail": "no location yet"}, status=404)
        return Response(LocationSerializer(loc).data)


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
            entry = {
                "child": UserSerializer(child, context={"request": request}).data,
                "location": LocationSerializer(loc).data if loc else None,
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

            # Battery events
            if loc.battery is not None and last_battery is not None:
                if loc.battery > last_battery + 5:
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
        for day in days:
            apps = day.get("apps", [])
            total_minutes = day.get(
                "total_minutes",
                sum(app["usage_minutes"] for app in apps),
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

        apps = sorted(
            selected_apps.values(),
            key=lambda item: (-item["usage_minutes"], item["app_name"].lower()),
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
                    "over_limit_apps": selected_summary.over_limit_apps if selected_summary else 0,
                },
                "weekly": weekly,
                "calendar": calendar_days,
                "apps": apps,
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
        return Response(AppLimitSerializer(app_limit).data)
