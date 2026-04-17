from django.urls import path

from .views import (
    ChatMessagesView,
    RewardClaimView,
    RewardListView,
    StarsView,
    TaskActionView,
    TaskListView,
)

urlpatterns = [
    path("<int:child_id>/messages/", ChatMessagesView.as_view()),
    path("<int:child_id>/tasks/", TaskListView.as_view()),
    path("<int:child_id>/tasks/<int:task_id>/<str:action>/", TaskActionView.as_view()),
    path("<int:child_id>/tasks/<int:task_id>/", TaskActionView.as_view()),
    path("<int:child_id>/stars/", StarsView.as_view()),
    path("<int:child_id>/rewards/", RewardListView.as_view()),
    path("<int:child_id>/rewards/<int:reward_id>/claim/", RewardClaimView.as_view()),
    path("<int:child_id>/rewards/<int:reward_id>/", RewardClaimView.as_view()),
]
