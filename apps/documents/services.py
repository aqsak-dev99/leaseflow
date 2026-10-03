from django.db import transaction
from pypdf import PdfReader

from apps.core.ai import embed_documents

from .chunking import split_text
from .models import Document, DocumentChunk


def extract_pages(file_obj):
    """Return a list of (page_number, text), with pages numbered from 1."""
    reader = PdfReader(file_obj)
    return [(number, page.extract_text() or "") for number, page in enumerate(reader.pages, 1)]


def process_document(document_id):
    """Read a PDF, split it into chunks, embed them and store them. Safe to re-run."""
    document = Document.objects.get(pk=document_id)
    document.status = Document.Status.PROCESSING
    document.save(update_fields=["status"])
    try:
        with document.file.open("rb") as file_obj:
            pages = extract_pages(file_obj)
        pieces = [
            (page_number, text)
            for page_number, page_text in pages
            for text in split_text(page_text)
        ]
        vectors = embed_documents([text for _, text in pieces]) if pieces else []
        with transaction.atomic():
            document.chunks.all().delete()
            DocumentChunk.objects.bulk_create(
                DocumentChunk(
                    organization=document.organization,
                    document=document,
                    lease=document.lease,
                    page_number=page_number,
                    chunk_index=index,
                    text=text,
                    embedding=vector,
                )
                for index, ((page_number, text), vector) in enumerate(zip(pieces, vectors))
            )
    except Exception as exc:
        document.status = Document.Status.FAILED
        document.error = str(exc)[:500]
        document.save(update_fields=["status", "error"])
        raise
    document.status = Document.Status.READY
    document.error = ""
    document.save(update_fields=["status", "error"])
    return len(pieces)
