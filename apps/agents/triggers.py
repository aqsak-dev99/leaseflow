"""Agent runs that start from a system event, with nobody typing."""

import datetime
import logging
import time

from django.utils import timezone

from apps.billing import services as billing_services
from apps.billing.models import Invoice

from . import approvals
from .models import AgentRun, ApprovalRequest
from .payment_agent import draft_reminder, template_reminder
from .tracing import Trace

logger = logging.getLogger(__name__)

REMINDER_GAP = datetime.timedelta(days=7)


def needs_reminder(invoice):
    if invoice.status != Invoice.Status.OVERDUE:
        return False
    if invoice.last_reminder_at and timezone.now() - invoice.last_reminder_at < REMINDER_GAP:
        return False
    return not invoice.approval_requests.filter(
        kind=ApprovalRequest.Kind.REMINDER, status=ApprovalRequest.Status.PENDING
    ).exists()


def draft_overdue_reminder(invoice):
    """Have the payment agent draft a reminder and put it in the landlord's inbox.

    Returns the new ApprovalRequest, or None if no reminder is needed. Nothing is
    sent here: sending happens only when the landlord approves.
    """
    if not needs_reminder(invoice):
        return None

    trace = Trace()
    status, error = AgentRun.Status.OK, ""
    try:
        subject, body = draft_reminder(invoice, trace)
    except Exception as exc:
        logger.exception("Reminder draft failed, using the template")
        subject, body = template_reminder(invoice)
        status, error = AgentRun.Status.ERROR, str(exc)[:500]

    run = AgentRun.objects.create(
        organization=invoice.organization,
        trigger=AgentRun.Trigger.EVENT,
        route="payment",
        status=status,
        input_tokens=trace.input_tokens,
        output_tokens=trace.output_tokens,
        latency_ms=trace.elapsed_ms(),
        steps=trace.steps,
        error=error,
    )
    request, created = approvals.request_reminder(
        invoice=invoice, subject=subject, body=body, run=run
    )
    return request if created else None


def run_overdue_check(*, organization=None, today=None, pause=0):
    """Mark newly overdue invoices, then draft a reminder for each one that needs it."""
    billing_services.mark_overdue(today=today)
    invoices = Invoice.objects.filter(status=Invoice.Status.OVERDUE).select_related(
        "lease__tenant", "lease__unit", "organization"
    )
    if organization is not None:
        invoices = invoices.filter(organization=organization)
    drafted = []
    for invoice in invoices.order_by("due_date", "id"):
        request = draft_overdue_reminder(invoice)
        if request is not None:
            drafted.append(request)
            if pause:
                time.sleep(pause)
    return drafted
