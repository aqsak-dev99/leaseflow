"""Profile pages: people can change their own details and nobody else's."""

import pytest

from apps.accounts.models import Organization, User
from apps.properties.models import Lease

PASSWORD = "demo12345"
NEW_PASSWORD = "a-long-new-passphrase-42"


@pytest.mark.django_db
def test_the_profile_needs_a_login(client):
    assert client.get("/profile/").status_code == 302


@pytest.mark.django_db
def test_a_tenant_sees_their_own_tenancy_and_landlord_contact(client):
    lease = Lease.objects.get(tenant__email="ali@alpha.test")
    other = Lease.objects.get(tenant__email="sara@alpha.test")
    client.login(email="ali@alpha.test", password=PASSWORD)

    page = client.get("/profile/").content.decode()

    assert "Your tenancy" in page
    assert f"unit {lease.unit.unit_number}" in page
    assert "landlord@alpha.test" in page
    assert "sara@alpha.test" not in page
    assert f"unit {other.unit.unit_number}" not in page
    assert "Your business" not in page


@pytest.mark.django_db
def test_a_person_can_update_their_own_details(client):
    client.login(email="ali@alpha.test", password=PASSWORD)

    response = client.post(
        "/profile/",
        {"section": "details", "first_name": "Ali", "last_name": "Raza", "phone": "0300 1234567"},
        follow=True,
    )

    user = User.objects.get(email="ali@alpha.test")
    assert user.phone == "0300 1234567"
    assert "Your details were updated." in response.content.decode()


@pytest.mark.django_db
def test_extra_fields_in_the_request_are_ignored(client):
    """Nobody can make themselves a landlord, change email or move organization."""
    before = User.objects.get(email="ali@alpha.test")
    other_org = Organization.objects.exclude(pk=before.organization_id).first()
    client.login(email="ali@alpha.test", password=PASSWORD)

    client.post(
        "/profile/",
        {
            "section": "details",
            "first_name": "Ali",
            "last_name": "Raza",
            "phone": "",
            "role": "landlord",
            "email": "hacker@example.com",
            "organization": other_org.id,
            "is_staff": "on",
            "is_superuser": "on",
            "id": User.objects.get(email="sara@alpha.test").id,
        },
    )

    after = User.objects.get(pk=before.pk)
    assert after.email == "ali@alpha.test" and after.role == "tenant"
    assert after.organization_id == before.organization_id
    assert not after.is_staff and not after.is_superuser


@pytest.mark.django_db
def test_saving_a_profile_never_touches_another_user(client):
    sara_before = User.objects.filter(email="sara@alpha.test").values().get()
    client.login(email="ali@alpha.test", password=PASSWORD)

    client.post(
        "/profile/?user=sara@alpha.test",
        {"section": "details", "first_name": "Changed", "last_name": "Name", "phone": "999"},
    )

    assert User.objects.filter(email="sara@alpha.test").values().get() == sara_before
    assert User.objects.get(email="ali@alpha.test").first_name == "Changed"


@pytest.mark.django_db
def test_a_tenant_cannot_rename_the_business(client):
    org = User.objects.get(email="ali@alpha.test").organization
    name = org.name
    client.login(email="ali@alpha.test", password=PASSWORD)

    client.post("/profile/", {"section": "business", "name": "Hacked Rentals"})

    org.refresh_from_db()
    assert org.name == name


@pytest.mark.django_db
def test_a_landlord_can_rename_only_their_own_business(client):
    other = Organization.objects.exclude(users__email="landlord@alpha.test").first()
    other_name = other.name
    client.login(email="landlord@alpha.test", password=PASSWORD)

    page = client.get("/profile/").content.decode()
    assert "Your business" in page and "Your tenancy" not in page
    client.post("/profile/", {"section": "business", "name": "Alpha Homes", "id": other.id})

    other.refresh_from_db()
    assert User.objects.get(email="landlord@alpha.test").organization.name == "Alpha Homes"
    assert other.name == other_name


@pytest.mark.django_db
def test_changing_the_password_needs_the_current_one_and_keeps_you_signed_in(client):
    client.login(email="ali@alpha.test", password=PASSWORD)
    new = {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}

    client.post("/profile/", {"section": "password", "old_password": "wrong", **new})
    assert User.objects.get(email="ali@alpha.test").check_password(PASSWORD)

    client.post("/profile/", {"section": "password", "old_password": PASSWORD, **new})
    assert User.objects.get(email="ali@alpha.test").check_password(NEW_PASSWORD)
    assert client.get("/profile/").status_code == 200


@pytest.mark.django_db
def test_the_account_menu_links_to_the_profile(client):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert 'href="/profile/"' in client.get("/").content.decode()
