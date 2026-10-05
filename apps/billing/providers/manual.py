from django.utils import timezone

from ..models import Payment
from .base import PaymentProvider


class ManualProvider(PaymentProvider):
    """Cash or bank transfer that the landlord records by hand. It succeeds at once."""

    name = "manual"

    def start(self, invoice, reference="", **kwargs):
        return Payment.objects.create(
            organization=invoice.organization,
            invoice=invoice,
            amount=invoice.amount,
            provider=self.name,
            provider_reference=reference[:100],
            status=Payment.Status.SUCCEEDED,
            paid_at=timezone.now(),
        )
