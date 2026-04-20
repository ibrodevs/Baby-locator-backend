from django.conf import settings
from django.db import models


class Message(models.Model):
    """Chat message between a parent and one of their children."""
    STATUS_SENT = "sent"
    STATUS_READ = "read"
    STATUS_CHOICES = [
        (STATUS_SENT, "Sent"),       # ✓  — отправлено
        (STATUS_READ, "Read"),       # ✓✓ — прочитано
    ]

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    receiver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_messages",
    )
    text = models.TextField(blank=True)
    file = models.FileField(upload_to="chat_files/", null=True, blank=True)
    file_name = models.CharField(max_length=255, blank=True, default="")
    status = models.CharField(
        max_length=8, choices=STATUS_CHOICES, default=STATUS_SENT,
    )
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def save(self, *args, **kwargs):
        # Keep DB writes safe even if callers omit file_name or pass None.
        if self.file and not self.file_name:
            self.file_name = getattr(self.file, "name", "") or ""
        else:
            self.file_name = self.file_name or ""
        super().save(*args, **kwargs)

    @property
    def is_read(self):
        return self.status == self.STATUS_READ

    def __str__(self):
        return f"{self.sender.username} -> {self.receiver.username}: {self.text[:40]}"


class Task(models.Model):
    """A task assigned by a parent to a child, with star rewards."""
    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_APPROVED = "approved"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_APPROVED, "Approved"),
    ]

    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_tasks",
    )
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="assigned_tasks",
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    reward_stars = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.status}) -> {self.child.username}"


class Reward(models.Model):
    """A reward that a child can earn by collecting enough stars."""
    parent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="created_rewards",
    )
    child = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="available_rewards",
    )
    title = models.CharField(max_length=200)
    required_stars = models.PositiveIntegerField()
    claimed = models.BooleanField(default=False)
    claimed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} ({self.required_stars} stars) -> {self.child.username}"
