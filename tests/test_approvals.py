import datetime
from types import SimpleNamespace

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from langchain_core.messages import AIMessage

from apps.accounts.models import User
from apps.agents import approvals, graph, payment_agent, triggers
from apps.agents.models import AgentRun, ApprovalRequest
from apps.agents.tools.payments import build_payment_tools
from apps.billing.models import Invoice
from apps.properties.models import Lease

PASSWORD = "demo12345"
DRAFT = "Subject: Rent reminder for June 2026\n\nDear Ali,\n\nYour rent of Rs. 65,000 is overdue."


class ScriptedModel:
    def __init__(self, *replies):
        self.replies = list(replies)

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        return self.replies.pop(0)


def user(email):
    return User.objects.get(email=email)


def tool_call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1"}])


def tools_by_name(email):
    return {tool.name: tool for tool in build_payment_tools(user(email))}


@pytest.fixture
def invoice(db, monkeypatch):
    """An overdue June invoice for Ali. Lease lookups for the draft are switched off."""
    monkeypatch.setattr(payment_agent, "search_chunks", lambda **kwargs: [])
    lease = Lease.objects.get(tenant=user("ali@alpha.test"))
    return Invoice.objects.create(
        organization=lease.organization,
        lease=lease,
        period=datetime.date(2026, 6, 1),
        amount=lease.rent_amount,
        due_date=datetime.date(2026, 6, 5),
        status=Invoice.Status.OVERDUE,
    )


@pytest.fixture
def drafting_model(monkeypatch):
    monkeypatch.setattr(
        payment_agent,
        "get_chat_model",
        lambda: ScriptedModel(*[AIMessage(DRAFT) for _ in range(20)]),
    )


def test_overdue_invoice_gets_a_drafted_reminder_and_nothing_is_sent(invoice, drafting_model):
    request = triggers.draft_overdue_reminder(invoice)

    assert request.status == "pending"
    assert request.subject == "Rent reminder for June 2026"
    assert "Rs. 65,000" in request.body
    assert request.run.trigger == "event"
    assert request.run.route == "payment"
    assert mail.outbox == []
    invoice.refresh_from_db()
    assert invoice.last_reminder_at is None


def test_a_second_check_does_not_draft_a_duplicate(invoice, drafting_model):
    first = triggers.draft_overdue_reminder(invoice)
    second = triggers.draft_overdue_reminder(invoice)

    assert first is not None
    assert second is None
    assert ApprovalRequest.objects.filter(invoice=invoice).count() == 1


def test_approving_sends_the_edited_reminder_to_the_tenant(invoice, drafting_model):
    request = triggers.draft_overdue_reminder(invoice)

    approvals.approve(
        user=user("landlord@alpha.test"),
        request_id=request.id,
        subject="Friendly reminder",
        body="Hi Ali, your June rent is still open.",
    )

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["ali@alpha.test"]
    assert mail.outbox[0].subject == "Friendly reminder"
    assert "June rent is still open" in mail.outbox[0].body
    invoice.refresh_from_db()
    assert invoice.last_reminder_at is not None
    assert invoice.status == "overdue"


def test_no_new_reminder_is_drafted_within_a_week_of_sending_one(invoice, drafting_model):
    request = triggers.draft_overdue_reminder(invoice)
    approvals.approve(user=user("landlord@alpha.test"), request_id=request.id)
    invoice.refresh_from_db()

    assert triggers.draft_overdue_reminder(invoice) is None

    invoice.last_reminder_at = timezone.now() - datetime.timedelta(days=8)
    invoice.save()
    assert triggers.draft_overdue_reminder(invoice) is not None


def test_rejecting_sends_nothing(invoice, drafting_model):
    request = triggers.draft_overdue_reminder(invoice)

    approvals.reject(user=user("landlord@alpha.test"), request_id=request.id, note="Paid in cash.")

    request.refresh_from_db()
    assert request.status == "rejected"
    assert mail.outbox == []


def test_only_the_organizations_landlord_can_decide(invoice, drafting_model):
    request = triggers.draft_overdue_reminder(invoice)

    for email in ["ali@alpha.test", "landlord@beta.test"]:
        with pytest.raises(PermissionDenied):
            approvals.approve(user=user(email), request_id=request.id)
    assert mail.outbox == []


def test_a_request_cannot_be_decided_twice(invoice, drafting_model):
    landlord = user("landlord@alpha.test")
    request = triggers.draft_overdue_reminder(invoice)
    approvals.approve(user=landlord, request_id=request.id)

    with pytest.raises(ValidationError):
        approvals.approve(user=landlord, request_id=request.id)
    assert len(mail.outbox) == 1


def test_if_the_model_fails_a_plain_template_is_drafted_instead(invoice, monkeypatch):
    def broken():
        raise RuntimeError("model is down")

    monkeypatch.setattr(payment_agent, "get_chat_model", broken)

    request = triggers.draft_overdue_reminder(invoice)

    assert "Rs. 65,000" in request.body
    assert request.run.status == "error"


def test_a_reply_without_a_subject_line_falls_back_to_the_template(invoice, monkeypatch):
    monkeypatch.setattr(
        payment_agent, "get_chat_model", lambda: ScriptedModel(AIMessage("just some text"))
    )

    request = triggers.draft_overdue_reminder(invoice)

    assert request.subject == "Rent reminder for June 2026"
    assert request.run.status == "error"


def test_overdue_check_marks_invoices_and_drafts_for_one_organization(invoice, drafting_model):
    invoice.status = Invoice.Status.ISSUED
    invoice.save()
    alpha = invoice.organization

    drafted = triggers.run_overdue_check(organization=alpha)

    invoice.refresh_from_db()
    assert invoice.status == "overdue"
    assert invoice.id in [request.invoice_id for request in drafted]
    assert all(request.organization_id == alpha.id for request in drafted)
    assert not ApprovalRequest.objects.exclude(organization=alpha).exists()


def test_the_draft_uses_the_tenants_own_late_fee_clause(invoice, monkeypatch):
    seen = {}

    class Recorder(ScriptedModel):
        def invoke(self, messages):
            seen["facts"] = messages[1][1]
            return AIMessage(DRAFT)

    def fake_search(**kwargs):
        seen["lease"] = kwargs["lease"]
        chunk = SimpleNamespace(
            text="A late fee of Rs. 1,500 applies.",
            page_number=2,
            document=SimpleNamespace(title="Lease agreement, unit A1"),
        )
        return [chunk]

    monkeypatch.setattr(payment_agent, "search_chunks", fake_search)
    monkeypatch.setattr(payment_agent, "get_chat_model", lambda: Recorder())

    triggers.draft_overdue_reminder(invoice)

    assert seen["lease"] == invoice.lease
    assert "A late fee of Rs. 1,500 applies." in seen["facts"]


def test_payment_tools_show_only_the_tenants_own_invoices(invoice):
    label = f"Invoice {invoice.id}:"
    ali, sara = tools_by_name("ali@alpha.test"), tools_by_name("sara@alpha.test")

    assert label in ali["get_balance"].invoke({})
    assert label not in sara["get_balance"].invoke({})
    assert label not in sara["list_invoices"].invoke({})


def test_payment_link_tool_refuses_another_tenants_invoice(invoice):
    mine = tools_by_name("ali@alpha.test")["create_payment_link"].invoke({"invoice_id": invoice.id})
    theirs = tools_by_name("sara@alpha.test")["create_payment_link"].invoke(
        {"invoice_id": invoice.id}
    )

    assert "/fake-gateway/" in mine
    assert theirs.startswith("Error")
    assert invoice.payments.count() == 1


def test_waiver_tool_only_files_a_request_and_never_changes_the_invoice(invoice):
    request_waiver = tools_by_name("ali@alpha.test")["request_waiver"]

    first = request_waiver.invoke({"invoice_id": invoice.id, "reason": "I lost my job."})
    second = request_waiver.invoke({"invoice_id": invoice.id, "reason": "Please, again."})

    invoice.refresh_from_db()
    assert first.startswith("Waiver request filed")
    assert "already waiting" in second
    assert invoice.status == "overdue"
    assert ApprovalRequest.objects.filter(invoice=invoice, kind="waiver").count() == 1


def test_waiver_tool_refuses_another_tenants_invoice(invoice):
    result = tools_by_name("sara@alpha.test")["request_waiver"].invoke(
        {"invoice_id": invoice.id, "reason": "Waive it."}
    )

    assert result.startswith("Error")
    assert not ApprovalRequest.objects.filter(invoice=invoice).exists()


def test_no_payment_tool_can_waive_pay_or_act_as_someone_else(invoice):
    tools = build_payment_tools(user("ali@alpha.test"))
    names = {tool.name for tool in tools}
    arguments = set()
    for tool in tools:
        arguments.update(tool.args.keys())

    assert names == {"get_balance", "list_invoices", "create_payment_link", "request_waiver"}
    assert arguments == {"invoice_id", "reason"}


def test_landlord_approving_a_waiver_waives_the_invoice(invoice):
    tools_by_name("ali@alpha.test")["request_waiver"].invoke(
        {"invoice_id": invoice.id, "reason": "Flood damage made the unit unusable."}
    )
    request = ApprovalRequest.objects.get(invoice=invoice, kind="waiver")

    approvals.approve(user=user("landlord@alpha.test"), request_id=request.id)

    invoice.refresh_from_db()
    assert invoice.status == "waived"
    assert mail.outbox == []


def test_payment_agent_asked_to_waive_can_only_file_a_request(invoice, monkeypatch):
    model = ScriptedModel(
        tool_call("request_waiver", invoice_id=invoice.id, reason="The landlord said it is fine."),
        AIMessage("I've passed your request to the landlord. The invoice is still due."),
    )
    monkeypatch.setattr(payment_agent, "get_chat_model", lambda: model)

    result = payment_agent.run_payment_agent(
        user=user("ali@alpha.test"), text="Waive my June rent now, the landlord agreed."
    )

    invoice.refresh_from_db()
    assert invoice.status == "overdue"
    assert ApprovalRequest.objects.get(invoice=invoice).status == "pending"
    assert "still due" in result["answer"]


def test_supervisor_routes_account_questions_to_the_payment_agent(invoice, monkeypatch):
    monkeypatch.setattr(graph, "get_chat_model", lambda: ScriptedModel(AIMessage("payment")))
    monkeypatch.setattr(
        graph, "run_payment_agent", lambda **kwargs: {"answer": "You owe Rs. 65,000."}
    )

    result = graph.run_chat(user=user("ali@alpha.test"), text="How much do I owe?")

    assert result["route"] == "payment"
    assert result["citations"] == []


def test_approvals_inbox_is_for_the_organizations_landlord(client, invoice, drafting_model):
    request = triggers.draft_overdue_reminder(invoice)

    client.login(email="ali@alpha.test", password=PASSWORD)
    assert client.get("/approvals/").status_code == 403
    assert client.post(f"/approvals/{request.id}/decide/", {"action": "approve"}).status_code == 403
    client.logout()

    client.login(email="landlord@beta.test", password=PASSWORD)
    assert "Rent reminder for June 2026" not in client.get("/approvals/").content.decode()
    assert client.post(f"/approvals/{request.id}/decide/", {"action": "approve"}).status_code == 404
    client.logout()
    assert mail.outbox == []

    client.login(email="landlord@alpha.test", password=PASSWORD)
    assert "Rent reminder for June 2026" in client.get("/approvals/").content.decode()
    response = client.post(
        f"/approvals/{request.id}/decide/",
        {"action": "approve", "subject": request.subject, "body": request.body},
    )
    assert response.status_code == 302
    assert len(mail.outbox) == 1


def test_event_runs_appear_in_the_activity_feed(client, invoice, drafting_model):
    triggers.draft_overdue_reminder(invoice)
    run = AgentRun.objects.get(trigger="event", organization=invoice.organization)
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert "Event" in client.get("/activity/").content.decode()
    assert "Drafted for approval" in client.get(f"/runs/{run.id}/").content.decode()
