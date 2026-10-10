"""Values every page needs for the top bar."""

from apps.agents.models import ApprovalRequest
from apps.notifications import services as notifications


def shell(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    # What the assistant costs to run is the platform owner's business, not the
    # landlord's or the tenant's, so only staff accounts are shown tokens and cost.
    context = {"nav_unread": notifications.unread_count(user), "show_costs": user.is_staff}
    if user.role == "landlord":
        waiting = ApprovalRequest.objects.for_org(user.organization).filter(
            status=ApprovalRequest.Status.PENDING
        )
        context["nav_pending_approvals"] = waiting.count()
    return context
