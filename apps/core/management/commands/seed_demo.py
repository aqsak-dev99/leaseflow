import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Organization, User
from apps.properties.models import Lease, Property, Unit

PASSWORD = "demo12345"

DEMO = [
    {
        "name": "Alpha Rentals",
        "slug": "alpha-rentals",
        "landlord": "landlord@alpha.test",
        "property": ("Gulberg Heights", "12 Main Boulevard, Gulberg", "Lahore"),
        "tenants": [
            ("ali@alpha.test", "Ali", "Raza", "A1", 65000),
            ("sara@alpha.test", "Sara", "Malik", "A2", 72000),
        ],
        "vacant_unit": ("A3", 60000),
    },
    {
        "name": "Beta Homes",
        "slug": "beta-homes",
        "landlord": "landlord@beta.test",
        "property": ("Clifton View", "8 Sea Road, Clifton", "Karachi"),
        "tenants": [
            ("omar@beta.test", "Omar", "Sheikh", "B1", 90000),
            ("hina@beta.test", "Hina", "Qureshi", "B2", 85000),
        ],
        "vacant_unit": ("B3", 80000),
    },
]


def get_or_create_user(email, organization, role, first_name="", last_name=""):
    user = User.objects.filter(email=email).first()
    if user is None:
        user = User.objects.create_user(
            email=email,
            password=PASSWORD,
            organization=organization,
            role=role,
            first_name=first_name,
            last_name=last_name,
        )
    return user


class Command(BaseCommand):
    help = "Create two demo organizations with properties, tenants and leases."

    @transaction.atomic
    def handle(self, *args, **options):
        for data in DEMO:
            org, _ = Organization.objects.get_or_create(
                slug=data["slug"], defaults={"name": data["name"]}
            )
            get_or_create_user(data["landlord"], org, User.Role.LANDLORD)

            name, address, city = data["property"]
            prop, _ = Property.objects.get_or_create(
                organization=org, name=name, defaults={"address": address, "city": city}
            )

            for email, first, last, number, rent in data["tenants"]:
                tenant = get_or_create_user(email, org, User.Role.TENANT, first, last)
                unit, _ = Unit.objects.get_or_create(
                    organization=org,
                    property=prop,
                    unit_number=number,
                    defaults={"monthly_rent": rent, "status": Unit.Status.OCCUPIED},
                )
                Lease.objects.get_or_create(
                    organization=org,
                    unit=unit,
                    tenant=tenant,
                    defaults={
                        "start_date": datetime.date(2026, 1, 1),
                        "end_date": datetime.date(2026, 12, 31),
                        "rent_amount": rent,
                        "deposit": rent * 2,
                        "due_day": 5,
                    },
                )

            number, rent = data["vacant_unit"]
            Unit.objects.get_or_create(
                organization=org,
                property=prop,
                unit_number=number,
                defaults={"monthly_rent": rent},
            )

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"All demo accounts use the password: {PASSWORD}")
