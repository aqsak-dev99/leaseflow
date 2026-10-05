"""The approval gate. Agents can only create requests; a landlord decides them."""

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import Invoice

from .models import ApprovalRequest


def _create(*, invoice, kind, subject, body, requested_by=None, run=None):
    """Create a pending request, or return the one already waiting. Returns (request, created)."""
    if not invoice.is_unpaid:
        raise ValidationError("That invoice is not waiting for payment.")
    existing = ApprovalRequest.objects.filter(
        invoice=invoice, kind=kind, status=ApprovalRequest.Status.PENDING
    ).first()
    if existing is not None:
        return existing, False
    try:
        with transaction.atomic():
            request = ApprovalRequest.objects.create(
                organization=invoice.organization,
                invoice=invoice,
                kind=kind,
                subject=subject[:200],
                body=body,
                requested_by=requested_by,
                run=run,
            )
    except IntegrityError:
        # Two requests raced. The database kept one, so return that.
        request = ApprovalRequest.objects.get(
            invoice=invoice, kind=kind, status=ApprovalRequest.Status.PENDING
        )
        return request, False
    return request, True


def request_reminder(*, invoice, subject, body, run=None):
    return _create(
        invoice=invoice, kind=ApprovalRequest.Kind.REMINDER, subject=subject, body=body, run=run
    )


def request_waiver(*, user, invoice, reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A waiver request needs a reason.")
    unit = invoice.lease.unit.unit_number
    subject = f"Waiver request: rent for {invoice.period:%B %Y}, unit {unit}"
    return _create(
        invoice=invoice,
        kind=ApprovalRequest.Kind.WAIVER,
        subject=subject,
        body=reason,
        requested_by=user,
    )


def requests_for(user):
    if user.role != "landlord":
        raise PermissionDenied("Only the landlord can see approval requests.")
    return ApprovalRequest.objects.for_org(user.organization).select_related(
        "invoice__lease__unit", "invoice__lease__tenant", "requested_by"
    )


def _pending(user, request_id):
    request = requests_for(user).select_for_update(of=("self",)).filter(pk=request_id).first()
    if request is None:
        raise PermissionDenied("Request not found.")
    if request.status != ApprovalRequest.Status.PENDING:
        raise ValidationError("This request has already been decided.")
    return request


def _close(request, user, status, note=""):
    request.status = status
    request.decided_by = user
    request.decided_at = timezone.now()
    request.decision_note = note
    request.save()


@transaction.atomic
def approve(*, user, request_id, subject=None, body=None):
    """Approve a request and carry it out. The landlord may edit a reminder first."""
    request = _pending(user, request_id)
    invoice = request.invoice
    if request.kind == ApprovalRequest.Kind.REMINDER:
        if subject is not None and subject.strip():
            request.subject = subject.strip()[:200]
        if body is not None and body.strip():
            request.body = body.strip()
        send_mail(
            request.subject,
            request.body,
            settings.DEFAULT_FROM_EMAIL,
            [invoice.lease.tenant.email],
        )
        invoice.last_reminder_at = timezone.now()
        invoice.save(update_fields=["last_reminder_at"])
    elif request.kind == ApprovalRequest.Kind.WAIVER:
        if not invoice.is_unpaid:
            raise ValidationError("That invoice is no longer waiting for payment.")
        invoice.status = Invoice.Status.WAIVED
        invoice.save(update_fields=["status"])
    _close(request, user, ApprovalRequest.Status.APPROVED)
    return request


@transaction.atomic
def reject(*, user, request_id, note=""):
    request = _pending(user, request_id)
    _close(request, user, ApprovalRequest.Status.REJECTED, (note or "").strip())
    return request
