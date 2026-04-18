from django.contrib.auth.models import AbstractUser
from django.db import models


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
