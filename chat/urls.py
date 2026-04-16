from django.urls import path

from .views import ChatMessagesView

urlpatterns = [
    path("<int:child_id>/messages/", ChatMessagesView.as_view()),
]
