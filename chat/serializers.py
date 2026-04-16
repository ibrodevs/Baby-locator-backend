from rest_framework import serializers

from .models import Message


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.CharField(source="sender.display_name", read_only=True)

    class Meta:
        model = Message
        fields = ["id", "sender", "receiver", "text", "read", "created_at", "sender_name"]
        read_only_fields = ["id", "sender", "created_at", "read", "sender_name"]


class SendMessageSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=2000)
