import pytest
from django.contrib.auth import get_user_model

from apps.accounts.models import Organization


@pytest.mark.django_db
def test_user_belongs_to_organization():
    org = Organization.objects.create(name="Demo Rentals", slug="demo-rentals")
    user = get_user_model().objects.create_user(
        email="landlord@example.com",
        password="pass12345",
        organization=org,
    )
    assert user.organization == org
    assert user.role == "landlord"


def test_home_page_loads(client):
    assert client.get("/").status_code == 200
