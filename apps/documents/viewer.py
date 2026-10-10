"""Shows a tenant or landlord the lease page behind a citation.

The assistant's answers cite a page of the lease. This module finds that page,
checks the person is allowed to see it, and marks the exact passage that was cited.
"""

import re

from django.http import Http404
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .models import Document


def document_for(user, document_id):
    """The document, or a 404 if this person may not see it.

    Landlords can open any document in their own organization. Tenants can only
    open their own lease and the organization's shared policy documents. A 404 is
    used for both "not found" and "not yours" so that ids cannot be probed.
    """
    document = (
        Document.objects.for_org(user.organization)
        .select_related("lease")
        .filter(pk=document_id)
        .first()
    )
    if document is None:
        raise Http404
    if user.role == "tenant" and document.lease is not None and document.lease.tenant_id != user.id:
        raise Http404
    return document


def read_pages(document):
    """The text of every page, in order, with its line breaks kept. Empty if unreadable."""
    try:
        with document.file.open("rb") as file_obj:
            return [page.extract_text() or "" for page in PdfReader(file_obj).pages]
    except (OSError, ValueError, PyPdfError):
        return []


def locate(page_text, passage):
    """Where `passage` sits in `page_text`, as (start, end), or None.

    Chunks are stored with every run of spaces and line breaks squeezed into one
    space, so the passage is searched for in a squeezed copy of the page and the
    position is then mapped back onto the original text.
    """
    squeezed = []
    positions = []
    gap = True
    for index, char in enumerate(page_text):
        if char.isspace():
            if not gap:
                squeezed.append(" ")
                positions.append(index)
            gap = True
        else:
            squeezed.append(char)
            positions.append(index)
            gap = False
    needle = " ".join(passage.split())
    if not needle:
        return None
    found = "".join(squeezed).find(needle)
    if found == -1:
        return None
    return positions[found], positions[found + len(needle) - 1] + 1


COMMON_WORDS = frozenset(
    "a an and are as at be by for from if in is it its of on or that the this to was with "
    "you your i my me we our they their not no may must will can".split()
)


def key_words(text):
    """The words that carry meaning, lower-cased, with punctuation and filler words removed."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {word for word in words if word not in COMMON_WORDS}


def closest_sentence(passage, answer):
    """The sentence of `passage` that shares the most words with `answer`, as (start, end).

    A cited passage is a few hundred characters long. This picks out the one sentence
    the answer most likely rests on, so the reader's eye lands on it first. It is a
    reading aid only: the whole cited passage stays marked as well.
    """
    wanted = key_words(answer)
    best, best_score = None, 1
    for match in re.finditer(r"[^.!?]+[.!?]*", passage):
        score = len(key_words(match.group()) & wanted)
        if score > best_score:
            start = match.start() + len(match.group()) - len(match.group().lstrip())
            best, best_score = (start, match.end()), score
    return best


def page_view(document, page_number, chunk_id=None, answer=""):
    """Everything the page template needs: the page text split around the cited passage."""
    chunks = list(document.chunks.filter(page_number=page_number).order_by("chunk_index"))
    cited = next((chunk for chunk in chunks if chunk.id == chunk_id), None)
    pages = read_pages(document)
    page_count = len(pages) or (
        document.chunks.order_by("-page_number").values_list("page_number", flat=True).first() or 0
    )
    if not 1 <= page_number <= max(page_count, 1):
        raise Http404

    text = pages[page_number - 1] if pages else ""
    if not text.strip():
        # The file could not be read: fall back to the text stored when it was processed.
        text = "\n\n".join(chunk.text for chunk in chunks)
    span = locate(text, cited.text) if cited is not None else None
    parts = {"before": text, "lead": "", "focus": "", "tail": "", "after": ""}
    if span is not None:
        marked = text[span[0] : span[1]]
        focus = closest_sentence(marked, answer) or (0, 0)
        parts = {
            "before": text[: span[0]],
            "lead": marked[: focus[0]],
            "focus": marked[focus[0] : focus[1]],
            "tail": marked[focus[1] :],
            "after": text[span[1] :],
        }
    return {
        "document": document,
        "page_number": page_number,
        "page_count": page_count,
        "previous_page": page_number - 1 if page_number > 1 else None,
        "next_page": page_number + 1 if page_number < page_count else None,
        "cited": span is not None,
        "has_file": bool(pages),
        **parts,
    }
