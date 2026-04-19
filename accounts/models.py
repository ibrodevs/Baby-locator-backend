import random
import string

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from datetime import timedelta


class User(AbstractUser):
    ROLE_PARENT = "parent"
    ROLE_CHILD = "child"
    ROLE_CHOICES = [
        (ROLE_PARENT, "Parent"),
        (ROLE_CHILD, "Child"),
    ]

    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_PARENT)
    display_name = models.CharField(max_length=120, blank=True)
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="children",
    )
    fcm_token = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"{self.username} ({self.role})"


class InviteCode(models.Model):
    code = models.CharField(max_length=10, unique=True, db_index=True)
    parent = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="invite_codes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="used_invite",
    )

    @staticmethod
    def generate_code():
        chars = string.ascii_uppercase + string.digits
        part1 = "".join(random.choices(chars, k=3))
        part2 = "".join(random.choices(chars, k=4))
        return f"{part1}-{part2}"

    @property
    def is_valid(self):
        return self.used_by is None and self.expires_at > timezone.now()

    def __str__(self):
        return f"{self.code} (parent={self.parent.username})"
