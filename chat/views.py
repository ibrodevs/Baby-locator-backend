from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User

from .models import Message
from .serializers import MessageSerializer, SendMessageSerializer


class ChatMessagesView(APIView):
    """
    GET  /api/chat/<child_id>/messages/ — list messages between current user and child
    POST /api/chat/<child_id>/messages/ — send a message to child (or parent sends to child)
    """

    def _get_child_and_validate(self, request, child_id):
        child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
        user = request.user
        if user.role == User.ROLE_PARENT:
            if child.parent_id != user.id:
                return None, None
        elif user.role == User.ROLE_CHILD:
            if user.id != child.id:
                return None, None
        return child, child.parent

    def get(self, request, child_id):
        child, parent = self._get_child_and_validate(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        messages = Message.objects.filter(
            Q(sender=parent, receiver=child) | Q(sender=child, receiver=parent)
        ).order_by("created_at")

        # Mark unread messages as read for the current user
        messages.filter(receiver=request.user, read=False).update(read=True)

        return Response(MessageSerializer(messages, many=True).data)

    def post(self, request, child_id):
        child, parent = self._get_child_and_validate(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        s = SendMessageSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        user = request.user
        if user.role == User.ROLE_PARENT:
            receiver = child
        else:
            receiver = parent

        msg = Message.objects.create(
            sender=user,
            receiver=receiver,
            text=s.validated_data["text"],
        )
        return Response(MessageSerializer(msg).data, status=201)
