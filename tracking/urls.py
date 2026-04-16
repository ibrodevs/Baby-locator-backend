from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AllChildrenLocationsView,
    ChildActivityView,
    ChildAppLimitView,
    ChildDeviceStatsSyncView,
    ChildLatestLocationView,
    ChildLocationHistoryView,
    ChildSafetyScoreView,
    ChildStatsSummaryView,
    SafeZoneViewSet,
    ShareLocationView,
)

router = DefaultRouter()
router.register(r"safe-zones", SafeZoneViewSet, basename="safezone")

urlpatterns = [
    path("", include(router.urls)),
    path("locations/", ShareLocationView.as_view()),
    path("device-stats/sync/", ChildDeviceStatsSyncView.as_view()),
    path("children/locations/", AllChildrenLocationsView.as_view()),
    path("children/<int:child_id>/location/", ChildLatestLocationView.as_view()),
    path("children/<int:child_id>/history/", ChildLocationHistoryView.as_view()),
    path("children/<int:child_id>/activity/", ChildActivityView.as_view()),
    path("children/<int:child_id>/safety-score/", ChildSafetyScoreView.as_view()),
    path("children/<int:child_id>/stats/", ChildStatsSummaryView.as_view()),
    path("children/<int:child_id>/app-limits/", ChildAppLimitView.as_view()),
]
