import pytest
from django.core.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.dashboard.search import search
from apps.maintenance import services as maintenance_services

PASSWORD = "demo12345"


@pytest.fixture
def landlord(db):
    return User.objects.get(email="landlord@alpha.test")


@pytest.fixture
def ticket(db):
    return maintenance_services.create_ticket(
        user=User.objects.get(email="ali@alpha.test"),
        title="Kitchen sink leaking",
        description="Water under the sink",
    )


def test_search_finds_tenants_units_tickets_and_invoices(landlord, ticket):
    by_name = search(landlord, "raza")
    by_unit = search(landlord, "A2")
    by_word = search(landlord, "sink")
    by_number = search(landlord, f"#{ticket.id}")

    assert [tenant.email for tenant in by_name["tenants"]] == ["ali@alpha.test"]
    assert {invoice.lease.tenant.email for invoice in by_name["invoices"]} == {"ali@alpha.test"}
    assert [unit.unit_number for unit in by_unit["units"]] == ["A2"]
    assert by_word["tickets"] == [ticket]
    assert by_number["tickets"] == [ticket]


def test_search_never_returns_another_organizations_data(ticket):
    other = User.objects.get(email="landlord@beta.test")

    for query in ["ali", "sink", "A1", "Gulberg", "alpha.test"]:
        assert not any(search(other, query).values()), query


def test_search_ignores_very_short_queries_and_is_for_landlords_only(landlord):
    assert not any(search(landlord, "a").values())
    assert not any(search(landlord, "   ").values())
    with pytest.raises(PermissionDenied):
        search(User.objects.get(email="ali@alpha.test"), "sara")


def test_search_pages_show_results_and_are_closed_to_tenants(client, ticket):
    client.login(email="landlord@alpha.test", password=PASSWORD)
    page = client.get("/search/?q=sink").content.decode()
    suggest = client.get("/search/suggest/?q=sink").content.decode()
    nothing = client.get("/search/?q=zzzz").content.decode()
    client.logout()

    client.login(email="ali@alpha.test", password=PASSWORD)

    assert "Kitchen sink leaking" in page
    assert "Kitchen sink leaking" in suggest and "See all results" in suggest
    assert "Nothing matches" in nothing
    assert client.get("/search/?q=sara").status_code == 403
    assert client.get("/search/suggest/?q=sara").status_code == 403
    assert 'role="search"' not in client.get("/").content.decode()


def test_the_other_landlord_sees_nothing_through_the_search_pages(client, ticket):
    client.login(email="landlord@beta.test", password=PASSWORD)

    assert "Kitchen sink leaking" not in client.get("/search/?q=sink").content.decode()
    assert "Ali" not in client.get("/search/suggest/?q=ali").content.decode()
