from django.conf import settings
from django.db import models

from apps.core.models import OrgScopedModel


class MaintenanceTicket(OrgScopedModel):
    class Category(models.TextChoices):
        PLUMBING = "plumbing", "Plumbing"
        ELECTRICAL = "electrical", "Electrical"
        APPLIANCE = "appliance", "Appliance"
        STRUCTURAL = "structural", "Structural"
        OTHER = "other", "Other"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        IN_PROGRESS = "in_progress", "In progress"
        RESOLVED = "resolved", "Resolved"

    unit = models.ForeignKey("properties.Unit", on_delete=models.PROTECT, related_name="tickets")
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="tickets"
    )
    title = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=Category.choices, default=Category.OTHER)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)
    cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"#{self.pk} {self.title}"


class TicketUpdate(OrgScopedModel):
    """A history entry on a ticket: a comment, a status change, or both."""

    ticket = models.ForeignKey(MaintenanceTicket, on_delete=models.CASCADE, related_name="updates")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    via_agent = models.BooleanField(default=False)
    note = models.TextField(blank=True)
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"Update on #{self.ticket_id}"
