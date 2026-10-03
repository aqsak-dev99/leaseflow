from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.documents.retrieval import search_chunks
from apps.properties.models import Lease


class Command(BaseCommand):
    help = "Show which lease chunks a tenant's question retrieves."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("question")

    def handle(self, *args, **options):
        tenant = User.objects.filter(email=options["email"]).first()
        if tenant is None:
            raise CommandError("No user with that email.")
        lease = (
            Lease.objects.for_org(tenant.organization)
            .filter(tenant=tenant, status=Lease.Status.ACTIVE)
            .first()
        )
        if lease is None:
            raise CommandError("That user has no active lease.")
        chunks = search_chunks(
            organization=tenant.organization, lease=lease, query=options["question"], limit=3
        )
        for chunk in chunks:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[{chunk.document.title}, page {chunk.page_number}] "
                    f"distance {chunk.distance:.3f}"
                )
            )
            self.stdout.write(chunk.text[:350])
