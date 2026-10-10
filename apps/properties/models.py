from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.models import OrgScopedModel


class Property(OrgScopedModel):
    name = models.CharField(max_length=200)
    address = models.CharField(max_length=300)
    city = models.CharField(max_length=100)

    class Meta:
        verbose_name_plural = "properties"

    def __str__(self):
        return self.name


class Unit(OrgScopedModel):
    class Status(models.TextChoices):
        VACANT = "vacant", "Vacant"
        OCCUPIED = "occupied", "Occupied"

    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name="units")
    unit_number = models.CharField(max_length=20)
    bedrooms = models.PositiveSmallIntegerField(default=1)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.VACANT)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["property", "unit_number"], name="unique_unit_per_property"
            )
        ]

    def __str__(self):
        return f"{self.property.name} / {self.unit_number}"


class Lease(OrgScopedModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ENDED = "ended", "Ended"

    unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="leases")
    tenant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="leases"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    rent_amount = models.DecimalField(max_digits=10, decimal_places=2)
    deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    due_day = models.PositiveSmallIntegerField(default=1)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["unit"],
                condition=Q(status="active"),
                name="one_active_lease_per_unit",
            )
        ]

    def __str__(self):
        return f"Lease: {self.unit} ({self.tenant.email})"


class TenantInvitation(OrgScopedModel):
    """A landlord's offer of a unit to a future tenant, accepted through a one-time link.

    The link contains a random token. Only a hash of that token is stored, so
    reading the database is not enough to accept an invitation.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        CANCELLED = "cancelled", "Cancelled"

    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="invitations")
    email = models.EmailField()
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    rent_amount = models.DecimalField(max_digits=10, decimal_places=2)
    deposit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    due_day = models.PositiveSmallIntegerField(default=1)
    token_hash = models.CharField(max_length=64, unique=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    lease = models.ForeignKey(
        Lease, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["unit"],
                condition=Q(status="pending"),
                name="one_pending_invitation_per_unit",
            )
        ]

    def __str__(self):
        return f"Invitation: {self.email} to {self.unit}"

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_open(self):
        return self.status == self.Status.PENDING and not self.is_expired
