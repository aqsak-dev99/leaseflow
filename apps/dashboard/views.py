import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from apps.agents.lease_agent import answer_lease_question

logger = logging.getLogger(__name__)

UNAVAILABLE = "Sorry, the assistant is unavailable right now. Please try again in a minute."


def home(request):
    return render(request, "dashboard/home.html")


def _require_tenant(request):
    if request.user.role != "tenant":
        raise PermissionDenied


@login_required
def chat(request):
    _require_tenant(request)
    return render(request, "dashboard/chat.html")


@login_required
@require_POST
def chat_send(request):
    _require_tenant(request)
    question = request.POST.get("question", "").strip()[:500]
    if not question:
        return HttpResponse("")
    try:
        result = answer_lease_question(user=request.user, question=question)
    except Exception:
        logger.exception("Lease agent failed")
        result = {"answer": UNAVAILABLE, "citations": []}
    return render(request, "dashboard/_chat_exchange.html", {"question": question, **result})
