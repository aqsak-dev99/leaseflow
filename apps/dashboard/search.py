"""Landlord search across tenants, units, tickets and invoices.

Every query starts from `for_org(user.organization)` or the user's own
organization, so a landlord can only ever find their own data.
"""

from django.core.exceptions import PermissionDenied
from django.db.models import Q

from apps.accounts.models import User
from apps.billing.models import Invoice
from apps.maintenance.models import MaintenanceTicket
from apps.properties.models import Unit

MIN_LENGTH = 2


def search(user, query, limit=5):
    """Return {"tenants": [...], "units": [...], "tickets": [...], "invoices": [...]}."""
    if user.role != "landlord":
        raise PermissionDenied("Only the landlord can search.")
    query = (query or "").strip()
    empty = {"tenants": [], "units": [], "tickets": [], "invoices": []}
    if len(query) < MIN_LENGTH:
        return empty
    org = user.organization

    person = (
        Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(email__icontains=query)
    )
    tenants = User.objects.filter(person, organization=org, role=User.Role.TENANT)

    units = (
        Unit.objects.for_org(org)
        .filter(Q(unit_number__icontains=query) | Q(property__name__icontains=query))
        .select_related("property")
    )

    ticket_match = Q(title__icontains=query) | Q(description__icontains=query)
    if query.lstrip("#").isdigit():
        ticket_match |= Q(pk=int(query.lstrip("#")))
    tickets = MaintenanceTicket.objects.for_org(org).filter(ticket_match).select_related("unit")

    invoices = (
        Invoice.objects.for_org(org)
        .filter(
            Q(lease__tenant__first_name__icontains=query)
            | Q(lease__tenant__last_name__icontains=query)
            | Q(lease__tenant__email__icontains=query)
            | Q(lease__unit__unit_number__iexact=query)
        )
        .select_related("lease__tenant", "lease__unit")
        .order_by("-period")
    )

    return {
        "tenants": list(tenants.order_by("first_name", "email")[:limit]),
        "units": list(units.order_by("unit_number")[:limit]),
        "tickets": list(tickets.order_by("-id")[:limit]),
        "invoices": list(invoices[:limit]),
    }
