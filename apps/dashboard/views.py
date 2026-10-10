import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.accounts.models import User
from apps.agents import approvals as approval_services
from apps.agents import services as agent_services
from apps.agents.costs import estimate_cost
from apps.agents.models import AgentRun, ApprovalRequest
from apps.agents.triggers import run_overdue_check
from apps.billing import services as billing_services
from apps.billing.models import Invoice
from apps.maintenance import services as maintenance_services
from apps.maintenance.models import MaintenanceTicket
from apps.notifications import services as notification_services
from apps.properties import invitations as invitation_services
from apps.properties.models import Lease, Property, Unit

from .forms import TicketStatusForm
from .search import search as run_search
from .trace import describe_steps


def _require_tenant(request):
    if request.user.role != "tenant":
        raise PermissionDenied


def _require_landlord(request):
    if request.user.role != "landlord":
        raise PermissionDenied


def _paginate(request, items, per_page):
    """One page of `items`, plus the other query parameters to keep in the page links."""
    page = Paginator(items, per_page).get_page(request.GET.get("page"))
    params = request.GET.copy()
    params.pop("page", None)
    return page, params.urlencode()


def _question_for(run):
    """The tenant message that started a chat run, and the assistant's reply to it."""
    reply = run.messages.first()
    question = None
    if reply is not None:
        question = (
            reply.conversation.messages.filter(role="user", id__lt=reply.id).order_by("-id").first()
        )
    return question, reply


def home(request):
    if not request.user.is_authenticated:
        return redirect("accounts:login")
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
    next_invoice = (
        billing_services.invoices_for(request.user)
        .filter(status__in=[Invoice.Status.ISSUED, Invoice.Status.OVERDUE])
        .order_by("due_date")
        .first()
    )
    context = {
        "lease": lease,
        "tickets": maintenance_services.tickets_for(request.user)[:5],
        "balance": billing_services.balance_for(request.user),
        "next_invoice": next_invoice,
    }
    return render(request, "dashboard/tenant_home.html", context)


def _landlord_home(request):
    org = request.organization
    units = Unit.objects.for_org(org)
    tickets = MaintenanceTicket.objects.for_org(org)
    invoices = Invoice.objects.for_org(org)
    invoiced = invoices.exclude(status=Invoice.Status.WAIVED).aggregate(total=Sum("amount"))
    collected = invoices.filter(status=Invoice.Status.PAID).aggregate(total=Sum("amount"))
    invoiced, collected = invoiced["total"] or 0, collected["total"] or 0
    latest_run = (
        AgentRun.objects.for_org(org).select_related("conversation__user").order_by("-id").first()
    )
    latest_question = _question_for(latest_run)[0] if latest_run else None
    context = {
        "unit_count": units.count(),
        "invoiced": invoiced,
        "collected": collected,
        "collected_percent": round(100 * collected / invoiced) if invoiced else 0,
        "pending": approval_services.requests_for(request.user).filter(
            status=ApprovalRequest.Status.PENDING
        )[:2],
        "recent_invoices": billing_services.invoices_for(request.user)[:5],
        "latest_run": latest_run,
        "latest_question": latest_question,
        "latest_steps": describe_steps(latest_run.steps) if latest_run else [],
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
    invited = invitation_services.pending_by_unit(org)
    rows = []
    for prop in Property.objects.for_org(org).prefetch_related("units").order_by("name"):
        units = [
            {"unit": unit, "lease": active.get(unit.id), "invitation": invited.get(unit.id)}
            for unit in sorted(prop.units.all(), key=lambda unit: unit.unit_number)
        ]
        rows.append({"property": prop, "units": units})
    # A new invitation link is shown once, straight after it is made, and then forgotten.
    new_link = request.session.pop("invitation_link", None)
    return render(request, "dashboard/properties.html", {"rows": rows, "new_link": new_link})


@login_required
def tickets(request):
    _require_landlord(request)
    status = request.GET.get("status", "")
    items = maintenance_services.tickets_for(request.user)
    if status in MaintenanceTicket.Status.values:
        items = items.filter(status=status)
    page, query = _paginate(request, items.select_related("reported_by", "unit"), 10)
    context = {
        "tickets": page,
        "page": page,
        "query": query,
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
        cost=Sum("cost"),
    )
    by_route = (
        runs.values("route")
        .annotate(
            runs=Count("id"),
            input_tokens=Sum("input_tokens"),
            output_tokens=Sum("output_tokens"),
            cost=Sum("cost"),
        )
        .order_by("-cost")
    )
    page, query = _paginate(request, runs.select_related("conversation__user").order_by("-id"), 15)
    context = {
        "runs": page,
        "page": page,
        "query": query,
        "count": runs.count(),
        "totals": totals,
        "by_route": by_route,
        "input_price": settings.LLM_INPUT_PRICE,
        "output_price": settings.LLM_OUTPUT_PRICE,
    }
    return render(request, "dashboard/activity.html", context)


@login_required
def run_detail(request, run_id):
    _require_landlord(request)
    run = get_object_or_404(
        AgentRun.objects.for_org(request.organization).select_related("conversation__user"),
        pk=run_id,
    )
    question, reply = _question_for(run)
    steps = [
        {
            **step,
            "detail_text": json.dumps(step.get("detail", {}), indent=2, default=str),
            "cost": estimate_cost(step.get("input_tokens"), step.get("output_tokens")),
        }
        for step in describe_steps(run.steps)
    ]
    context = {"run": run, "steps": steps, "question": question, "reply": reply}
    return render(request, "dashboard/run_detail.html", context)


@never_cache
@login_required
def chat(request):
    _require_tenant(request)
    conversation = agent_services.current_conversation(request.user)
    context = {"chat_messages": conversation.messages.select_related("run")}
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
    page, query = _paginate(request, items, 12)
    context = {
        "invoices": page,
        "page": page,
        "query": query,
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


@login_required
def notifications(request):
    """Everything this user has been told, newest first."""
    items = notification_services.for_user(request.user)
    page, query = _paginate(request, items, 15)
    context = {"notifications": page, "page": page, "query": query}
    return render(request, "dashboard/notifications.html", context)


@login_required
def notifications_panel(request):
    """The short list shown under the bell. Loaded only when the bell is opened."""
    context = {"notifications": notification_services.for_user(request.user)[:6], "compact": True}
    return render(request, "dashboard/_notification_list.html", context)


@login_required
def notifications_count(request):
    """The number on the bell. The page asks for it again every minute."""
    return render(request, "dashboard/_notification_count.html")


@login_required
@require_POST
def notifications_read_all(request):
    notification_services.mark_all_read(request.user)
    return redirect("dashboard:notifications")


@login_required
def notification_open(request, notification_id):
    """Mark one notification as read, then go to the page it is about."""
    try:
        url = notification_services.open_notification(request.user, notification_id)
    except PermissionDenied:
        raise Http404 from None
    if not url or not url_has_allowed_host_and_scheme(url, allowed_hosts=None):
        return redirect("dashboard:notifications")
    return redirect(url)


@login_required
def search(request):
    _require_landlord(request)
    query = request.GET.get("q", "").strip()[:80]
    results = run_search(request.user, query, limit=10)
    context = {"q": query, "results": results, "found": any(results.values())}
    return render(request, "dashboard/search.html", context)


@login_required
def search_suggest(request):
    """The dropdown under the search box while the landlord types."""
    _require_landlord(request)
    query = request.GET.get("q", "").strip()[:80]
    results = run_search(request.user, query, limit=3)
    context = {"q": query, "results": results, "found": any(results.values()), "compact": True}
    return render(request, "dashboard/_search_results.html", context)
