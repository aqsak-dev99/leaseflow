"""All billing rules live here. Views, jobs and agent tools call these functions."""

import calendar

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.properties.models import Lease

from .models import Invoice, Payment
from .providers import get_provider

UNPAID = (Invoice.Status.ISSUED, Invoice.Status.OVERDUE)


def month_start(day):
    return day.replace(day=1)


def month_end(day):
    return day.replace(day=calendar.monthrange(day.year, day.month)[1])


def due_date_for(lease, period):
    """The lease's due day in that month, moved back if the month is shorter."""
    return period.replace(day=min(lease.due_day, month_end(period).day))


def generate_invoices(*, period=None, organization=None):
    """Create one invoice per active lease for the month. Safe to run again."""
    period = month_start(period or timezone.localdate())
    leases = Lease.objects.filter(
        status=Lease.Status.ACTIVE,
        start_date__lte=month_end(period),
        end_date__gte=period,
    )
    if organization is not None:
        leases = leases.filter(organization=organization)
    created = 0
    for lease in leases:
        _, was_created = Invoice.objects.get_or_create(
            lease=lease,
            period=period,
            defaults={
                "organization": lease.organization,
                "amount": lease.rent_amount,
                "due_date": due_date_for(lease, period),
            },
        )
        created += int(was_created)
    return created


def mark_overdue(*, today=None):
    """Flag issued invoices whose due date has passed. Returns the newly overdue ones."""
    today = today or timezone.localdate()
    invoices = list(Invoice.objects.filter(status=Invoice.Status.ISSUED, due_date__lt=today))
    Invoice.objects.filter(pk__in=[invoice.pk for invoice in invoices]).update(
        status=Invoice.Status.OVERDUE
    )
    for invoice in invoices:
        invoice.status = Invoice.Status.OVERDUE
    return invoices


def invoices_for(user):
    """Invoices this user may see: a tenant's own, or all in a landlord's organization."""
    invoices = Invoice.objects.for_org(user.organization)
    if user.role == "tenant":
        invoices = invoices.filter(lease__tenant=user)
    return invoices.select_related("lease__unit__property", "lease__tenant").order_by(
        "-period", "lease__unit__unit_number"
    )


def get_invoice(user, invoice_id):
    invoice = invoices_for(user).filter(pk=invoice_id).first()
    if invoice is None:
        raise PermissionDenied("Invoice not found.")
    return invoice


def balance_for(user):
    """Total this user still owes (tenant) or is still owed (landlord)."""
    total = invoices_for(user).filter(status__in=UNPAID).aggregate(total=Sum("amount"))
    return total["total"] or 0


def _require_unpaid(invoice):
    if not invoice.is_unpaid:
        raise ValidationError(f"This invoice is already {invoice.get_status_display().lower()}.")


def settle(payment):
    """Mark a payment as succeeded and its invoice as paid."""
    payment.status = Payment.Status.SUCCEEDED
    payment.paid_at = payment.paid_at or timezone.now()
    payment.save(update_fields=["status", "paid_at"])
    invoice = payment.invoice
    if invoice.is_unpaid:
        invoice.status = Invoice.Status.PAID
        invoice.save(update_fields=["status"])


@transaction.atomic
def record_manual_payment(*, user, invoice_id, reference=""):
    """A landlord records cash or a bank transfer against an invoice."""
    if user.role != "landlord":
        raise PermissionDenied("Only the landlord can record a manual payment.")
    invoice = get_invoice(user, invoice_id)
    _require_unpaid(invoice)
    payment = get_provider("manual").start(invoice, reference=reference)
    settle(payment)
    return payment


@transaction.atomic
def start_gateway_payment(*, user, invoice_id):
    """A tenant starts paying one of their own invoices. Returns (payment, checkout URL)."""
    if user.role != "tenant":
        raise PermissionDenied("Only the tenant pays through the gateway.")
    invoice = get_invoice(user, invoice_id)
    _require_unpaid(invoice)
    provider = get_provider("fake_gateway")
    payment = provider.start(invoice)
    return payment, provider.checkout_url(payment)
