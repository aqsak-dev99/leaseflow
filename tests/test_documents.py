import pytest
from django.core.files.base import ContentFile

from apps.accounts.models import User
from apps.documents import retrieval, services
from apps.documents.chunking import split_text
from apps.documents.models import Document, DocumentChunk
from apps.documents.sample_leases import build_lease_pdf
from apps.properties.models import Lease

LEASE_CONTEXT = {
    "landlord_name": "Alpha Rentals",
    "tenant_name": "Test Tenant",
    "unit_number": "A1",
    "property_name": "Gulberg Heights",
    "address": "12 Main Boulevard",
    "city": "Lahore",
    "start_date": "1 January 2026",
    "end_date": "31 December 2026",
    "rent": "65,000",
    "deposit": "130,000",
    "due_day": 5,
    "notice_days": 30,
    "grace_days": 5,
    "late_fee": "Rs. 1,500",
    "max_increase": 10,
    "repair_limit": "5,000",
    "pets": "Pets are not allowed in the unit.",
    "access_hours": 24,
}


def unit_vector():
    vector = [0.0] * 768
    vector[0] = 1.0
    return vector


def fake_vectors(texts):
    """Stand-in for the embedding API, so tests are fast, free and offline."""
    return [unit_vector() for _ in texts]


def lease_of(email):
    return Lease.objects.get(tenant=User.objects.get(email=email))


def add_chunk(lease, text, organization=None):
    organization = organization or lease.organization
    document = Document.objects.for_org(organization).filter(lease=lease).first()
    return DocumentChunk.objects.create(
        organization=organization,
        document=document,
        lease=lease,
        page_number=1,
        chunk_index=0,
        text=text,
        embedding=unit_vector(),
    )


def test_split_text_makes_several_bounded_chunks():
    chunks = split_text("word " * 400, size=500, overlap=100)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)


@pytest.mark.django_db
def test_process_document_stores_chunks_with_page_numbers(monkeypatch):
    monkeypatch.setattr(services, "embed_documents", fake_vectors)
    lease = lease_of("ali@alpha.test")
    document = Document(
        organization=lease.organization, lease=lease, kind="lease", title="Test lease"
    )
    document.file.save("test-lease.pdf", ContentFile(build_lease_pdf(LEASE_CONTEXT)))

    services.process_document(document.id)

    document.refresh_from_db()
    assert document.status == "ready"
    assert set(document.chunks.values_list("page_number", flat=True)) == {1, 2, 3}
    assert all(chunk.lease_id == lease.id for chunk in document.chunks.all())


@pytest.mark.django_db
def test_processing_twice_replaces_chunks_instead_of_duplicating(monkeypatch):
    monkeypatch.setattr(services, "embed_documents", fake_vectors)
    lease = lease_of("ali@alpha.test")
    document = Document(
        organization=lease.organization, lease=lease, kind="lease", title="Test lease"
    )
    document.file.save("test-lease.pdf", ContentFile(build_lease_pdf(LEASE_CONTEXT)))

    first = services.process_document(document.id)
    second = services.process_document(document.id)

    assert first == second == document.chunks.count()


@pytest.mark.django_db
def test_search_never_returns_another_tenants_or_organizations_chunks(monkeypatch):
    monkeypatch.setattr(retrieval, "embed_query", lambda text: unit_vector())
    ali_lease = lease_of("ali@alpha.test")
    mine = add_chunk(ali_lease, "Ali: notice period is 30 days.")
    policy = add_chunk(None, "Alpha quiet hours.", organization=ali_lease.organization)
    add_chunk(lease_of("sara@alpha.test"), "Sara: notice period is 60 days.")
    add_chunk(lease_of("omar@beta.test"), "Omar: notice period is 45 days.")
    beta = lease_of("omar@beta.test").organization
    add_chunk(None, "Beta quiet hours.", organization=beta)

    results = retrieval.search_chunks(
        organization=ali_lease.organization, lease=ali_lease, query="notice", limit=100
    )

    assert {chunk.id for chunk in results} == {mine.id, policy.id}
