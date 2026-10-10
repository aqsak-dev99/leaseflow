"""The lease page viewer that citations link to, and who is allowed to open it."""

import pytest
from django.core.files.base import ContentFile
from fpdf import FPDF

from apps.accounts.models import User
from apps.documents.models import Document, DocumentChunk
from apps.documents.viewer import closest_sentence, locate
from apps.properties.models import Lease

PASSWORD = "demo12345"
VECTOR = [1.0] + [0.0] * 767


PAGES = [
    "RESIDENTIAL LEASE AGREEMENT. 4. Rent. Rent is due on day 5 of each month.",
    "7. Notice period. Either party may end this lease by giving 30 days written notice.",
    "12. Pets. Pets are not allowed in the unit.",
]


def lease_document(email):
    """The tenant's lease, with a real three-page PDF saved as its file."""
    lease = Lease.objects.get(tenant=User.objects.get(email=email))
    document = Document.objects.get(lease=lease, kind=Document.Kind.LEASE)
    pdf = FPDF()
    pdf.set_font("Helvetica", size=12)
    for text in PAGES:
        pdf.add_page()
        pdf.multi_cell(0, 8, text)
    document.file.save("lease.pdf", ContentFile(bytes(pdf.output())), save=True)
    return document


def chunk_on(document, page_number, text):
    return DocumentChunk.objects.create(
        organization=document.organization,
        document=document,
        lease=document.lease,
        page_number=page_number,
        chunk_index=999,
        text=text,
        embedding=VECTOR,
    )


def test_locate_finds_a_passage_across_line_breaks():
    page = "7. Notice period. Either party may end\nthis lease by giving 30 days\n  written notice."

    start, end = locate(page, "this lease by giving 30 days written notice.")

    assert page[start:end] == "this lease by giving 30 days\n  written notice."


def test_locate_returns_none_when_the_passage_is_not_on_the_page():
    assert locate("Rent is due on day 5.", "Pets are not allowed") is None
    assert locate("Rent is due on day 5.", "   ") is None


def test_closest_sentence_picks_the_sentence_the_answer_rests_on():
    passage = (
        "6. Late payment. A late fee of Rs. 1,500 is added. 7. Notice period. Either party "
        "may end this lease by giving 30 days written notice. 8. Early termination."
    )

    start, end = closest_sentence(passage, "You must give 30 days written notice to end it.")

    assert passage[start:end] == "Either party may end this lease by giving 30 days written notice."
    assert closest_sentence(passage, "") is None
    assert closest_sentence(passage, "Pets and parking") is None


@pytest.mark.django_db
def test_a_tenant_sees_their_lease_page_with_the_cited_passage_marked(client):
    document = lease_document("ali@alpha.test")
    chunk = chunk_on(document, 2, "Either party may end this lease by giving")
    client.login(email="ali@alpha.test", password=PASSWORD)

    response = client.get(f"/documents/{document.id}/page/2/?chunk={chunk.id}")
    page = response.content.decode()

    assert response.status_code == 200
    assert "Page 2 of 3" in page
    assert '<mark id="cited">Either party may end this lease by giving</mark>' in page
    assert f"/documents/{document.id}/file/#page=2" in page


@pytest.mark.django_db
def test_the_page_still_shows_without_a_cited_passage(client):
    document = lease_document("ali@alpha.test")
    client.login(email="ali@alpha.test", password=PASSWORD)

    page = client.get(f"/documents/{document.id}/page/1/?chunk=not-a-number").content.decode()

    assert "RESIDENTIAL LEASE AGREEMENT" in page
    assert "<mark" not in page


@pytest.mark.django_db
def test_a_tenant_cannot_open_another_tenants_lease(client):
    other = lease_document("sara@alpha.test")
    client.login(email="ali@alpha.test", password=PASSWORD)

    assert client.get(f"/documents/{other.id}/page/1/").status_code == 404
    assert client.get(f"/documents/{other.id}/file/").status_code == 404


@pytest.mark.django_db
def test_nobody_can_open_a_document_from_another_organization(client):
    other = lease_document("omar@beta.test")

    for email in ("ali@alpha.test", "landlord@alpha.test"):
        client.login(email=email, password=PASSWORD)
        assert client.get(f"/documents/{other.id}/page/1/").status_code == 404
        assert client.get(f"/documents/{other.id}/file/").status_code == 404


@pytest.mark.django_db
def test_a_landlord_can_open_any_lease_in_their_own_organization(client):
    document = lease_document("sara@alpha.test")
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert client.get(f"/documents/{document.id}/page/1/").status_code == 200


@pytest.mark.django_db
def test_a_tenant_can_open_the_shared_policy_document(client):
    policy = Document.objects.filter(
        kind=Document.Kind.POLICY, organization__users__email="ali@alpha.test"
    ).first()
    client.login(email="ali@alpha.test", password=PASSWORD)

    assert client.get(f"/documents/{policy.id}/page/1/").status_code == 200


@pytest.mark.django_db
def test_the_viewer_needs_a_login_and_a_real_page(client):
    document = lease_document("ali@alpha.test")

    assert client.get(f"/documents/{document.id}/page/1/").status_code == 302
    client.login(email="ali@alpha.test", password=PASSWORD)
    assert client.get(f"/documents/{document.id}/page/99/").status_code == 404


@pytest.mark.django_db
def test_the_original_pdf_is_served_only_for_embedding_on_this_site(client):
    document = lease_document("ali@alpha.test")
    client.login(email="ali@alpha.test", password=PASSWORD)

    response = client.get(f"/documents/{document.id}/file/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["X-Frame-Options"] == "SAMEORIGIN"
    assert b"".join(response.streaming_content).startswith(b"%PDF")


@pytest.mark.django_db
def test_the_page_falls_back_to_stored_text_when_the_file_is_missing(client):
    document = lease_document("ali@alpha.test")
    document.file.save("gone.pdf", ContentFile(b"not a pdf"), save=True)
    chunk = chunk_on(document, 1, "Stored text of the first page.")
    client.login(email="ali@alpha.test", password=PASSWORD)

    page = client.get(f"/documents/{document.id}/page/1/?chunk={chunk.id}").content.decode()

    assert '<mark id="cited">Stored text of the first page.</mark>' in page
    assert "Open the PDF" not in page


@pytest.mark.django_db
def test_a_chat_citation_links_to_its_lease_page(client):
    from apps.agents.models import Conversation, Message

    user = User.objects.get(email="ali@alpha.test")
    document = lease_document("ali@alpha.test")
    conversation = Conversation.objects.create(organization=user.organization, user=user)
    Message.objects.create(
        organization=user.organization,
        conversation=conversation,
        role="assistant",
        content="30 days written notice [1].",
        citations=[
            {
                "number": 1,
                "title": "Lease agreement",
                "page": 2,
                "text": "7. Notice period.",
                "document_id": document.id,
                "chunk_id": 5,
            }
        ],
    )
    client.login(email="ali@alpha.test", password=PASSWORD)

    page = client.get("/chat/").content.decode()

    assert f"/documents/{document.id}/page/2/?chunk=5&amp;answer=" in page
    assert "Open page 2 of the lease" in page


def reply_to(email, content):
    from apps.agents.models import Conversation, Message

    user = User.objects.get(email=email)
    conversation = Conversation.objects.create(organization=user.organization, user=user)
    return Message.objects.create(
        organization=user.organization, conversation=conversation, role="assistant", content=content
    )


@pytest.mark.django_db
def test_the_sentence_closest_to_the_answer_stands_out(client):
    document = lease_document("ali@alpha.test")
    chunk = chunk_on(document, 2, PAGES[1])
    reply = reply_to("ali@alpha.test", "You need to give 30 days written notice to end the lease.")
    client.login(email="ali@alpha.test", password=PASSWORD)

    page = client.get(
        f"/documents/{document.id}/page/2/?chunk={chunk.id}&answer={reply.id}"
    ).content.decode()

    assert (
        '<mark id="cited" class="focus">Either party may end this lease by giving 30 days '
        "written notice.</mark>" in page
    )
    assert "<mark>7. Notice period. </mark>" in page


@pytest.mark.django_db
def test_another_tenants_answer_is_never_used(client):
    document = lease_document("ali@alpha.test")
    chunk = chunk_on(document, 2, PAGES[1])
    reply = reply_to("sara@alpha.test", "You need to give 30 days written notice.")
    client.login(email="ali@alpha.test", password=PASSWORD)

    page = client.get(
        f"/documents/{document.id}/page/2/?chunk={chunk.id}&answer={reply.id}"
    ).content.decode()

    assert 'class="focus"' not in page
    assert '<mark id="cited">' in page
