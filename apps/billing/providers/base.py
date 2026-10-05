from abc import ABC, abstractmethod


class PaymentProvider(ABC):
    """What every payment method must offer. A real gateway would be one more subclass."""

    name = ""

    @abstractmethod
    def start(self, invoice, **kwargs):
        """Create and return a Payment for this invoice."""

    def checkout_url(self, payment):
        """Where to send the payer to complete the payment, or None if not needed."""
        return None
