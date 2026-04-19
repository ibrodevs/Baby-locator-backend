from datetime import timedelta

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
        try:
            invite = InviteCode.objects.get(code=code_str)
        except InviteCode.DoesNotExist:
            return Response({"detail": "Invalid invite code"}, status=400)
        if not invite.is_valid:
            return Response({"detail": "Invite code expired or already used"}, status=400)
        child = User.objects.create_user(
            username=s.validated_data["username"],
            password=s.validated_data["password"],
            display_name=s.validated_data.get("display_name", ""),
            role=User.ROLE_CHILD,
            parent=invite.parent,
        )
        invite.used_by = child
        invite.save(update_fields=["used_by"])
        return Response(
            {"token": token_for(child), "user": UserSerializer(child, context={"request": request}).data},
            status=status.HTTP_201_CREATED,
        )
