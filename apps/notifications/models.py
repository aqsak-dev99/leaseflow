from django.conf import settings
from django.db import models

from apps.core.models import OrgScopedModel


class Notification(OrgScopedModel):
    """Something one user should know about: shown under the bell until they read it."""

    class Kind(models.TextChoices):
        RENT = "rent", "Rent"
        REPAIR = "repair", "Repair"
        APPROVAL = "approval", "Approval"
        TENANT = "tenant", "Tenant"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=300, blank=True)
    url = models.CharField(max_length=200, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["user", "read_at"], name="notification_user_unread")]

    def __str__(self):
        return f"{self.title} (for {self.user_id})"

    @property
    def is_unread(self):
        return self.read_at is None
