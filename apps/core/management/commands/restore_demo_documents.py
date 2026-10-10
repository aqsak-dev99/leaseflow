"""Put the demo PDF files back when the host's disk has been wiped.

Free hosting has no permanent disk: uploaded files vanish on every deploy.
The text of each document is safe in the database, but the PDF shown beside a
citation is a file. The demo PDFs are generated from fixed data, so they can
simply be rebuilt. Documents that are not part of the demo are left alone.
"""

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from apps.documents.models import Document
from apps.documents.sample_leases import build_lease_pdf, build_policy_pdf

from .seed_demo import DEMO, lease_context


class Command(BaseCommand):
    help = "Rebuild any demo lease or policy PDF whose file is missing."

    def handle(self, *args, **options):
        restored = 0
        for data in DEMO:
            documents = Document.objects.filter(organization__slug=data["slug"])
            by_email = {item["email"]: item for item in data["tenants"]}
            for document in documents.select_related("lease__tenant"):
                if document.file and document.file.storage.exists(document.file.name):
                    continue
                if document.kind == Document.Kind.POLICY:
                    name = data["property"][0]
                    pdf = build_policy_pdf({"property_name": name, **data["policy"]})
                elif document.lease and document.lease.tenant.email in by_email:
                    item = by_email[document.lease.tenant.email]
                    pdf = build_lease_pdf(lease_context(data, item))
                else:
                    continue
                filename = (document.file.name or f"document-{document.id}.pdf").split("/")[-1]
                document.file.save(filename, ContentFile(pdf), save=True)
                restored += 1
        self.stdout.write(f"Restored {restored} demo document file(s).")
