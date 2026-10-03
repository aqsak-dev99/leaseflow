from django.conf import settings
from django.db import models
from django.db.models import Q

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
