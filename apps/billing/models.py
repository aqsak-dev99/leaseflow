from django.db import models

from apps.core.models import OrgScopedModel


class Invoice(OrgScopedModel):
    class Status(models.TextChoices):
        ISSUED = "issued", "Issued"
        PAID = "paid", "Paid"
        OVERDUE = "overdue", "Overdue"
        WAIVED = "waived", "Waived"

    lease = models.ForeignKey("properties.Lease", on_delete=models.PROTECT, related_name="invoices")
    period = models.DateField(help_text="First day of the month being billed.")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    due_date = models.DateField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ISSUED)
    last_reminder_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lease", "period"], name="one_invoice_per_lease_per_period"
            )
        ]

    def __str__(self):
        return f"Invoice {self.pk}: {self.period:%b %Y}"

    @property
    def is_unpaid(self):
        return self.status in (self.Status.ISSUED, self.Status.OVERDUE)


class Payment(OrgScopedModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    invoice = models.ForeignKey(Invoice, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    provider = models.CharField(max_length=30)
    provider_reference = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    paid_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Payment {self.pk} ({self.provider}, {self.status})"


class WebhookEvent(models.Model):
    """A message received from a payment gateway.

    Not organization-scoped: it arrives from outside before we know whose it is.
    The unique constraint is what stops the same event being handled twice.
    """

    provider = models.CharField(max_length=30)
    event_id = models.CharField(max_length=100)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    payment = models.ForeignKey(
        Payment, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "event_id"], name="one_row_per_webhook_event"
            )
        ]

    def __str__(self):
        return f"{self.provider} event {self.event_id}"
