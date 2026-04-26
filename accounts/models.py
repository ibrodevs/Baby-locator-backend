import random
import string

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    ROLE_PARENT = "parent"
    ROLE_CHILD = "child"
    GENDER_BOY = "boy"
    GENDER_GIRL = "girl"
    ROLE_CHOICES = [
        (ROLE_PARENT, "Parent"),
        (ROLE_CHILD, "Child"),
    ]
    GENDER_CHOICES = [
        (GENDER_BOY, "Boy"),
        (GENDER_GIRL, "Girl"),
    ]

    role = models.CharField(max_length=16, choices=ROLE_CHOICES, default=ROLE_PARENT)
    display_name = models.CharField(max_length=120, blank=True)
    gender = models.CharField(
        max_length=16,
        choices=GENDER_CHOICES,
        blank=True,
        default="",
    )
    avatar = models.ImageField(upload_to="avatars/", null=True, blank=True)
    joined_at = models.DateTimeField(null=True, blank=True)
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
    child = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="child_invite_codes",
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
        return "".join(random.choices(string.digits, k=6))

    @property
    def is_valid(self):
        return self.used_by is None and self.expires_at > timezone.now()

    def __str__(self):
        if self.child_id:
            return f"{self.code} (child={self.child.username})"
        return f"{self.code} (parent={self.parent.username})"
