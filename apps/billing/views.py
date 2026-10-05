from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import Payment
from .providers import get_provider
from .webhooks import InvalidPayload, InvalidSignature, process_webhook


def fake_checkout(request, reference):
    """The pretend gateway's own payment page. In real life this is another company's site."""
    provider = get_provider("fake_gateway")
    payment = get_object_or_404(
        Payment.objects.select_related("invoice__lease__unit__property"),
        provider=provider.name,
        provider_reference=reference,
    )
    if request.method == "POST" and payment.status == Payment.Status.PENDING:
        succeeded = request.POST.get("outcome") == "success"
        body, signature = provider.build_event(payment, succeeded=succeeded)
        process_webhook(body, signature)
        if request.POST.get("duplicate"):
            # Real gateways sometimes deliver the same event twice. Ours must cope.
            process_webhook(body, signature)
        if succeeded:
            messages.success(request, "Payment received. Thank you.")
        else:
            messages.error(request, "The payment failed. You have not been charged.")
        return redirect("dashboard:invoices")
    return render(request, "billing/fake_checkout.html", {"payment": payment})


@csrf_exempt
@require_POST
def fake_gateway_webhook(request):
    """The address a gateway calls to tell us a payment's result."""
    try:
        status = process_webhook(request.body, request.headers.get("X-Signature", ""))
    except InvalidSignature:
        return JsonResponse({"error": "invalid signature"}, status=400)
    except InvalidPayload:
        return JsonResponse({"error": "invalid payload"}, status=400)
    return JsonResponse({"status": status})
