"""All maintenance rules live here. Views and agent tools both call these functions."""

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.properties.models import Lease, Unit

from .models import MaintenanceTicket, TicketUpdate


def _choice(value, choices, default):
    """Accept only a valid choice. Anything else falls back to the default."""
    value = (value or "").strip().lower()
    return value if value in choices.values else default


def _tenant_unit(user):
    lease = (
        Lease.objects.for_org(user.organization)
        .filter(tenant=user, status=Lease.Status.ACTIVE)
        .select_related("unit")
        .first()
    )
    if lease is None:
        raise ValidationError("You need an active lease to report a maintenance problem.")
    return lease.unit


def tickets_for(user):
    """Tickets this user may see: a tenant's own, or all in a landlord's organization."""
    tickets = MaintenanceTicket.objects.for_org(user.organization)
    if user.role == "tenant":
        tickets = tickets.filter(reported_by=user)
    return tickets.select_related("unit", "unit__property").order_by("-created_at")


def get_ticket(user, ticket_id):
    ticket = tickets_for(user).filter(pk=ticket_id).first()
    if ticket is None:
        raise PermissionDenied("Ticket not found.")
    return ticket


def find_open_ticket(user, category):
    """An unresolved ticket this tenant already has in the same category, if any."""
    category = _choice(category, MaintenanceTicket.Category, MaintenanceTicket.Category.OTHER)
    return (
        tickets_for(user)
        .filter(category=category)
        .exclude(status=MaintenanceTicket.Status.RESOLVED)
        .first()
    )


@transaction.atomic
def create_ticket(
    *, user, title, description, category="", priority="", unit_id=None, via_agent=False
):
    if user.role == "tenant":
        unit = _tenant_unit(user)
    else:
        unit = Unit.objects.for_org(user.organization).filter(pk=unit_id).first()
        if unit is None:
            raise ValidationError("Choose a unit in your organization.")
    title = (title or "").strip()[:200]
    description = (description or "").strip()
    if not title or not description:
        raise ValidationError("A ticket needs a title and a description.")

    ticket = MaintenanceTicket.objects.create(
        organization=user.organization,
        unit=unit,
        reported_by=user,
        title=title,
        description=description,
        category=_choice(category, MaintenanceTicket.Category, MaintenanceTicket.Category.OTHER),
        priority=_choice(priority, MaintenanceTicket.Priority, MaintenanceTicket.Priority.MEDIUM),
    )
    TicketUpdate.objects.create(
        organization=user.organization,
        ticket=ticket,
        author=user,
        via_agent=via_agent,
        note="Ticket created.",
        new_status=ticket.status,
    )
    return ticket


@transaction.atomic
def add_comment(*, user, ticket_id, note, via_agent=False):
    ticket = get_ticket(user, ticket_id)
    note = (note or "").strip()
    if not note:
        raise ValidationError("A comment cannot be empty.")
    return TicketUpdate.objects.create(
        organization=user.organization,
        ticket=ticket,
        author=user,
        via_agent=via_agent,
        note=note,
    )


@transaction.atomic
def update_status(*, user, ticket_id, new_status, note="", cost=None):
    """Only a landlord can change a ticket's status or record its cost."""
    if user.role != "landlord":
        raise PermissionDenied("Only the landlord can change a ticket's status.")
    ticket = get_ticket(user, ticket_id)
    if new_status not in MaintenanceTicket.Status.values:
        raise ValidationError("Unknown status.")
    old_status = ticket.status
    ticket.status = new_status
    if cost is not None:
        ticket.cost = cost
    ticket.save()
    TicketUpdate.objects.create(
        organization=user.organization,
        ticket=ticket,
        author=user,
        note=(note or "").strip(),
        old_status=old_status,
        new_status=new_status,
    )
    return ticket
