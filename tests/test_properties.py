import datetime

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError

from apps.accounts.models import Organization
from apps.properties.models import Lease, Property, Unit

User = get_user_model()


def make_unit(org, name):
    prop = Property.objects.create(organization=org, name=name, address="1 Main St", city="Lahore")
    return Unit.objects.create(
        organization=org, property=prop, unit_number="A1", monthly_rent=50000
    )


def make_lease(org, unit, email):
    tenant = User.objects.create_user(
        email=email, password="pass12345", organization=org, role="tenant"
    )
    return Lease.objects.create(
        organization=org,
        unit=unit,
        tenant=tenant,
        start_date=datetime.date(2026, 1, 1),
        end_date=datetime.date(2026, 12, 31),
        rent_amount=50000,
    )


@pytest.mark.django_db
def test_for_org_returns_only_that_organizations_rows():
    org_a = Organization.objects.create(name="Alpha Rentals", slug="alpha")
    org_b = Organization.objects.create(name="Beta Homes", slug="beta")
    make_unit(org_a, "Alpha House")
    make_unit(org_b, "Beta House")

    names = [p.name for p in Property.objects.for_org(org_a)]

    assert names == ["Alpha House"]


@pytest.mark.django_db
def test_unit_cannot_have_two_active_leases():
    org = Organization.objects.create(name="Alpha Rentals", slug="alpha")
    unit = make_unit(org, "Alpha House")
    make_lease(org, unit, "first@example.com")

    with pytest.raises(IntegrityError):
        make_lease(org, unit, "second@example.com")
