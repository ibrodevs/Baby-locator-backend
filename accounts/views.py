from datetime import timedelta
import secrets
import uuid

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import InviteCode, User
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


class RegisterParentView(APIView):
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
    permission_classes = [AllowAny]

    def post(self, request):
        s = LoginSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        user = s.validated_data["user"]
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


class ChildrenView(APIView):
    def get(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        qs = request.user.children.all().order_by("id")
        return Response(UserSerializer(qs, many=True, context={"request": request}).data)

    def post(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        s = CreateChildSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        child = User.objects.create_user(
            username=s.validated_data["username"],
            password=s.validated_data["password"],
            display_name=s.validated_data.get("display_name", ""),
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
        child.avatar = avatar
        child.save(update_fields=["avatar"])
        return Response(UserSerializer(child, context={"request": request}).data)


class FcmTokenView(APIView):
    """Register or update the FCM token for the authenticated user."""

    def post(self, request):
        fcm_token = request.data.get("fcm_token", "").strip()
        if not fcm_token:
            return Response({"detail": "fcm_token is required"}, status=400)
        request.user.fcm_token = fcm_token
        request.user.save(update_fields=["fcm_token"])
        return Response({"status": "ok"})


class AvatarUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"detail": "No avatar file provided"}, status=400)
        request.user.avatar = avatar
        request.user.save(update_fields=["avatar"])
        return Response(UserSerializer(request.user, context={"request": request}).data)


class InviteCodeView(APIView):
    """GET — return active invite code for parent. POST — generate a new one."""

    def get(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        invite = (
            InviteCode.objects.filter(
                parent=request.user,
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
            "expires_at": invite.expires_at.isoformat(),
        })

    def post(self, request):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "parents only"}, status=403)
        # Reuse existing valid code if available
        invite = (
            InviteCode.objects.filter(
                parent=request.user,
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
                expires_at=timezone.now() + timedelta(days=3),
            )
        return Response({
            "code": invite.code,
            "expires_at": invite.expires_at.isoformat(),
        }, status=status.HTTP_201_CREATED)


class RegisterChildWithCodeView(APIView):
    """Child registers themselves using an invite code."""
    permission_classes = [AllowAny]

    def post(self, request):
        s = RegisterChildWithCodeSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        code_str = s.validated_data["code"].strip().upper()
        display_name = s.validated_data["display_name"]
        try:
            invite = InviteCode.objects.get(code=code_str)
        except InviteCode.DoesNotExist:
            return Response({"detail": "Invalid invite code"}, status=400)
        if invite.expires_at <= timezone.now():
            return Response({"detail": "Invite code expired"}, status=400)

        child = (
            invite.parent.children.filter(display_name__iexact=display_name)
            .order_by("id")
            .first()
        )
        status_code = status.HTTP_200_OK

        if child is None:
            username, password = _generate_child_credentials()
            child = User.objects.create_user(
                username=username,
                password=password,
                display_name=display_name,
                role=User.ROLE_CHILD,
                parent=invite.parent,
            )
            status_code = status.HTTP_201_CREATED

        return Response(
            {"token": token_for(child), "user": UserSerializer(child, context={"request": request}).data},
            status=status_code,
        )


def invite_landing(request, code):
    """Landing page for invite links — shows code and instructions."""
    try:
        invite = InviteCode.objects.get(code=code.upper())
        valid = invite.is_valid
        parent_name = invite.parent.display_name or invite.parent.username
    except InviteCode.DoesNotExist:
        valid = False
        parent_name = ""

    if valid:
        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kid Security — Приглашение</title>
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
  <p class="sub"><span class="parent">{parent_name}</span> приглашает вас в семейный круг Kid Security</p>
  <div class="code-box">
    <div class="code">{invite.code}</div>
    <div class="label">Код приглашения</div>
  </div>
  <ol class="steps">
    <li>Скачайте приложение <b>Kid Security</b></li>
    <li>Откройте и выберите <b>«Я ребёнок»</b></li>
    <li>Введите код выше и затем укажите отображаемое имя</li>
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
<title>Kid Security — Приглашение</title>
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
