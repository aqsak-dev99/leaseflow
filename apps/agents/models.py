from django.conf import settings
from django.db import models

from apps.core.models import OrgScopedModel


class Conversation(OrgScopedModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversations"
    )
    title = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return self.title or f"Conversation {self.pk}"


class AgentRun(OrgScopedModel):
    """One run of the agent system, with every step it took. This is the trace."""

    class Trigger(models.TextChoices):
        CHAT = "chat", "Chat"
        EVENT = "event", "Event"

    class Status(models.TextChoices):
        OK = "ok", "OK"
        ERROR = "error", "Error"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.SET_NULL, null=True, blank=True, related_name="runs"
    )
    trigger = models.CharField(max_length=20, choices=Trigger.choices, default=Trigger.CHAT)
    route = models.CharField(max_length=40, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OK)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    latency_ms = models.PositiveIntegerField(default=0)
    steps = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True)

    def __str__(self):
        return f"Run {self.pk} ({self.route or 'no route'})"


class Message(OrgScopedModel):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"

    conversation = models.ForeignKey(
        Conversation, on_delete=models.CASCADE, related_name="messages"
    )
    role = models.CharField(max_length=20, choices=Role.choices)
    content = models.TextField()
    citations = models.JSONField(default=list, blank=True)
    run = models.ForeignKey(
        AgentRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages"
    )

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.role}: {self.content[:40]}"
