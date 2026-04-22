from rest_framework import serializers

from .models import Message, Reward, Task


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField()
    sender_avatar_url = serializers.SerializerMethodField()
    is_read = serializers.BooleanField(read_only=True)
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id", "sender", "receiver", "text",
            "file", "file_name", "file_url",
            "status", "is_read", "read_at",
            "created_at", "sender_name", "sender_avatar_url",
        ]
        read_only_fields = [
            "id", "sender", "created_at",
            "status", "is_read", "read_at",
            "sender_name", "sender_avatar_url", "file_url",
        ]

    def get_sender_name(self, obj):
        return "Родитель" if obj.sender.role == "parent" else "Ребёнок"

    def get_sender_avatar_url(self, obj):
        if not obj.sender.avatar:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.sender.avatar.url)
        return obj.sender.avatar.url

    def get_file_url(self, obj):
        if not obj.file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url


class SendMessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000, required=False, default="", allow_blank=True)


class TaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = Task
        fields = [
            "id", "parent", "child", "title", "description",
            "reward_stars", "status", "created_at", "completed_at",
        ]
        read_only_fields = ["id", "parent", "created_at", "completed_at"]


class CreateTaskSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    description = serializers.CharField(required=False, default="", allow_blank=True)
    reward_stars = serializers.IntegerField(min_value=0, default=0)


class RewardSerializer(serializers.ModelSerializer):
    class Meta:
        model = Reward
        fields = [
            "id", "parent", "child", "title", "required_stars",
            "claimed", "claimed_at", "created_at",
        ]
        read_only_fields = ["id", "parent", "created_at", "claimed_at"]


class CreateRewardSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    required_stars = serializers.IntegerField(min_value=1)
