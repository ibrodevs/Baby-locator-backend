from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User
from tracking.fcm import send_notification_push
from tracking.models import Alert

from .models import Message, Reward, Task
from .serializers import (
    CreateRewardSerializer,
    CreateTaskSerializer,
    MessageSerializer,
    RewardSerializer,
    SendMessageSerializer,
    TaskSerializer,
)


class ChatMessagesView(APIView):
    """
    GET  /api/chat/<child_id>/messages/ — list messages between current user and child
    POST /api/chat/<child_id>/messages/ — send a message to child (or parent sends to child)
    """
    parser_classes = [MultiPartParser, FormParser, JSONParser]

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

        return Response(
            MessageSerializer(
                messages,
                many=True,
                context={"request": request},
            ).data
        )

    def post(self, request, child_id):
        child, parent = self._get_child_and_validate(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        text = (request.data.get("text") or "").strip()
        uploaded_file = request.FILES.get("file")

        if not text and not uploaded_file:
            return Response(
                {"detail": "text or file is required"}, status=400
            )

        user = request.user
        if user.role == User.ROLE_PARENT:
            receiver = child
        else:
            receiver = parent

        msg = Message.objects.create(
            sender=user,
            receiver=receiver,
            text=text,
            file=uploaded_file,
            file_name=uploaded_file.name if uploaded_file else "",
        )

        alert = None
        if user.role == User.ROLE_CHILD and child.parent:
            alert = Alert.objects.create(
                child=child,
                parent=child.parent,
                alert_type=Alert.TYPE_CHAT_MESSAGE,
                title=f"Сообщение от {user.display_name or user.username}",
                message=text[:200] if text else f"📎 {uploaded_file.name}" if uploaded_file else "",
            )

        # Send FCM push to the receiver
        sender_name = user.display_name or user.username
        push_body = text[:200] if text else f"📎 {uploaded_file.name}" if uploaded_file else ""
        if receiver.fcm_token:
            send_notification_push(
                receiver.fcm_token,
                notification_type="chat_message",
                title=f"Сообщение от {sender_name}",
                body=push_body,
                extra_data={
                    "message_id": msg.id,
                    "child_id": child.id,
                    "sender_id": user.id,
                    "alert_id": alert.id if alert else None,
                },
            )

        return Response(
            MessageSerializer(msg, context={"request": request}).data,
            status=201,
        )


class MarkMessagesReadView(APIView):
    """
    POST /api/chat/<child_id>/messages/read/ — mark messages as read.
    Body: {"message_ids": [1, 2, 3]}  — optional, if omitted marks ALL unread.
    """

    def post(self, request, child_id):
        child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
        user = request.user

        if user.role == User.ROLE_PARENT:
            if child.parent_id != user.id:
                return Response({"detail": "forbidden"}, status=403)
            partner = child
        elif user.role == User.ROLE_CHILD:
            if user.id != child.id:
                return Response({"detail": "forbidden"}, status=403)
            partner = child.parent
        else:
            return Response({"detail": "forbidden"}, status=403)

        qs = Message.objects.filter(
            sender=partner,
            receiver=user,
            status=Message.STATUS_SENT,
        )

        message_ids = request.data.get("message_ids")
        if message_ids:
            qs = qs.filter(id__in=message_ids)

        now = timezone.now()
        updated = qs.update(status=Message.STATUS_READ, read_at=now)

        return Response({"updated": updated})


def _validate_parent_child(request, child_id):
    """Validate that the request user has access to this child."""
    child = get_object_or_404(User, id=child_id, role=User.ROLE_CHILD)
    user = request.user
    if user.role == User.ROLE_PARENT:
        if child.parent_id != user.id:
            return None, None
    elif user.role == User.ROLE_CHILD:
        if user.id != child.id:
            return None, None
    return child, child.parent


class TaskListView(APIView):
    """
    GET  /api/chat/<child_id>/tasks/ — list tasks for this child
    POST /api/chat/<child_id>/tasks/ — create a task (parent only)
    """

    def get(self, request, child_id):
        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        tasks = Task.objects.filter(child=child)
        return Response(TaskSerializer(tasks, many=True).data)

    def post(self, request, child_id):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "Only parents can create tasks"}, status=403)

        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        s = CreateTaskSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        task = Task.objects.create(
            parent=request.user,
            child=child,
            **s.validated_data,
        )

        # Send FCM push to child about new task
        parent_name = request.user.display_name or request.user.username
        if child.fcm_token:
            alert = Alert.objects.create(
                child=child,
                parent=request.user,
                alert_type=Alert.TYPE_TASK_ASSIGNED,
                title=f"Задание для {child.display_name or child.username}",
                message=task.title,
            )
            send_notification_push(
                child.fcm_token,
                notification_type="task_assigned",
                title=f"Новое задание от {parent_name}",
                body=task.title,
                extra_data={
                    "child_id": child.id,
                    "task_id": task.id,
                    "alert_id": alert.id,
                },
            )
        else:
            Alert.objects.create(
                child=child,
                parent=request.user,
                alert_type=Alert.TYPE_TASK_ASSIGNED,
                title=f"Задание для {child.display_name or child.username}",
                message=task.title,
            )

        return Response(TaskSerializer(task).data, status=201)


class TaskActionView(APIView):
    """
    PATCH  /api/chat/<child_id>/tasks/<task_id>/complete/ — child marks as completed
    PATCH  /api/chat/<child_id>/tasks/<task_id>/approve/  — parent approves (awards stars)
    DELETE /api/chat/<child_id>/tasks/<task_id>/           — parent deletes task
    """

    def patch(self, request, child_id, task_id, action):
        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        task = get_object_or_404(Task, id=task_id, child=child)

        if action == "complete":
            if task.status != Task.STATUS_PENDING:
                return Response({"detail": "Task is not pending"}, status=400)
            task.status = Task.STATUS_COMPLETED
            task.completed_at = timezone.now()
            task.save()
        elif action == "approve":
            if request.user.role != User.ROLE_PARENT:
                return Response({"detail": "Only parents can approve"}, status=403)
            if task.status != Task.STATUS_COMPLETED:
                return Response({"detail": "Task is not completed yet"}, status=400)
            task.status = Task.STATUS_APPROVED
            task.save()
        else:
            return Response({"detail": "Invalid action"}, status=400)

        return Response(TaskSerializer(task).data)

    def delete(self, request, child_id, task_id, action=None):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "Only parents can delete tasks"}, status=403)

        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        task = get_object_or_404(Task, id=task_id, child=child)
        task.delete()
        return Response(status=204)


class StarsView(APIView):
    """
    GET /api/chat/<child_id>/stars/ — get total earned stars for a child
    """

    def get(self, request, child_id):
        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        total = Task.objects.filter(
            child=child, status=Task.STATUS_APPROVED,
        ).aggregate(total=Sum("reward_stars"))["total"] or 0

        # Subtract stars spent on claimed rewards
        spent = Reward.objects.filter(
            child=child, claimed=True,
        ).aggregate(total=Sum("required_stars"))["total"] or 0

        return Response({
            "total_earned": total,
            "total_spent": spent,
            "balance": total - spent,
        })


class RewardListView(APIView):
    """
    GET  /api/chat/<child_id>/rewards/ — list rewards
    POST /api/chat/<child_id>/rewards/ — create a reward (parent only)
    """

    def get(self, request, child_id):
        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        rewards = Reward.objects.filter(child=child)
        return Response(RewardSerializer(rewards, many=True).data)

    def post(self, request, child_id):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "Only parents can create rewards"}, status=403)

        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        s = CreateRewardSerializer(data=request.data)
        s.is_valid(raise_exception=True)

        reward = Reward.objects.create(
            parent=request.user,
            child=child,
            **s.validated_data,
        )
        return Response(RewardSerializer(reward).data, status=201)


class RewardClaimView(APIView):
    """
    PATCH  /api/chat/<child_id>/rewards/<reward_id>/claim/ — claim a reward
    DELETE /api/chat/<child_id>/rewards/<reward_id>/       — delete a reward (parent only)
    """

    def patch(self, request, child_id, reward_id):
        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        reward = get_object_or_404(Reward, id=reward_id, child=child)
        if reward.claimed:
            return Response({"detail": "Already claimed"}, status=400)

        # Check if child has enough stars
        total_earned = Task.objects.filter(
            child=child, status=Task.STATUS_APPROVED,
        ).aggregate(total=Sum("reward_stars"))["total"] or 0

        total_spent = Reward.objects.filter(
            child=child, claimed=True,
        ).aggregate(total=Sum("required_stars"))["total"] or 0

        balance = total_earned - total_spent
        if balance < reward.required_stars:
            return Response({"detail": "Not enough stars"}, status=400)

        reward.claimed = True
        reward.claimed_at = timezone.now()
        reward.save()
        return Response(RewardSerializer(reward).data)

    def delete(self, request, child_id, reward_id):
        if request.user.role != User.ROLE_PARENT:
            return Response({"detail": "Only parents can delete rewards"}, status=403)

        child, parent = _validate_parent_child(request, child_id)
        if child is None:
            return Response({"detail": "forbidden"}, status=403)

        reward = get_object_or_404(Reward, id=reward_id, child=child)
        reward.delete()
        return Response(status=204)


class ChildNotificationsView(APIView):
    """
    GET /api/chat/notifications/ — child gets unread messages + pending tasks.
    Used as a polling fallback when FCM is unavailable.
    """

    def get(self, request):
        user = request.user
        if user.role != User.ROLE_CHILD:
            return Response({"detail": "children only"}, status=403)

        unread_messages = Message.objects.filter(
            receiver=user,
            status=Message.STATUS_SENT,
        ).order_by("-created_at")[:20]

        pending_tasks = Task.objects.filter(
            child=user,
            status=Task.STATUS_PENDING,
        ).order_by("-created_at")[:20]

        notifications = []

        for msg in unread_messages:
            sender_name = msg.sender.display_name or msg.sender.username
            notifications.append({
                "id": f"msg_{msg.id}",
                "type": "chat_message",
                "title": f"Сообщение от {sender_name}",
                "body": msg.text[:200],
                "created_at": msg.created_at.isoformat(),
            })

        for task in pending_tasks:
            parent_name = task.parent.display_name or task.parent.username
            notifications.append({
                "id": f"task_{task.id}",
                "type": "task_assigned",
                "title": f"Задание от {parent_name}",
                "body": task.title,
                "created_at": task.created_at.isoformat(),
            })

        notifications.sort(key=lambda n: n["created_at"], reverse=True)
        return Response(notifications)
