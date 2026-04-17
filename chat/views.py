from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User

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
