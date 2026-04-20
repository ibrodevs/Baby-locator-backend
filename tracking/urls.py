from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AlertReadAllView,
    AlertReadView,
    AllChildrenLocationsView,
    AroundAudioStreamView,
    AroundAudioUploadView,
    BlockedAppsView,
    ChildActivityView,
    ChildAppLimitView,
    ChildDeviceCommandCreateView,
    ChildDeviceStatsSyncView,
    ChildLatestLocationView,
    ChildLocationHistoryView,
    ChildSafetyScoreView,
    ChildStatsSummaryView,
    CompleteDeviceCommandView,
    LatestAroundAudioView,
    ParentAlertsView,
    PendingDeviceCommandsView,
    SafeZoneViewSet,
    ShareLocationView,
    SosView,
    UnblockAppView,
)

router = DefaultRouter()
router.register(r"safe-zones", SafeZoneViewSet, basename="safezone")

urlpatterns = [
    path("", include(router.urls)),
    path("locations/", ShareLocationView.as_view()),
    path("device-stats/sync/", ChildDeviceStatsSyncView.as_view()),
    path("device-commands/pending/", PendingDeviceCommandsView.as_view()),
    path("device-commands/<int:command_id>/complete/", CompleteDeviceCommandView.as_view()),
    path("around-audio/", AroundAudioUploadView.as_view()),
    path("around-audio/<int:clip_id>/stream/", AroundAudioStreamView.as_view()),
    path("children/locations/", AllChildrenLocationsView.as_view()),
    path("children/<int:child_id>/device-commands/", ChildDeviceCommandCreateView.as_view()),
    path("children/<int:child_id>/around-audio/latest/", LatestAroundAudioView.as_view()),
    path("children/<int:child_id>/location/", ChildLatestLocationView.as_view()),
    path("children/<int:child_id>/history/", ChildLocationHistoryView.as_view()),
    path("children/<int:child_id>/activity/", ChildActivityView.as_view()),
    path("children/<int:child_id>/safety-score/", ChildSafetyScoreView.as_view()),
    path("children/<int:child_id>/stats/", ChildStatsSummaryView.as_view()),
    path("children/<int:child_id>/app-limits/", ChildAppLimitView.as_view()),
    path("children/<int:child_id>/blocked-apps/", BlockedAppsView.as_view()),
    path("children/<int:child_id>/blocked-apps/<int:blocked_id>/", UnblockAppView.as_view()),
    path("sos/", SosView.as_view()),
    path("alerts/", ParentAlertsView.as_view()),
    path("alerts/<int:alert_id>/read/", AlertReadView.as_view()),
    path("alerts/read-all/", AlertReadAllView.as_view()),
]
