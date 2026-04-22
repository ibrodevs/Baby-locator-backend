from django.contrib.auth import authenticate
from rest_framework import serializers
from rest_framework.authtoken.models import Token

from .models import User


class UserSerializer(serializers.ModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "role",
            "display_name",
            "gender",
            "parent",
            "avatar_url",
        ]

    def get_avatar_url(self, obj):
        if obj.avatar:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.avatar.url)
            return obj.avatar.url
        return None


class RegisterParentSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True, min_length=4)
    display_name = serializers.CharField(required=False, allow_blank=True)

    def create(self, validated_data):
        if User.objects.filter(username=validated_data["username"]).exists():
            raise serializers.ValidationError({"username": "already taken"})
        user = User.objects.create_user(
            username=validated_data["username"],
            password=validated_data["password"],
            display_name=validated_data.get("display_name", ""),
            role=User.ROLE_PARENT,
        )
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            username=attrs["username"],
            password=attrs["password"],
        )
        if not user:
            raise serializers.ValidationError("Invalid credentials")
        attrs["user"] = user
        return attrs


class CreateChildSerializer(serializers.Serializer):
    username = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        min_length=4,
    )
    display_name = serializers.CharField(required=False, allow_blank=True)
    gender = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        username = attrs.get("username", "").strip()
        password = attrs.get("password", "")
        gender = attrs.get("gender", "").strip()

        if username:
            if User.objects.filter(username=username).exists():
                raise serializers.ValidationError({"username": "already taken"})
            if len(password) < 4:
                raise serializers.ValidationError(
                    {"password": "Ensure this field has at least 4 characters."}
                )
            attrs["username"] = username
        else:
            attrs.pop("username", None)
            attrs.pop("password", None)

        if gender and gender not in {User.GENDER_BOY, User.GENDER_GIRL}:
            raise serializers.ValidationError({"gender": "invalid value"})

        if "display_name" in attrs:
            attrs["display_name"] = attrs["display_name"].strip()
        if gender:
            attrs["gender"] = gender

        return attrs


class UpdateChildSerializer(serializers.Serializer):
    display_name = serializers.CharField(required=False, allow_blank=True)
    gender = serializers.CharField(required=False, allow_blank=True)

    def validate_gender(self, value):
        value = value.strip()
        if value and value not in {User.GENDER_BOY, User.GENDER_GIRL}:
            raise serializers.ValidationError("invalid value")
        return value


class UpdateProfileSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    display_name = serializers.CharField(required=False, allow_blank=True)

    def validate_username(self, value):
        user = self.context["request"].user
        if (
            User.objects.exclude(id=user.id)
            .filter(username=value)
            .exists()
        ):
            raise serializers.ValidationError("already taken")
        return value


class RegisterChildWithCodeSerializer(serializers.Serializer):
    code = serializers.CharField()
    display_name = serializers.CharField(required=False, allow_blank=True)

    def validate_display_name(self, value):
        value = value.strip()
        return value


class AuthResponseSerializer(serializers.Serializer):
    token = serializers.CharField()
    user = UserSerializer()


def token_for(user):
    token, _ = Token.objects.get_or_create(user=user)
    return token.key
