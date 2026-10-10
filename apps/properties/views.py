from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from . import invitations
from .forms import ExistingAccountForm, InviteForm, NewAccountForm
from .models import Lease, Unit

LINK_SESSION_KEY = "invitation_link"


def _require_landlord(request):
    if request.user.role != "landlord":
        raise PermissionDenied


def _remember_link(request, invitation, raw_token):
    """Keep the new link for one page view, so the landlord can copy it once."""
    request.session[LINK_SESSION_KEY] = {
        "email": invitation.email,
        "url": invitations.accept_url(raw_token),
    }


@login_required
def unit_invite(request, unit_id):
    """Landlord: invite a tenant to one vacant unit."""
    _require_landlord(request)
    unit = get_object_or_404(
        Unit.objects.for_org(request.organization).select_related("property"), pk=unit_id
    )
    if unit.leases.filter(status=Lease.Status.ACTIVE).exists():
        messages.error(request, "This unit already has a tenant.")
        return redirect("dashboard:properties")
    form = InviteForm(request.POST or None, initial={"rent_amount": unit.monthly_rent})
    if request.method == "POST" and form.is_valid():
        try:
            invitation, raw_token = invitations.create_invitation(
                landlord=request.user, unit_id=unit.id, **form.cleaned_data
            )
        except ValidationError as error:
            form.add_error(None, error)
        else:
            invitations.send_invitation_email(invitation, raw_token)
            _remember_link(request, invitation, raw_token)
            return redirect("dashboard:properties")
    return render(request, "properties/invite.html", {"unit": unit, "form": form})


@login_required
@require_POST
def invitation_cancel(request, invitation_id):
    invitation = invitations.cancel(request.user, invitation_id)
    messages.success(request, f"The invitation to {invitation.email} was cancelled.")
    return redirect("dashboard:properties")


@login_required
@require_POST
def invitation_resend(request, invitation_id):
    invitation, raw_token = invitations.resend(request.user, invitation_id)
    invitations.send_invitation_email(invitation, raw_token)
    _remember_link(request, invitation, raw_token)
    return redirect("dashboard:properties")


@never_cache
@sensitive_post_parameters("password", "password_again")
def invitation_accept(request, token):
    """Tenant: open an invitation link, set up or confirm the account, and move in."""
    invitation = invitations.find_open(token)
    if invitation is None:
        return render(request, "properties/invalid.html", status=404)

    account = invitations.account_for(invitation.email)
    signed_in = request.user.is_authenticated
    if signed_in and request.user.email.lower() != invitation.email.lower():
        # Somebody else is signed in on this browser. Never accept on their behalf.
        return render(request, "properties/other_account.html", {"invitation": invitation})

    confirming = signed_in and account is not None
    form_class = ExistingAccountForm if account is not None else NewAccountForm
    initial = {"first_name": invitation.first_name, "last_name": invitation.last_name}
    form = None if confirming else form_class(request.POST or None, initial=initial)

    if request.method == "POST" and (confirming or form.is_valid()):
        try:
            if confirming:
                tenant = invitations.accept(invitation, user=request.user)
            elif account is not None:
                tenant = authenticate(
                    request, username=account.email, password=form.cleaned_data["password"]
                )
                if tenant is None:
                    raise ValidationError("That password is not correct.")
                tenant = invitations.accept(invitation, user=tenant)
            else:
                tenant = invitations.accept(
                    invitation,
                    password=form.cleaned_data["password"],
                    first_name=form.cleaned_data["first_name"],
                    last_name=form.cleaned_data["last_name"],
                )
        except ValidationError as error:
            if form is None:
                messages.error(request, " ".join(error.messages))
                return redirect("dashboard:home")
            form.add_error(None, error)
        else:
            if not signed_in:
                login(request, tenant, backend="django.contrib.auth.backends.ModelBackend")
            messages.success(request, "Welcome to LeaseFlow. Your home is set up.")
            return redirect("dashboard:home")

    context = {"invitation": invitation, "form": form, "account": account}
    return render(request, "properties/accept.html", context)
