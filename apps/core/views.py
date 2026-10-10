import hmac

from django.conf import settings
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from apps.agents.triggers import run_overdue_check
from apps.billing import services as billing_services


@require_GET
def healthz(request):
    """Tells the host the app is up. It touches nothing, so it is always fast."""
    return HttpResponse("ok", content_type="text/plain")


JOBS = {
    # On the first of the month: one invoice per active lease.
    "monthly-invoices": lambda: {"invoices": billing_services.generate_invoices()},
    # Every morning: mark late invoices and draft reminders for the landlord to approve.
    "overdue-check": lambda: {"drafted": len(run_overdue_check(pause=3))},
}


@csrf_exempt
@require_POST
def run_job(request, name):
    """Start one scheduled job. Only a caller that knows CRON_SECRET may do this.

    On hosting that sleeps when idle there is no always-on scheduler, so a small
    cron outside the app calls this address instead.
    """
    secret = settings.CRON_SECRET
    sent = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(sent, f"Bearer {secret}"):
        raise Http404
    job = JOBS.get(name)
    if job is None:
        raise Http404
    return JsonResponse({"job": name, **job()})
