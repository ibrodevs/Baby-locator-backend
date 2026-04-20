from rest_framework import serializers

from .models import Message, Reward, Task


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True)
    is_read = serializers.BooleanField(read_only=True)

    class Meta:
        model = Message
        fields = [
            "id", "sender", "receiver", "text",
            "status", "is_read", "read_at",
            "created_at", "sender_name",
        ]
        read_only_fields = [
            "id", "sender", "created_at",
            "status", "is_read", "read_at", "sender_name",
        ]


class SendMessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000)


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
