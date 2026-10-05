"""A pretend payment gateway for demos and tests. No real money moves.

It behaves like a real one in the ways that matter: the payer is sent to a
checkout page, and the result comes back later as a signed webhook.
"""

import hashlib
import hmac
import json
import uuid

from django.conf import settings
from django.urls import reverse

from ..models import Payment
from .base import PaymentProvider


def sign(body: bytes) -> str:
    secret = settings.FAKE_GATEWAY_WEBHOOK_SECRET.encode()
    return hmac.new(secret, body, hashlib.sha256).hexdigest()


def verify(body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(body), signature or "")


class FakeGatewayProvider(PaymentProvider):
    name = "fake_gateway"

    def start(self, invoice, **kwargs):
        pending = invoice.payments.filter(
            provider=self.name, status=Payment.Status.PENDING
        ).first()
        if pending is not None:
            return pending
        return Payment.objects.create(
            organization=invoice.organization,
            invoice=invoice,
            amount=invoice.amount,
            provider=self.name,
            provider_reference=uuid.uuid4().hex,
        )

    def checkout_url(self, payment):
        return reverse("billing:fake_checkout", args=[payment.provider_reference])

    def build_event(self, payment, succeeded=True):
        """What the gateway would send us: a JSON body and its signature."""
        event = {
            "event_id": uuid.uuid4().hex,
            "type": "payment.succeeded" if succeeded else "payment.failed",
            "reference": payment.provider_reference,
            "amount": str(payment.amount),
        }
        body = json.dumps(event).encode()
        return body, sign(body)
