from django.urls import path

from .views import RevenueCatWebhookView

urlpatterns = [
    path("webhook/", RevenueCatWebhookView.as_view()),
]
