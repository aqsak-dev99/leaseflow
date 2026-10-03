import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.agents import services as agent_services
from apps.agents.models import AgentRun
from apps.maintenance import services as maintenance_services
from apps.maintenance.models import MaintenanceTicket
from apps.properties.models import Lease, Property, Unit

from .forms import TicketStatusForm


def _require_tenant(request):
    if request.user.role != "tenant":
        raise PermissionDenied


def _require_landlord(request):
    if request.user.role != "landlord":
        raise PermissionDenied


def home(request):
    if not request.user.is_authenticated:
        return render(request, "dashboard/landing.html")
    if request.user.role == "tenant":
        return _tenant_home(request)
    return _landlord_home(request)


def _tenant_home(request):
    lease = (
        Lease.objects.for_org(request.organization)
        .filter(tenant=request.user, status=Lease.Status.ACTIVE)
        .select_related("unit", "unit__property")
        .first()
    )
    tickets = maintenance_services.tickets_for(request.user)[:5]
    return render(request, "dashboard/tenant_home.html", {"lease": lease, "tickets": tickets})


def _landlord_home(request):
    org = request.organization
    units = Unit.objects.for_org(org)
    tickets = MaintenanceTicket.objects.for_org(org)
    context = {
        "occupied": units.filter(status=Unit.Status.OCCUPIED).count(),
        "vacant": units.filter(status=Unit.Status.VACANT).count(),
        "tenants": User.objects.filter(organization=org, role=User.Role.TENANT).count(),
        "open_tickets": tickets.exclude(status=MaintenanceTicket.Status.RESOLVED).count(),
        "recent_tickets": maintenance_services.tickets_for(request.user)[:5],
        "recent_runs": AgentRun.objects.for_org(org).order_by("-id")[:5],
    }
    return render(request, "dashboard/landlord_home.html", context)


@login_required
def properties(request):
    _require_landlord(request)
    org = request.organization
    active = {
        lease.unit_id: lease
        for lease in Lease.objects.for_org(org)
        .filter(status=Lease.Status.ACTIVE)
        .select_related("tenant")
    }
    rows = []
    for prop in Property.objects.for_org(org).prefetch_related("units").order_by("name"):
        units = [
            {"unit": unit, "lease": active.get(unit.id)}
            for unit in sorted(prop.units.all(), key=lambda unit: unit.unit_number)
        ]
        rows.append({"property": prop, "units": units})
    return render(request, "dashboard/properties.html", {"rows": rows})


@login_required
def tickets(request):
    _require_landlord(request)
    status = request.GET.get("status", "")
    items = maintenance_services.tickets_for(request.user)
    if status in MaintenanceTicket.Status.values:
        items = items.filter(status=status)
    context = {
        "tickets": items.select_related("reported_by"),
        "status": status,
        "statuses": MaintenanceTicket.Status.choices,
    }
    return render(request, "dashboard/tickets.html", context)


@login_required
def ticket_detail(request, ticket_id):
    try:
        ticket = maintenance_services.get_ticket(request.user, ticket_id)
    except PermissionDenied:
        raise Http404 from None
    is_landlord = request.user.role == "landlord"
    form = TicketStatusForm(request.POST or None, initial={"status": ticket.status})
    if request.method == "POST":
        _require_landlord(request)
        if form.is_valid():
            maintenance_services.update_status(
                user=request.user,
                ticket_id=ticket.id,
                new_status=form.cleaned_data["status"],
                note=form.cleaned_data["note"],
                cost=form.cleaned_data["cost"],
            )
            return redirect("dashboard:ticket_detail", ticket_id=ticket.id)
    context = {
        "ticket": ticket,
        "updates": ticket.updates.select_related("author"),
        "form": form,
        "is_landlord": is_landlord,
    }
    return render(request, "dashboard/ticket_detail.html", context)


@login_required
def activity(request):
    _require_landlord(request)
    runs = AgentRun.objects.for_org(request.organization)
    totals = runs.aggregate(
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
        latency=Avg("latency_ms"),
    )
    context = {
        "runs": runs.select_related("conversation__user").order_by("-id")[:50],
        "count": runs.count(),
        "totals": totals,
    }
    return render(request, "dashboard/activity.html", context)


@login_required
def run_detail(request, run_id):
    _require_landlord(request)
    run = get_object_or_404(
        AgentRun.objects.for_org(request.organization).select_related("conversation__user"),
        pk=run_id,
    )
    reply = run.messages.first()
    question = None
    if reply is not None:
        question = (
            reply.conversation.messages.filter(role="user", id__lt=reply.id).order_by("-id").first()
        )
    steps = [
        {**step, "detail_text": json.dumps(step.get("detail", {}), indent=2, default=str)}
        for step in run.steps
    ]
    context = {"run": run, "steps": steps, "question": question, "reply": reply}
    return render(request, "dashboard/run_detail.html", context)


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
