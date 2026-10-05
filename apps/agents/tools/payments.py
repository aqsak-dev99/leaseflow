"""Tools the payment agent can call.

As with the maintenance tools, the user is fixed when the tools are built. There
is deliberately no tool that waives an invoice or marks one as paid: the agent
can only read, create a payment link, and ask the landlord.
"""

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError

from apps.billing import services as billing_services

from .. import approvals


def _error(exc):
    if isinstance(exc, ValidationError):
        return "Error: " + " ".join(exc.messages)
    return f"Error: {exc}"


def _line(invoice):
    return (
        f"Invoice {invoice.id}: rent for {invoice.period:%B %Y}, Rs. {invoice.amount:,.0f}, "
        f"due {invoice.due_date:%d %b %Y}, status {invoice.get_status_display().lower()}"
    )


def build_payment_tools(user):
    from langchain_core.tools import tool

    @tool
    def get_balance() -> str:
        """Show how much the tenant owes right now and which invoices are unpaid."""
        unpaid = [invoice for invoice in billing_services.invoices_for(user) if invoice.is_unpaid]
        if not unpaid:
            return "The tenant owes nothing. There are no unpaid invoices."
        total = billing_services.balance_for(user)
        lines = "\n".join(_line(invoice) for invoice in unpaid)
        return f"Total owed: Rs. {total:,.0f}\n{lines}"

    @tool
    def list_invoices() -> str:
        """List the tenant's recent invoices, paid and unpaid, newest first."""
        invoices = list(billing_services.invoices_for(user)[:12])
        if not invoices:
            return "The tenant has no invoices yet."
        return "\n".join(_line(invoice) for invoice in invoices)

    @tool
    def create_payment_link(invoice_id: int) -> str:
        """Create a link the tenant can open to pay one of their own unpaid invoices."""
        try:
            _, path = billing_services.start_gateway_payment(user=user, invoice_id=invoice_id)
        except (ValidationError, PermissionDenied) as exc:
            return _error(exc)
        return f"Payment link for invoice {invoice_id}: {settings.SITE_URL}{path}"

    @tool
    def request_waiver(invoice_id: int, reason: str) -> str:
        """Ask the landlord to waive one of the tenant's unpaid invoices.

        This only files a request. The invoice stays due until the landlord approves.
        reason: why the tenant is asking, in their own words.
        """
        try:
            invoice = billing_services.get_invoice(user, invoice_id)
            _, created = approvals.request_waiver(user=user, invoice=invoice, reason=reason)
        except (ValidationError, PermissionDenied) as exc:
            return _error(exc)
        if not created:
            return (
                f"A waiver request for invoice {invoice_id} is already waiting for the "
                "landlord. No new request was filed."
            )
        return (
            f"Waiver request filed for invoice {invoice_id}. The landlord will decide. "
            "The invoice is still due until they approve."
        )

    return [get_balance, list_invoices, create_payment_link, request_waiver]
