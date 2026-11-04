from django.urls import path
from .views import (LiteAccessTokenView, RevenueCatConfigView,
                    RevenueCatWebhookView, SubscriptionSyncView)
urlpatterns = [
    path("config/", RevenueCatConfigView.as_view()),
    path("lite-token/", LiteAccessTokenView.as_view()),
    path("sync/", SubscriptionSyncView.as_view()),
    path("webhook/", RevenueCatWebhookView.as_view()),
]
