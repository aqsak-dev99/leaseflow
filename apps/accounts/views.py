from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters

from apps.properties.models import Lease

from .forms import BusinessForm, ProfileForm, SignupForm
from .models import User
from .services import signup_landlord

# The login page has a landlord and a tenant portal. The portal only changes the
# wording of the page: what a person can see is always decided by the role on their
# account, never by the card they clicked.
PORTALS = {
    "landlord": {
        "title": "Landlord login",
        "note": "Manage your properties, tenants and rent.",
    },
    "tenant": {
        "title": "Tenant login",
        "note": "Your lease, rent, repairs and assistant.",
    },
}


class PortalLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"

    def portal(self):
        name = self.request.POST.get("portal") or self.request.GET.get("portal") or ""
        return name if name in PORTALS else "landlord"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        portal = self.portal()
        context["portal"] = portal
        context["portal_info"] = PORTALS[portal]
        context["demo_mode"] = settings.DEMO_MODE
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        portal = self.portal()
        role = self.request.user.role
        if portal != role:
            messages.info(
                self.request, f"This is a {role} account, so you are in the {role} portal."
            )
        return response


def signup(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = signup_landlord(**form.cleaned_data)
        login(request, user)
        return redirect("dashboard:home")
    return render(request, "accounts/signup.html", {"form": form})


def is_demo_account(user):
    """True for the sample accounts on a public demo, which every visitor shares."""
    domain = user.email.rsplit("@", 1)[-1].lower()
    return settings.DEMO_MODE and domain in settings.DEMO_EMAIL_DOMAINS


SAVED = {
    "details": "Your details were updated.",
    "password": "Your password was changed.",
    "business": "Your business name was updated.",
}


@login_required
@sensitive_post_parameters("old_password", "new_password1", "new_password2")
def profile(request):
    """A person's own details. There is no user id in the address: it is always `request.user`."""
    user = request.user
    is_landlord = user.role == User.Role.LANDLORD
    section = request.POST.get("section", "")

    def bound(name):
        return request.POST if request.method == "POST" and section == name else None

    forms = {"details": ProfileForm(bound("details"), instance=user)}
    forms["password"] = PasswordChangeForm(user, bound("password"))
    forms["password"].fields["old_password"].widget.attrs.pop("autofocus", None)
    if is_landlord:
        forms["business"] = BusinessForm(bound("business"), instance=user.organization)

    locked = is_demo_account(user)
    if request.method == "POST" and locked and section in ("password", "business"):
        messages.error(request, "This is a shared demo account, so that cannot be changed here.")
        return redirect("accounts:profile")

    form = forms.get(section)
    if request.method == "POST" and form is not None and form.is_valid():
        form.save()
        if section == "password":
            # Keep this browser signed in; every other session is signed out.
            update_session_auth_hash(request, form.user)
        messages.success(request, SAVED[section])
        return redirect("accounts:profile")

    lease = None
    if not is_landlord:
        lease = (
            Lease.objects.for_org(user.organization)
            .filter(tenant=user, status=Lease.Status.ACTIVE)
            .select_related("unit", "unit__property")
            .first()
        )
    context = {
        "forms": forms,
        "is_landlord": is_landlord,
        "locked": locked,
        "lease": lease,
        "landlords": User.objects.filter(
            organization=user.organization, role=User.Role.LANDLORD
        ),
    }
    return render(request, "accounts/profile.html", context)
