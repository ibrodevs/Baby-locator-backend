from django.urls import path

from .views import (
    AvatarUploadView,
    ChildAvatarUploadView,
    ChildDetailView,
    ChildrenView,
    FcmTokenView,
    InviteCodeView,
    LoginAsPremiumTestView,
    LoginView,
    LogoutView,
    MeView,
    RegisterChildWithCodeView,
    RegisterParentView,
    TestModeStatusView,
)

urlpatterns = [
    path("register/", RegisterParentView.as_view()),
    path("login/", LoginView.as_view()),
    path("logout/", LogoutView.as_view()),
    path("me/", MeView.as_view()),
    path("test-mode/", TestModeStatusView.as_view(), name="test-mode-status"),
    path("login-as-premium/", LoginAsPremiumTestView.as_view(), name="login-as-premium"),
    path("fcm-token/", FcmTokenView.as_view()),
    path("children/", ChildrenView.as_view()),
    path("children/<int:child_id>/", ChildDetailView.as_view()),
    path("children/<int:child_id>/avatar/", ChildAvatarUploadView.as_view()),
    path("avatar/", AvatarUploadView.as_view()),
    path("invite/", InviteCodeView.as_view()),
    path("register-child/", RegisterChildWithCodeView.as_view()),
]
