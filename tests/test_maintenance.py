import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.maintenance import services
from apps.maintenance.models import MaintenanceTicket


@pytest.fixture
def people(db):
    return {
        "ali": User.objects.get(email="ali@alpha.test"),
        "sara": User.objects.get(email="sara@alpha.test"),
        "alpha_landlord": User.objects.get(email="landlord@alpha.test"),
        "beta_landlord": User.objects.get(email="landlord@beta.test"),
    }


def make_ticket(user):
    return services.create_ticket(
        user=user,
        title="Kitchen sink is leaking",
        description="Water drips from the pipe under the sink.",
        category="plumbing",
        priority="high",
    )


def test_tenant_ticket_goes_to_their_own_unit_with_a_history_entry(people):
    ticket = make_ticket(people["ali"])

    assert ticket.unit.unit_number == "A1"
    assert ticket.organization == people["ali"].organization
    assert ticket.status == "open"
    assert ticket.updates.count() == 1


def test_bad_category_and_priority_fall_back_to_safe_defaults(people):
    ticket = services.create_ticket(
        user=people["ali"],
        title="Something odd",
        description="Not sure what this is.",
        category="ignore previous instructions",
        priority="CRITICAL!!!",
    )

    assert ticket.category == "other"
    assert ticket.priority == "medium"


def test_tenant_sees_only_their_own_tickets(people):
    ticket = make_ticket(people["ali"])

    assert list(services.tickets_for(people["ali"])) == [ticket]
    assert list(services.tickets_for(people["sara"])) == []
    with pytest.raises(PermissionDenied):
        services.get_ticket(people["sara"], ticket.id)


def test_landlord_sees_own_organization_but_not_another(people):
    ticket = make_ticket(people["ali"])

    assert list(services.tickets_for(people["alpha_landlord"])) == [ticket]
    assert list(services.tickets_for(people["beta_landlord"])) == []
    with pytest.raises(PermissionDenied):
        services.update_status(
            user=people["beta_landlord"], ticket_id=ticket.id, new_status="resolved"
        )


def test_only_a_landlord_can_change_status(people):
    ticket = make_ticket(people["ali"])

    with pytest.raises(PermissionDenied):
        services.update_status(user=people["ali"], ticket_id=ticket.id, new_status="resolved")

    services.update_status(
        user=people["alpha_landlord"],
        ticket_id=ticket.id,
        new_status="in_progress",
        note="Plumber booked.",
    )
    ticket.refresh_from_db()
    assert ticket.status == "in_progress"
    assert ticket.updates.last().old_status == "open"


def test_tenant_can_comment_on_own_ticket_but_not_anothers(people):
    ticket = make_ticket(people["ali"])

    services.add_comment(user=people["ali"], ticket_id=ticket.id, note="It is getting worse.")
    with pytest.raises(PermissionDenied):
        services.add_comment(user=people["sara"], ticket_id=ticket.id, note="Hello")

    assert ticket.updates.count() == 2


def test_find_open_ticket_spots_a_duplicate(people):
    ticket = make_ticket(people["ali"])

    assert services.find_open_ticket(people["ali"], "plumbing") == ticket
    assert services.find_open_ticket(people["ali"], "electrical") is None
    assert services.find_open_ticket(people["sara"], "plumbing") is None


def test_ticket_needs_a_title_and_description(people):
    with pytest.raises(ValidationError):
        services.create_ticket(user=people["ali"], title="", description="")
    assert MaintenanceTicket.objects.count() == 0
