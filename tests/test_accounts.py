import pytest
from django.core.management import call_command

from apps.accounts.models import Organization, User
from apps.properties.models import Lease


@pytest.mark.django_db
def test_signup_creates_organization_and_landlord(client):
    response = client.post(
        "/signup/",
        {
            "organization_name": "Gamma Estates",
            "email": "owner@gamma.test",
            "password": "Tr1cky-horse-77",
        },
    )

    assert response.status_code == 302
    user = User.objects.get(email="owner@gamma.test")
    assert user.role == "landlord"
    assert user.organization.name == "Gamma Estates"


@pytest.mark.django_db
def test_seed_demo_is_safe_to_run_again():
    before = (Organization.objects.count(), User.objects.count(), Lease.objects.count())

    call_command("seed_demo")

    after = (Organization.objects.count(), User.objects.count(), Lease.objects.count())
    assert before == after == (2, 6, 4)
