from django.urls import path

from .views import (
    AvatarUploadView,
    ChildAvatarUploadView,
    ChildDetailView,
    ChildrenView,
    FcmTokenView,
    InviteCodeView,
    LoginView,
    MeView,
    RegisterChildWithCodeView,
    RegisterParentView,
)

urlpatterns = [
    path("register/", RegisterParentView.as_view()),
    path("login/", LoginView.as_view()),
    path("me/", MeView.as_view()),
    path("fcm-token/", FcmTokenView.as_view()),
    path("children/", ChildrenView.as_view()),
    path("children/<int:child_id>/", ChildDetailView.as_view()),
    path("children/<int:child_id>/avatar/", ChildAvatarUploadView.as_view()),
    path("avatar/", AvatarUploadView.as_view()),
    path("invite/", InviteCodeView.as_view()),
    path("register-child/", RegisterChildWithCodeView.as_view()),
]
