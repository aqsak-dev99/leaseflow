"""Handles messages from the payment gateway.

Two protections matter here:
1. The signature proves the message really came from the gateway.
2. The unique event ID means a repeated delivery is recognised and ignored.
"""

import json
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Payment, WebhookEvent
from .providers.fake_gateway import FakeGatewayProvider, verify
from .services import settle

PROVIDER = FakeGatewayProvider.name


class InvalidSignature(Exception):
    pass


class InvalidPayload(Exception):
    pass


def process_webhook(body: bytes, signature: str) -> str:
    """Returns "processed" or "duplicate". Raises if the message cannot be trusted."""
    if not verify(body, signature):
        raise InvalidSignature
    try:
        data = json.loads(body)
        event_id = str(data["event_id"])
        event_type = str(data["type"])
        reference = str(data["reference"])
        amount = Decimal(str(data["amount"]))
    except (ValueError, KeyError, TypeError, InvalidOperation) as exc:
        raise InvalidPayload from exc

    try:
        with transaction.atomic():
            event = WebhookEvent.objects.create(provider=PROVIDER, event_id=event_id, payload=data)
            payment = (
                Payment.objects.select_for_update()
                .filter(provider=PROVIDER, provider_reference=reference)
                .first()
            )
            if payment is not None and payment.status == Payment.Status.PENDING:
                if event_type == "payment.succeeded" and amount == payment.amount:
                    settle(payment)
                else:
                    payment.status = Payment.Status.FAILED
                    payment.save(update_fields=["status"])
            event.payment = payment
            event.processed_at = timezone.now()
            event.save(update_fields=["payment", "processed_at"])
    except IntegrityError:
        return "duplicate"
    return "processed"
