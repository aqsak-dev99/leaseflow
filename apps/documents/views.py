from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.http import require_GET

from apps.agents.models import Message

from .viewer import document_for, page_view


def _answer_text(request):
    """The assistant reply a citation link came from, if this person may read it."""
    answer_id = request.GET.get("answer", "")
    if not answer_id.isdigit():
        return ""
    replies = Message.objects.for_org(request.user.organization).filter(pk=int(answer_id))
    if request.user.role == "tenant":
        replies = replies.filter(conversation__user=request.user)
    reply = replies.first()
    return reply.content if reply is not None else ""


@login_required
@require_GET
def document_page(request, document_id, page_number):
    """One page of a lease, with the passage an answer cited marked on it."""
    document = document_for(request.user, document_id)
    chunk = request.GET.get("chunk", "")
    context = page_view(
        document,
        page_number,
        chunk_id=int(chunk) if chunk.isdigit() else None,
        answer=_answer_text(request),
    )
    context["back"] = "dashboard:chat" if request.user.role == "tenant" else "dashboard:activity"
    return render(request, "documents/page.html", context)


@login_required
@require_GET
@xframe_options_sameorigin
def document_file(request, document_id):
    """The original PDF, shown in the browser. Only this app's own pages may embed it."""
    document = document_for(request.user, document_id)
    try:
        handle = document.file.open("rb")
    except (OSError, ValueError) as exc:
        raise Http404 from exc
    return FileResponse(handle, content_type="application/pdf", filename=f"{document.title}.pdf")
