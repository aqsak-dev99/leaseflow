import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.documents import retrieval, services
from apps.documents.chunking import split_text
from apps.documents.models import Document, DocumentChunk
from apps.properties.models import Lease


def fake_vectors(texts):
    """Stand-in for the embedding API, so tests are fast, free and offline."""
    vector = [0.0] * 768
    vector[0] = 1.0
    return [vector for _ in texts]


def test_split_text_makes_several_bounded_chunks():
    chunks = split_text("word " * 400, size=500, overlap=100)

    assert len(chunks) > 1
    assert all(len(chunk) <= 500 for chunk in chunks)


@pytest.mark.django_db
def test_process_document_stores_chunks_with_page_numbers(monkeypatch):
    call_command("seed_demo")
    monkeypatch.setattr(services, "embed_documents", fake_vectors)
    document = Document.objects.filter(kind="lease").first()

    services.process_document(document.id)

    document.refresh_from_db()
    assert document.status == "ready"
    assert set(document.chunks.values_list("page_number", flat=True)) == {1, 2, 3}
    assert all(chunk.lease_id == document.lease_id for chunk in document.chunks.all())


@pytest.mark.django_db
def test_search_never_returns_another_tenants_or_organizations_chunks(monkeypatch):
    call_command("seed_demo")
    monkeypatch.setattr(services, "embed_documents", fake_vectors)
    for document in Document.objects.all():
        services.process_document(document.id)
    monkeypatch.setattr(retrieval, "embed_query", lambda text: fake_vectors([text])[0])
    ali = User.objects.get(email="ali@alpha.test")
    lease = Lease.objects.get(tenant=ali)

    results = retrieval.search_chunks(
        organization=ali.organization, lease=lease, query="notice period", limit=100
    )

    assert results
    for chunk in results:
        assert chunk.organization_id == ali.organization_id
        assert chunk.lease_id in (lease.id, None)
    # Prove there really was other data that could have leaked.
    other_org = DocumentChunk.objects.exclude(organization=ali.organization)
    other_tenant = DocumentChunk.objects.filter(organization=ali.organization).exclude(
        lease=lease
    ).exclude(lease=None)
    assert other_org.exists()
    assert other_tenant.exists()
