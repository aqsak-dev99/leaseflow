import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Avg, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.agents import approvals as approval_services
from apps.agents import services as agent_services
from apps.agents.models import AgentRun, ApprovalRequest
from apps.agents.triggers import run_overdue_check
from apps.billing import services as billing_services
from apps.billing.models import Invoice
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
    context = {
        "lease": lease,
        "tickets": maintenance_services.tickets_for(request.user)[:5],
        "balance": billing_services.balance_for(request.user),
    }
    return render(request, "dashboard/tenant_home.html", context)


def _landlord_home(request):
    org = request.organization
    units = Unit.objects.for_org(org)
    tickets = MaintenanceTicket.objects.for_org(org)
    context = {
        "occupied": units.filter(status=Unit.Status.OCCUPIED).count(),
        "vacant": units.filter(status=Unit.Status.VACANT).count(),
        "tenants": User.objects.filter(organization=org, role=User.Role.TENANT).count(),
        "open_tickets": tickets.exclude(status=MaintenanceTicket.Status.RESOLVED).count(),
        "outstanding": billing_services.balance_for(request.user),
        "pending_approvals": ApprovalRequest.objects.for_org(org)
        .filter(status=ApprovalRequest.Status.PENDING)
        .count(),
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
    context = {"chat_messages": conversation.messages.all()}
    return render(request, "dashboard/chat.html", context)


@login_required
@require_POST
def chat_send(request):
    _require_tenant(request)
    text = request.POST.get("question", "").strip()[:500]
    if not text:
        return HttpResponse("")
    exchange = agent_services.handle_message(user=request.user, text=text)
    return render(request, "dashboard/_chat_exchange.html", {"chat_messages": exchange})


@login_required
@require_POST
def chat_new(request):
    _require_tenant(request)
    agent_services.start_conversation(request.user)
    return redirect("dashboard:chat")


@login_required
def invoices(request):
    items = billing_services.invoices_for(request.user)
    context = {
        "invoices": items[:100],
        "balance": billing_services.balance_for(request.user),
        "overdue": items.filter(status=Invoice.Status.OVERDUE).count(),
        "is_landlord": request.user.role == "landlord",
    }
    return render(request, "dashboard/invoices.html", context)


@login_required
@require_POST
def invoice_pay(request, invoice_id):
    """A tenant starts paying: we create the payment and send them to the gateway."""
    _require_tenant(request)
    try:
        _, checkout_url = billing_services.start_gateway_payment(
            user=request.user, invoice_id=invoice_id
        )
    except PermissionDenied:
        raise Http404 from None
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect("dashboard:invoices")
    return redirect(checkout_url)


@login_required
@require_POST
def invoice_record_payment(request, invoice_id):
    """A landlord records cash or a bank transfer."""
    _require_landlord(request)
    try:
        billing_services.record_manual_payment(
            user=request.user,
            invoice_id=invoice_id,
            reference=request.POST.get("reference", ""),
        )
    except PermissionDenied:
        raise Http404 from None
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Payment recorded.")
    return redirect("dashboard:invoices")


@login_required
@require_POST
def invoices_generate(request):
    """Create this month's invoices now, without waiting for the scheduled job."""
    _require_landlord(request)
    created = billing_services.generate_invoices(organization=request.organization)
    messages.success(request, f"{created} new invoice(s) created for this month.")
    return redirect("dashboard:invoices")


@login_required
def approvals(request):
    _require_landlord(request)
    items = approval_services.requests_for(request.user)
    context = {
        "pending": items.filter(status=ApprovalRequest.Status.PENDING),
        "decided": items.exclude(status=ApprovalRequest.Status.PENDING)[:20],
    }
    return render(request, "dashboard/approvals.html", context)


@login_required
@require_POST
def approval_decide(request, request_id):
    _require_landlord(request)
    try:
        if request.POST.get("action") == "approve":
            decided = approval_services.approve(
                user=request.user,
                request_id=request_id,
                subject=request.POST.get("subject"),
                body=request.POST.get("body"),
            )
            if decided.kind == ApprovalRequest.Kind.REMINDER:
                messages.success(request, "Approved. The reminder has been sent to the tenant.")
            else:
                messages.success(request, "Approved. The invoice has been waived.")
        else:
            approval_services.reject(
                user=request.user, request_id=request_id, note=request.POST.get("note", "")
            )
            messages.success(request, "Rejected. Nothing was sent or changed.")
    except PermissionDenied:
        raise Http404 from None
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("dashboard:approvals")


@login_required
@require_POST
def overdue_check_now(request):
    """Run the daily overdue check now, for this organization only."""
    _require_landlord(request)
    drafted = run_overdue_check(organization=request.organization, pause=2)
    messages.success(request, f"{len(drafted)} new reminder(s) drafted for your approval.")
    return redirect("dashboard:approvals")
