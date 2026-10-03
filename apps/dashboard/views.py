from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.agents import services as agent_services


def home(request):
    return render(request, "dashboard/home.html")


def _require_tenant(request):
    if request.user.role != "tenant":
        raise PermissionDenied


@login_required
def chat(request):
    _require_tenant(request)
    conversation = agent_services.current_conversation(request.user)
    return render(request, "dashboard/chat.html", {"messages": conversation.messages.all()})


@login_required
@require_POST
def chat_send(request):
    _require_tenant(request)
    text = request.POST.get("question", "").strip()[:500]
    if not text:
        return HttpResponse("")
    messages = agent_services.handle_message(user=request.user, text=text)
    return render(request, "dashboard/_chat_exchange.html", {"messages": messages})


@login_required
@require_POST
def chat_new(request):
    _require_tenant(request)
    agent_services.start_conversation(request.user)
    return redirect("dashboard:chat")
