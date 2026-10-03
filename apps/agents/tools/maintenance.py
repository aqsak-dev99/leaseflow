"""Tools the maintenance agent can call.

The user is fixed when the tools are built and is never a tool argument, so the
model cannot act as anyone else. Each tool calls the same service functions as
the web pages, which is where the permission checks live.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from langchain_core.tools import tool

from apps.maintenance import services


def _error(exc):
    if isinstance(exc, ValidationError):
        return "Error: " + " ".join(exc.messages)
    return f"Error: {exc}"


def build_maintenance_tools(user):
    @tool
    def create_ticket(
        title: str,
        description: str,
        category: str = "other",
        priority: str = "medium",
        allow_duplicate: bool = False,
    ) -> str:
        """Create a maintenance ticket for the tenant's own unit.

        title: a short summary, such as "Kitchen sink leaking".
        description: what is wrong and where, in the tenant's words.
        category: plumbing, electrical, appliance, structural or other.
        priority: low, medium, high or urgent.
        allow_duplicate: set true only after the tenant confirms they want a new
        ticket even though an open one exists in the same category.
        """
        try:
            existing = services.find_open_ticket(user, category)
            if existing is not None and not allow_duplicate:
                return (
                    f"Not created. An open ticket already exists in this category: "
                    f"#{existing.id} '{existing.title}' ({existing.get_status_display()}). "
                    "Ask the tenant whether to add a comment to it or open a new ticket."
                )
            ticket = services.create_ticket(
                user=user,
                title=title,
                description=description,
                category=category,
                priority=priority,
                via_agent=True,
            )
        except (ValidationError, PermissionDenied) as exc:
            return _error(exc)
        return (
            f"Created ticket #{ticket.id} '{ticket.title}' for unit {ticket.unit.unit_number} "
            f"(category {ticket.category}, priority {ticket.priority}, status open)."
        )

    @tool
    def list_my_tickets() -> str:
        """List the tenant's own maintenance tickets with their current status."""
        tickets = list(services.tickets_for(user)[:10])
        if not tickets:
            return "The tenant has no maintenance tickets."
        return "\n".join(
            f"#{ticket.id} '{ticket.title}' - {ticket.get_status_display()}, "
            f"{ticket.priority} priority, reported {ticket.created_at:%d %b %Y}"
            for ticket in tickets
        )

    @tool
    def add_ticket_comment(ticket_id: int, note: str) -> str:
        """Add a comment from the tenant to one of their own tickets."""
        try:
            services.add_comment(user=user, ticket_id=ticket_id, note=note, via_agent=True)
        except (ValidationError, PermissionDenied) as exc:
            return _error(exc)
        return f"Comment added to ticket #{ticket_id}."

    return [create_ticket, list_my_tickets, add_ticket_comment]
