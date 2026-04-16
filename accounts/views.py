from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import User
from .serializers import (
    CreateChildSerializer,
    LoginSerializer,
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


class AvatarUploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        avatar = request.FILES.get("avatar")
        if not avatar:
            return Response({"detail": "No avatar file provided"}, status=400)
        request.user.avatar = avatar
        request.user.save(update_fields=["avatar"])
        return Response(UserSerializer(request.user, context={"request": request}).data)
