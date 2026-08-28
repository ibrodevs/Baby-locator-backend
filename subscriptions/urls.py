from django.urls import path

from .views import LiteAccessTokenView, RevenueCatConfigView, RevenueCatWebhookView

urlpatterns = [
    path("config/", RevenueCatConfigView.as_view(), name="revenuecat-config"),
    path("lite-token/", LiteAccessTokenView.as_view()),
    path("webhook/", RevenueCatWebhookView.as_view()),
]

