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


def test_home_page_sends_visitors_to_the_login_page(client):
    response = client.get("/")

    assert response.status_code == 302
    assert response.url == "/login/"
