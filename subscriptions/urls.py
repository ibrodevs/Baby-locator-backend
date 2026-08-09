from django.urls import path

from .views import LiteAccessTokenView, RevenueCatWebhookView

urlpatterns = [
    path("lite-token/", LiteAccessTokenView.as_view()),
    path("webhook/", RevenueCatWebhookView.as_view()),
]
