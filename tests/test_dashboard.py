import pytest

from apps.accounts.models import User
from apps.agents.models import AgentRun
from apps.agents.text import text_of
from apps.maintenance import services as maintenance_services

PASSWORD = "demo12345"


@pytest.fixture
def ticket(db):
    ali = User.objects.get(email="ali@alpha.test")
    return maintenance_services.create_ticket(
        user=ali,
        title="Kitchen sink leaking",
        description="Water drips from the pipe under the sink.",
        category="plumbing",
    )


def test_landlord_dashboard_shows_counts_and_the_new_ticket(client, ticket):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    html = client.get("/").content.decode()

    assert "Occupied units" in html
    assert "Kitchen sink leaking" in html


def test_tenant_home_shows_only_their_own_tickets(client, ticket):
    client.login(email="sara@alpha.test", password=PASSWORD)
    assert "Kitchen sink leaking" not in client.get("/").content.decode()
    client.logout()

    client.login(email="ali@alpha.test", password=PASSWORD)
    assert "Kitchen sink leaking" in client.get("/").content.decode()


def test_landlord_pages_are_closed_to_tenants(client, ticket):
    client.login(email="ali@alpha.test", password=PASSWORD)

    for url in ["/properties/", "/tickets/", "/activity/"]:
        assert client.get(url).status_code == 403


def test_another_organizations_landlord_cannot_open_the_ticket(client, ticket):
    client.login(email="landlord@beta.test", password=PASSWORD)

    assert client.get(f"/tickets/{ticket.id}/").status_code == 404
    assert "Kitchen sink leaking" not in client.get("/tickets/").content.decode()


def test_another_tenant_cannot_open_the_ticket(client, ticket):
    client.login(email="sara@alpha.test", password=PASSWORD)

    assert client.get(f"/tickets/{ticket.id}/").status_code == 404


def test_landlord_can_update_status_and_cost(client, ticket):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    response = client.post(
        f"/tickets/{ticket.id}/",
        {"status": "resolved", "note": "Pipe replaced.", "cost": "2500"},
    )

    ticket.refresh_from_db()
    assert response.status_code == 302
    assert ticket.status == "resolved"
    assert ticket.cost == 2500
    assert ticket.updates.count() == 2


def test_tenant_cannot_update_status_by_posting_to_the_page(client, ticket):
    client.login(email="ali@alpha.test", password=PASSWORD)

    response = client.post(f"/tickets/{ticket.id}/", {"status": "resolved"})

    ticket.refresh_from_db()
    assert response.status_code == 403
    assert ticket.status == "open"


def test_properties_page_lists_units_and_tenants_of_own_organization_only(client, db):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    html = client.get("/properties/").content.decode()

    assert "Gulberg Heights" in html
    assert "Ali Raza" in html
    assert "Clifton View" not in html


def test_activity_and_trace_are_scoped_to_the_organization(client, db):
    alpha = User.objects.get(email="landlord@alpha.test").organization
    beta = User.objects.get(email="landlord@beta.test").organization
    steps = [{"type": "model", "name": "supervisor", "ms": 12, "detail": {"route": "lease"}}]
    mine = AgentRun.objects.create(organization=alpha, route="lease", steps=steps)
    theirs = AgentRun.objects.create(organization=beta, route="maintenance")
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert f"#{mine.id}" in client.get("/activity/").content.decode()
    assert f"#{theirs.id}" not in client.get("/activity/").content.decode()
    assert "supervisor" in client.get(f"/runs/{mine.id}/").content.decode()
    assert client.get(f"/runs/{theirs.id}/").status_code == 404


def test_reply_text_has_markdown_bold_removed():
    assert text_of("**Ticket #1** created") == "Ticket #1 created"
