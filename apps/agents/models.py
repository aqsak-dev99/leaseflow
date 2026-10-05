from django.conf import settings
from django.db import models
from django.db.models import Q

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


class ApprovalRequest(OrgScopedModel):
    """Something an agent wants done that only a landlord may decide."""

    class Kind(models.TextChoices):
        REMINDER = "reminder", "Rent reminder"
        WAIVER = "waiver", "Waiver request"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    invoice = models.ForeignKey(
        "billing.Invoice", on_delete=models.CASCADE, related_name="approval_requests"
    )
    subject = models.CharField(max_length=200)
    body = models.TextField()
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    run = models.ForeignKey(
        AgentRun, on_delete=models.SET_NULL, null=True, blank=True, related_name="approval_requests"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True)

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["invoice", "kind"],
                condition=Q(status="pending"),
                name="one_pending_request_per_invoice_and_kind",
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()} for invoice {self.invoice_id} ({self.status})"
