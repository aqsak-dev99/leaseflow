"""The payment agent: answers account questions in chat, and drafts overdue reminders."""

import time
from pathlib import Path

from django.utils import timezone
from langchain_core.messages import HumanMessage, SystemMessage

from apps.core.ai import get_chat_model
from apps.documents.retrieval import search_chunks

from .text import text_of
from .tool_loop import history_messages, run_tool_loop
from .tools.payments import build_payment_tools

PROMPTS = Path(__file__).parent / "prompts"
PROMPT = (PROMPTS / "payment_agent.md").read_text()
REMINDER_PROMPT = (PROMPTS / "reminder_draft.md").read_text()


def run_payment_agent(*, user, text, history=(), trace=None):
    tools = build_payment_tools(user)
    model = get_chat_model().bind_tools(tools)
    messages = [SystemMessage(PROMPT), *history_messages(history), HumanMessage(text)]
    return run_tool_loop(
        model=model, tools=tools, messages=messages, name="payment_agent", trace=trace
    )


def template_reminder(invoice):
    """A plain reminder used when the model is unavailable."""
    tenant = invoice.lease.tenant
    subject = f"Rent reminder for {invoice.period:%B %Y}"
    body = (
        f"Dear {tenant.first_name or 'tenant'},\n\n"
        f"Our records show that your rent of Rs. {invoice.amount:,.0f} for "
        f"{invoice.period:%B %Y} was due on {invoice.due_date:%d %B %Y} and has not been "
        "received yet.\n\n"
        "You can pay from the Rent page of your LeaseFlow account. If you have already "
        "paid or something is wrong, please reply to this email.\n\n"
        f"Thank you,\n{invoice.organization.name}"
    )
    return subject, body


def _late_fee_clause(invoice, trace):
    """Look up what this tenant's own lease says about late payment, if anything."""
    started = time.monotonic()
    try:
        chunks = search_chunks(
            organization=invoice.organization,
            lease=invoice.lease,
            query="late payment fee if rent is not received",
            limit=1,
        )
    except Exception:
        return ""
    if trace is not None:
        results = [{"title": c.document.title, "page": c.page_number} for c in chunks]
        trace.add("retrieval", "search_lease_documents", started, {"results": results})
    return chunks[0].text if chunks else ""


def draft_reminder(invoice, trace=None):
    """Ask the model to write a reminder for one overdue invoice. Returns (subject, body)."""
    tenant = invoice.lease.tenant
    days_late = (timezone.localdate() - invoice.due_date).days
    clause = _late_fee_clause(invoice, trace)
    facts = (
        f"Landlord's business name: {invoice.organization.name}\n"
        f"Tenant's first name: {tenant.first_name or 'not known'}\n"
        f"Unit: {invoice.lease.unit.unit_number}\n"
        f"Rent month: {invoice.period:%B %Y}\n"
        f"Amount due: Rs. {invoice.amount:,.0f}\n"
        f"Due date: {invoice.due_date:%d %B %Y}\n"
        f"Days overdue: {max(days_late, 0)}\n"
        f"Lease clause about late payment: {clause or 'none provided'}"
    )
    started = time.monotonic()
    reply = get_chat_model().invoke([("system", REMINDER_PROMPT), ("human", facts)])
    if trace is not None:
        trace.add_model_call("payment_agent", started, reply, {"task": "draft_reminder"})

    text = text_of(reply.content)
    first, _, rest = text.partition("\n")
    if not first.lower().startswith("subject:") or not rest.strip():
        raise ValueError("The model did not return a subject line and a body.")
    return first[len("subject:") :].strip()[:200], rest.strip()
