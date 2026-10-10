"""A landlord sets up their own properties and units, so a new sign-up is not a dead end."""

import pytest

from apps.accounts.models import User
from apps.properties.models import Property, Unit

PASSWORD = "demo12345"
PROPERTY = {"name": "Model Town House", "address": "5 Park Road", "city": "Lahore"}
UNIT = {"unit_number": "G1", "bedrooms": "2", "monthly_rent": "48000"}


def alpha():
    return User.objects.get(email="landlord@alpha.test").organization


@pytest.mark.django_db
def test_a_landlord_adds_a_property_then_a_unit_and_can_invite(client):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    response = client.post("/properties/add/", PROPERTY)
    home = Property.objects.get(name="Model Town House")
    assert home.organization == alpha()
    assert response.url == f"/properties/{home.id}/units/add/"

    client.post(f"/properties/{home.id}/units/add/", UNIT)
    unit = Unit.objects.get(property=home)
    page = client.get("/properties/").content.decode()

    assert unit.organization == alpha() and unit.status == "vacant" and unit.monthly_rent == 48000
    assert "Model Town House" in page
    assert f"/units/{unit.id}/invite/" in page


@pytest.mark.django_db
def test_a_brand_new_landlord_starts_with_a_way_forward(client):
    client.post(
        "/signup/",
        {
            "organization_name": "Fresh Homes",
            "email": "new@fresh.test",
            "password": "a-long-pass-42",
        },
    )

    page = client.get("/properties/").content.decode()

    assert "No properties yet" in page and "/properties/add/" in page


@pytest.mark.django_db
def test_tenants_cannot_add_properties_or_units(client):
    home = Property.objects.for_org(alpha()).first()
    client.login(email="ali@alpha.test", password=PASSWORD)

    assert client.post("/properties/add/", PROPERTY).status_code == 403
    assert client.post(f"/properties/{home.id}/units/add/", UNIT).status_code == 403
    assert not Property.objects.filter(name="Model Town House").exists()


@pytest.mark.django_db
def test_a_landlord_cannot_add_a_unit_to_another_organizations_property(client):
    other = Property.objects.exclude(organization=alpha()).first()
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert client.post(f"/properties/{other.id}/units/add/", UNIT).status_code == 404
    assert not Unit.objects.filter(property=other, unit_number="G1").exists()


@pytest.mark.django_db
def test_the_organization_and_status_cannot_be_set_from_the_form(client):
    other_org = Property.objects.exclude(organization=alpha()).first().organization
    home = Property.objects.for_org(alpha()).first()
    client.login(email="landlord@alpha.test", password=PASSWORD)

    client.post("/properties/add/", {**PROPERTY, "organization": other_org.id})
    client.post(
        f"/properties/{home.id}/units/add/",
        {**UNIT, "status": "occupied", "organization": other_org.id, "property": 999},
    )

    assert Property.objects.get(name="Model Town House").organization == alpha()
    unit = Unit.objects.get(unit_number="G1")
    assert unit.property == home and unit.organization == alpha() and unit.status == "vacant"


@pytest.mark.django_db
def test_duplicate_unit_numbers_and_bad_rent_are_refused(client):
    home = Property.objects.for_org(alpha()).first()
    taken = home.units.first().unit_number
    client.login(email="landlord@alpha.test", password=PASSWORD)
    before = home.units.count()

    duplicate = client.post(
        f"/properties/{home.id}/units/add/", {**UNIT, "unit_number": taken.lower()}
    )
    free = client.post(f"/properties/{home.id}/units/add/", {**UNIT, "monthly_rent": "0"})

    assert "already has a unit" in duplicate.content.decode()
    assert free.status_code == 200
    assert home.units.count() == before


@pytest.mark.django_db
def test_the_password_card_is_closed_until_opened_or_wrong(client):
    client.login(email="ali@alpha.test", password=PASSWORD)

    closed = client.get("/profile/").content.decode()
    wrong = client.post(
        "/profile/",
        {"section": "password", "old_password": "nope", "new_password1": "x", "new_password2": "y"},
    ).content.decode()

    assert '<details class="card section accordion">' in closed
    assert '<details class="card section accordion" open>' in wrong
