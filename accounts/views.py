import logging
logger = logging.getLogger(__name__)
from datetime import timedelta
import secrets
import uuid

from django.conf import settings
from django.http import HttpResponse
from django.db import transaction
from django.utils.html import escape
from rest_framework.authtoken.models import Token
from .throttles import AuthenticationThrottle
from .uploads import validate_avatar
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from subscriptions.services import parent_can_add_child, premium_required_response

from .models import DeviceInstallation, InviteCode, User
from .serializers import (
    CreateChildSerializer,
    LoginSerializer,
    RegisterChildWithCodeSerializer,
    RegisterParentSerializer,
    UpdateChildSerializer,
    UpdateProfileSerializer,
    UserSerializer,
    token_for,
)


def _generate_child_credentials():
    while True:
        username = f"child_{uuid.uuid4().hex[:12]}"
        if not User.objects.filter(username=username).exists():
            return username, secrets.token_urlsafe(18)


def _get_parent_child_for_request(request):
    raw_child_id = request.data.get("child_id") or request.query_params.get("child_id")
    if raw_child_id in (None, ""):
        return None, None

    try:
        child_id = int(raw_child_id)
    except (TypeError, ValueError):
        return None, Response({"detail": "invalid child_id"}, status=400)

    try:
        child = request.user.children.get(id=child_id)
    except User.DoesNotExist:
        return None, Response({"detail": "child not found"}, status=404)

    return child, None


def _mark_child_joined(user):
    if user.role == User.ROLE_CHILD and user.joined_at is None:
        user.joined_at = timezone.now()
        user.save(update_fields=["joined_at"])


class RegisterParentView(APIView):
    throttle_classes = [AuthenticationThrottle]
    permission_classes = [AllowAny]

    def post(self, request):
        s = RegisterParentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.save()
        return Response(
            {"token": token_for(user), "user": UserSerializer(user, context={"request": request}).data},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    throttle_classes = [AuthenticationThrottle]
    permission_classes = [AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.validated_data["user"]
        _mark_child_joined(user)
        return Response({"token": token_for(user), "user": UserSerializer(user, context={"request": request}).data})


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user, context={"request": request}).data)

    def patch(self, request):
        serializer = UpdateProfileSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        user = request.user
        if "username" in serializer.validated_data:
            user.username = serializer.validated_data["username"]
        if "display_name" in serializer.validated_data:
            user.display_name = serializer.validated_data["display_name"]
        user.save()

        return Response(UserSerializer(user, context={"request": request}).data)

    def delete(self, request):
        with transaction.atomic():
            request.user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class LogoutView(APIView):
    def post(self, request):
        # Current DRF schema has one token per user: revocation signs out all sessions.
        request.user.installations.all().delete()
        request.user.fcm_token = ""
        request.user.save(update_fields=["fcm_token"])
        Token.objects.filter(user=request.user).delete()
        return Response(status=204)


class ChildrenView(APIView):
    def get(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        qs = request.user.children.all().order_by("id")
        return Response(UserSerializer(qs, many=True, context={"request": request}).data)

    @transaction.atomic
    def post(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        request.user = User.objects.select_for_update().get(pk=request.user.pk)
        if not parent_can_add_child(request.user):
            return premium_required_response()
        s = CreateChildSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        username = s.validated_data.get("username")
        password = s.validated_data.get("password")
        if not username:
            username, password = _generate_child_credentials()
        child = User.objects.create_user(
            username=username,
            password=password,
            display_name=s.validated_data.get("display_name", ""),
            gender=s.validated_data.get("gender", ""),
            role=User.ROLE_CHILD,
            parent=request.user,
        )
        return Response(UserSerializer(child, context={"request": request}).data, status=201)


class ChildDetailView(APIView):
    """GET / PATCH / DELETE a single child (parent only)."""

    def _get_child(self, request, child_id):
        if request.user.role != User.ROLE_PARENT:
            return None, Response({"detail": "parents only"}, status=403)
        try:
            child = request.user.children.get(id=child_id)
        except User.DoesNotExist:
            return None, Response({"detail": "child not found"}, status=404)
        return child, None

    def get(self, request, child_id):
        child, err = self._get_child(request, child_id)
        if err:
            return err
        return Response(UserSerializer(child, context={"request": request}).data)

    def patch(self, request, child_id):
        child, err = self._get_child(request, child_id)
        if err:
            return err
        s = UpdateChildSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        if "display_name" in s.validated_data:
            child.display_name = s.validated_data["display_name"]
        if "gender" in s.validated_data:
            child.gender = s.validated_data["gender"]
        child.save()
        return Response(UserSerializer(child, context={"request": request}).data)

    def delete(self, request, child_id):
        child, err = self._get_child(request, child_id)
        if err:
            return err
        child.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ChildAvatarUploadView(APIView):
    """Upload avatar for a child (parent only)."""
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, child_id):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        try:
            child = request.user.children.get(id=child_id)
        except User.DoesNotExist:
            return Response({"detail": "child not found"}, status=404)
        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"detail": "No avatar file provided"}, status=400)
        avatar = validate_avatar(avatar)
        child.avatar = avatar
        child.save(update_fields=["avatar"])
        return Response(UserSerializer(child, context={"request": request}).data)


class FcmTokenView(APIView):
    """Register or update the FCM token for the authenticated user."""

    def post(self, request):
        fcm_token = str(request.data.get("fcm_token", "")).strip()
        installation_id = str(request.data.get("installation_id") or "legacy").strip()
        if not fcm_token or len(fcm_token) > 512 or not 1 <= len(installation_id) <= 64:
            return Response({"detail": "invalid device token or installation_id"}, status=400)
        if not request.user.installations.filter(installation_id=installation_id).exists() and request.user.installations.count() >= 20:
            return Response({"detail": "Device installation limit reached"}, status=400)
        with transaction.atomic():
            DeviceInstallation.objects.filter(fcm_token=fcm_token).exclude(user=request.user).delete()
            User.objects.filter(fcm_token=fcm_token).exclude(pk=request.user.pk).update(fcm_token="")
            DeviceInstallation.objects.update_or_create(user=request.user, installation_id=installation_id,
                                                        defaults={"fcm_token": fcm_token})
            request.user.fcm_token = fcm_token
            request.user.save(update_fields=["fcm_token"])
        _mark_child_joined(request.user)
        return Response({"status": "ok"})


class AvatarUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"detail": "No avatar file provided"}, status=400)
        avatar = validate_avatar(avatar)
        request.user.avatar = avatar
        request.user.save(update_fields=["avatar"])
        return Response(UserSerializer(request.user, context={"request": request}).data)


class InviteCodeView(APIView):
    """GET — return active invite code for parent. POST — generate a new one."""

    def get(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        child, err = _get_parent_child_for_request(request)
        if err:
            return err
        invite = (
            InviteCode.objects.filter(
                parent=request.user,
                child=child,
                used_by__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
        if not invite:
            return Response({"code": None})
        return Response({
            "code": invite.code,
            "child_id": invite.child_id,
            "expires_at": invite.expires_at.isoformat(),
        })

    def post(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        child, err = _get_parent_child_for_request(request)
        if err:
            return err
        # Reuse existing valid code if available
        invite = (
            InviteCode.objects.filter(
                parent=request.user,
                child=child,
                used_by__isnull=True,
                expires_at__gt=timezone.now(),
            )
            .order_by("-created_at")
            .first()
        )
        if not invite:
            code = InviteCode.generate_code()
            while InviteCode.objects.filter(code=code).exists():
                code = InviteCode.generate_code()
            invite = InviteCode.objects.create(
                code=code,
                parent=request.user,
                child=child,
                expires_at=timezone.now() + timedelta(days=3),
            )
        return Response({
            "code": invite.code,
            "child_id": invite.child_id,
            "expires_at": invite.expires_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class RegisterChildWithCodeView(APIView):
    throttle_classes = [AuthenticationThrottle]
    """Child registers themselves using an invite code."""
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = RegisterChildWithCodeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code = "".join(ch for ch in serializer.validated_data["code"] if ch.isascii() and ch.isdigit())
        invite = InviteCode.objects.select_for_update().filter(code=code).first()
        if not invite or not invite.is_valid:
            return Response({"detail": "Invalid, used or expired invite code"}, status=400)
        parent = User.objects.select_for_update().get(pk=invite.parent_id)
        child = invite.child
        status_code = 200
        if child is None:
            name = serializer.validated_data.get("display_name", "").strip()
            if not name:
                return Response({"detail": "Child profile is not ready for this code"}, status=400)
            if not parent_can_add_child(parent):
                return premium_required_response()
            username, password = _generate_child_credentials()
            child = User.objects.create_user(username=username, password=password, display_name=name,
                                             role=User.ROLE_CHILD, parent=parent)
            status_code = 201
        # An intentional new pairing code rotates credentials for the previous child device.
        Token.objects.filter(user=child).delete()
        child.installations.all().delete()
        child.fcm_token = ""
        child.joined_at = timezone.now()
        child.save(update_fields=["fcm_token", "joined_at"])
        invite.used_by = child
        invite.save(update_fields=["used_by"])
        return Response({"token": token_for(child), "user": UserSerializer(child, context={"request": request}).data}, status=status_code)


def invite_landing(request, code):
    """Landing page for invite links — shows code and instructions."""
    try:
        normalized_code = "".join(ch for ch in code if ch.isdigit())
        invite = InviteCode.objects.get(code=normalized_code)
        valid = invite.is_valid
        parent_name = escape(invite.parent.display_name or invite.parent.username)
        child_name = escape(invite.child.display_name) if invite.child else ""
    except InviteCode.DoesNotExist:
        valid = False
        parent_name = ""
        child_name = ""

    if valid:
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Family security — Приглашение</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f0f4ff; display: flex; justify-content: center; align-items: center;
         min-height: 100vh; padding: 20px; }}
  .card {{ background: #fff; border-radius: 24px; padding: 40px 32px; max-width: 400px;
           width: 100%; text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.08); }}
  .icon {{ width: 80px; height: 80px; background: linear-gradient(135deg, #3366FF, #1a1a4e);
           border-radius: 50%; margin: 0 auto 24px; display: flex; align-items: center;
           justify-content: center; font-size: 36px; }}
  h1 {{ color: #1a1a4e; font-size: 24px; margin-bottom: 8px; }}
  .sub {{ color: #6b7280; font-size: 14px; margin-bottom: 24px; }}
  .code-box {{ background: #f0f4ff; border-radius: 16px; padding: 20px; margin-bottom: 24px; }}
  .code {{ font-size: 32px; font-weight: 900; color: #1a1a4e; letter-spacing: 3px; }}
  .label {{ font-size: 12px; color: #6b7280; margin-top: 6px; }}
  .steps {{ text-align: left; margin-bottom: 24px; }}
  .steps li {{ color: #374151; font-size: 14px; margin-bottom: 8px; line-height: 1.5; }}
  .parent {{ color: #3366FF; font-weight: 700; }}
</style>
</head>
<body>
<div class="card">
  <div class="icon">&#x1F46A;</div>
  <h1>Вас приглашают!</h1>
  <p class="sub"><span class="parent">{parent_name}</span> подготовил подключение{f' для {child_name}' if child_name else ''} в Family security</p>
  <div class="code-box">
    <div class="code">{invite.code}</div>
    <div class="label">Код для входа ребёнка</div>
  </div>
  <ol class="steps">
    <li>Скачайте приложение <b>Family security</b></li>
    <li>Откройте приложение</li>
    <li>Введите код выше на первом экране</li>
  </ol>
</div>
</body>
</html>"""
    else:
        html = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Family security — Приглашение</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #f0f4ff; display: flex; justify-content: center; align-items: center;
         min-height: 100vh; padding: 20px; }
  .card { background: #fff; border-radius: 24px; padding: 40px 32px; max-width: 400px;
          width: 100%; text-align: center; box-shadow: 0 8px 32px rgba(0,0,0,0.08); }
  h1 { color: #dc2626; font-size: 22px; margin-bottom: 12px; }
  p { color: #6b7280; font-size: 14px; }
</style>
</head>
<body>
<div class="card">
  <h1>Код недействителен</h1>
  <p>Этот код приглашения истёк или уже был использован. Попросите родителя отправить новый код.</p>
</div>
</body>
</html>"""

    return HttpResponse(html)


class TestModeStatusView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"is_test": bool(getattr(settings, "IS_TEST", False))})


class LoginAsPremiumTestView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        if not (settings.DEBUG and getattr(settings, "IS_TEST", False)):
            return Response(
                {"detail": "Test mode is disabled."},
                status=status.HTTP_403_FORBIDDEN,
            )

        test_username = "test_premium_parent"
        entitlement = getattr(settings, "REVENUECAT_ENTITLEMENT_ID", "family_security_pro")
        expires_at = timezone.now() + timedelta(days=365 * 10)

        user = User.objects.filter(username=test_username).first()
        if user is None:
            user = User.objects.create_user(
                username=test_username,
                password=secrets.token_urlsafe(24),
                display_name="Premium Tester",
                role=User.ROLE_PARENT,
            )

        user.role = User.ROLE_PARENT
        user.is_premium = True
        user.premium_entitlement = entitlement
        user.premium_product_id = "yearly"
        user.premium_expires_at = expires_at
        user.premium_updated_at = timezone.now()
        user.save()

        token = token_for(user)
        return Response(
            {
                "token": token,
                "user": UserSerializer(user, context={"request": request}).data,
            },
            status=status.HTTP_200_OK,
        )

