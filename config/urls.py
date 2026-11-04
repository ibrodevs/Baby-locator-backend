from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from accounts.views import invite_landing
from accounts.media import PrivateMediaView

urlpatterns = [
    path("media/<path:name>", PrivateMediaView.as_view()),
    path("admin/", admin.site.urls),
    path("api/auth/", include("accounts.urls")),
    path("api/revenuecat/", include("subscriptions.urls")),
    path("api/", include("tracking.urls")),
    path("api/chat/", include("chat.urls")),
    path("invite/<str:code>/", invite_landing, name="invite-landing"),
]
