import datetime
import time

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Organization, User
from apps.documents.models import Document
from apps.documents.sample_leases import build_lease_pdf, build_policy_pdf
from apps.documents.services import process_document
from apps.properties.models import Lease, Property, Unit

PASSWORD = "demo12345"
START = datetime.date(2026, 1, 1)
END = datetime.date(2026, 12, 31)

DEMO = [
    {
        "name": "Alpha Rentals",
        "slug": "alpha-rentals",
        "landlord": "landlord@alpha.test",
        "property": ("Gulberg Heights", "12 Main Boulevard, Gulberg", "Lahore"),
        "policy": {
            "quiet_start": "10 pm",
            "quiet_end": "7 am",
            "parking": "one",
            "waste_days": "on Monday and Thursday mornings",
            "generator": "The building generator covers lifts and corridor lights only.",
        },
        "tenants": [
            {
                "email": "ali@alpha.test",
                "name": ("Ali", "Raza"),
                "unit": "A1",
                "rent": 65000,
                "terms": {
                    "notice_days": 30,
                    "grace_days": 5,
                    "late_fee": "Rs. 1,500",
                    "max_increase": 10,
                    "repair_limit": "5,000",
                    "pets": "Pets are not allowed in the unit.",
                    "access_hours": 24,
                },
            },
            {
                "email": "sara@alpha.test",
                "name": ("Sara", "Malik"),
                "unit": "A2",
                "rent": 72000,
                "terms": {
                    "notice_days": 60,
                    "grace_days": 7,
                    "late_fee": "Rs. 2,000",
                    "max_increase": 8,
                    "repair_limit": "3,000",
                    "pets": "One cat is allowed with the written consent of the Landlord.",
                    "access_hours": 48,
                },
            },
        ],
        "vacant_unit": ("A3", 60000),
    },
    {
        "name": "Beta Homes",
        "slug": "beta-homes",
        "landlord": "landlord@beta.test",
        "property": ("Clifton View", "8 Sea Road, Clifton", "Karachi"),
        "policy": {
            "quiet_start": "11 pm",
            "quiet_end": "6 am",
            "parking": "two",
            "waste_days": "every day except Sunday",
            "generator": "The building generator covers all units during power cuts.",
        },
        "tenants": [
            {
                "email": "omar@beta.test",
                "name": ("Omar", "Sheikh"),
                "unit": "B1",
                "rent": 90000,
                "terms": {
                    "notice_days": 45,
                    "grace_days": 3,
                    "late_fee": "2 percent of the monthly rent",
                    "max_increase": 12,
                    "repair_limit": "10,000",
                    "pets": "Pets are not allowed in the unit.",
                    "access_hours": 24,
                },
            },
            {
                "email": "hina@beta.test",
                "name": ("Hina", "Qureshi"),
                "unit": "B2",
                "rent": 85000,
                "terms": {
                    "notice_days": 90,
                    "grace_days": 10,
                    "late_fee": "Rs. 2,500",
                    "max_increase": 5,
                    "repair_limit": "7,500",
                    "pets": "Small pets are allowed. The Tenant pays for any damage they cause.",
                    "access_hours": 72,
                },
            },
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


def save_document(organization, lease, kind, title, filename, pdf_bytes):
    document = Document(organization=organization, lease=lease, kind=kind, title=title)
    document.file.save(filename, ContentFile(pdf_bytes), save=False)
    document.save()
    return document


class Command(BaseCommand):
    help = "Create two demo organizations with properties, tenants, leases and documents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--embed",
            action="store_true",
            help="Also process the documents (calls the embedding API).",
        )

    def handle(self, *args, **options):
        with transaction.atomic():
            for data in DEMO:
                self.create_organization(data)
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write(f"All demo accounts use the password: {PASSWORD}")

        if options["embed"]:
            pending = Document.objects.exclude(status=Document.Status.READY)
            for document in pending:
                count = process_document(document.id)
                self.stdout.write(f"Processed {document.title}: {count} chunks")
                time.sleep(1)

    def create_organization(self, data):
        org, _ = Organization.objects.get_or_create(
            slug=data["slug"], defaults={"name": data["name"]}
        )
        get_or_create_user(data["landlord"], org, User.Role.LANDLORD)

        name, address, city = data["property"]
        prop, _ = Property.objects.get_or_create(
            organization=org, name=name, defaults={"address": address, "city": city}
        )

        for item in data["tenants"]:
            first, last = item["name"]
            rent = item["rent"]
            tenant = get_or_create_user(item["email"], org, User.Role.TENANT, first, last)
            unit, _ = Unit.objects.get_or_create(
                organization=org,
                property=prop,
                unit_number=item["unit"],
                defaults={"monthly_rent": rent, "status": Unit.Status.OCCUPIED},
            )
            lease, _ = Lease.objects.get_or_create(
                organization=org,
                unit=unit,
                tenant=tenant,
                defaults={
                    "start_date": START,
                    "end_date": END,
                    "rent_amount": rent,
                    "deposit": rent * 2,
                    "due_day": 5,
                },
            )
            if not lease.documents.exists():
                context = {
                    "landlord_name": org.name,
                    "tenant_name": f"{first} {last}",
                    "unit_number": item["unit"],
                    "property_name": name,
                    "address": address,
                    "city": city,
                    "start_date": "1 January 2026",
                    "end_date": "31 December 2026",
                    "rent": f"{rent:,}",
                    "deposit": f"{rent * 2:,}",
                    "due_day": 5,
                    **item["terms"],
                }
                save_document(
                    org,
                    lease,
                    Document.Kind.LEASE,
                    f"Lease agreement, unit {item['unit']}",
                    f"lease-{org.slug}-{item['unit'].lower()}.pdf",
                    build_lease_pdf(context),
                )

        if not Document.objects.for_org(org).filter(kind=Document.Kind.POLICY).exists():
            save_document(
                org,
                None,
                Document.Kind.POLICY,
                f"Building rules, {name}",
                f"policy-{org.slug}.pdf",
                build_policy_pdf({"property_name": name, **data["policy"]}),
            )

        number, rent = data["vacant_unit"]
        Unit.objects.get_or_create(
            organization=org,
            property=prop,
            unit_number=number,
            defaults={"monthly_rent": rent},
        )
