"""Values every page needs for the top bar."""

from apps.agents.models import ApprovalRequest
from apps.notifications import services as notifications


def shell(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    context = {"nav_unread": notifications.unread_count(user)}
    if user.role == "landlord":
        waiting = ApprovalRequest.objects.for_org(user.organization).filter(
            status=ApprovalRequest.Status.PENDING
        )
        context["nav_pending_approvals"] = waiting.count()
    return context
