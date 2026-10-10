#!/bin/bash
# LeaseFlow v1.1b: landlords can add their own properties and units (so a new
# sign-up can reach "Invite tenant"), and the password card on the profile page
# is an accordion that opens when clicked. The top bar also scrolls with the page.
# Run from inside the LeaseFlow folder with the virtual environment active.
set -e

if [ ! -f manage.py ]; then
  echo "Run this from inside the LeaseFlow folder (the one containing manage.py)."
  exit 1
fi
if [ -z "$VIRTUAL_ENV" ]; then
  echo "The virtual environment is not active. Run this first, then run the script again:"
  echo "  source .venv/bin/activate"
  exit 1
fi
if [ ! -f apps/properties/invitations.py ]; then
  echo "Apply leaseflow_v1_1_invites_and_profiles.sh first."
  exit 1
fi

SELF_DIR="$(cd "$(dirname "$0")" && pwd)"

cat > apps/properties/forms.py << 'LEASEFLOW_EOF'
from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import Property, Unit


class DateInput(forms.DateInput):
    input_type = "date"


class InviteForm(forms.Form):
    email = forms.EmailField(label="Tenant's email")
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    start_date = forms.DateField(label="Lease starts", widget=DateInput)
    end_date = forms.DateField(label="Lease ends", widget=DateInput)
    rent_amount = forms.DecimalField(
        label="Monthly rent (Rs.)", min_value=1, max_digits=10, decimal_places=2
    )
    deposit = forms.DecimalField(
        label="Security deposit (Rs.)", min_value=0, max_digits=10, decimal_places=2, initial=0
    )
    due_day = forms.IntegerField(label="Rent due on day", min_value=1, max_value=28, initial=5)


class NewAccountForm(forms.Form):
    """For an invited tenant who has no account yet."""

    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150)
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password_again = forms.CharField(
        label="Repeat password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("password_again") != data["password"]:
            self.add_error("password_again", "The two passwords do not match.")
        return data


class ExistingAccountForm(forms.Form):
    """For an invited tenant who already has an account: they prove it with their password."""

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"})
    )


class PropertyForm(forms.ModelForm):
    class Meta:
        model = Property
        fields = ["name", "address", "city"]
        labels = {"name": "Property name"}


class UnitForm(forms.ModelForm):
    """A unit in one property. The property comes from the address, not from the form."""

    class Meta:
        model = Unit
        fields = ["unit_number", "bedrooms", "monthly_rent"]
        labels = {"monthly_rent": "Monthly rent (Rs.)"}

    def __init__(self, *args, property, **kwargs):
        super().__init__(*args, **kwargs)
        self.property = property
        self.fields["monthly_rent"].min_value = 1
        self.fields["monthly_rent"].widget.attrs["min"] = 1

    def clean_unit_number(self):
        unit_number = self.cleaned_data["unit_number"].strip()
        if self.property.units.filter(unit_number__iexact=unit_number).exists():
            raise forms.ValidationError("This property already has a unit with that number.")
        return unit_number

    def clean_monthly_rent(self):
        rent = self.cleaned_data["monthly_rent"]
        if rent <= 0:
            raise forms.ValidationError("The rent must be more than zero.")
        return rent
LEASEFLOW_EOF

cat > apps/properties/urls.py << 'LEASEFLOW_EOF'
from django.urls import path

from . import views

app_name = "properties"

urlpatterns = [
    path("properties/add/", views.property_add, name="property_add"),
    path("properties/<int:property_id>/units/add/", views.unit_add, name="unit_add"),
    path("units/<int:unit_id>/invite/", views.unit_invite, name="invite"),
    path(
        "invitations/<int:invitation_id>/cancel/", views.invitation_cancel, name="cancel"
    ),
    path(
        "invitations/<int:invitation_id>/resend/", views.invitation_resend, name="resend"
    ),
    path("invite/<str:token>/", views.invitation_accept, name="accept"),
]
LEASEFLOW_EOF

cat > apps/properties/views.py << 'LEASEFLOW_EOF'
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from . import invitations
from .forms import ExistingAccountForm, InviteForm, NewAccountForm, PropertyForm, UnitForm
from .models import Lease, Property, Unit

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
def property_add(request):
    """Landlord: add a building or house to their own organization."""
    _require_landlord(request)
    form = PropertyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        new = form.save(commit=False)
        new.organization = request.organization
        new.save()
        messages.success(request, f"{new.name} was added. Now add its first unit.")
        return redirect("properties:unit_add", property_id=new.id)
    return render(request, "properties/property_form.html", {"form": form})


@login_required
def unit_add(request, property_id):
    """Landlord: add a unit to one of their own properties. It starts vacant."""
    _require_landlord(request)
    home = get_object_or_404(Property.objects.for_org(request.organization), pk=property_id)
    form = UnitForm(request.POST or None, property=home)
    if request.method == "POST" and form.is_valid():
        unit = form.save(commit=False)
        unit.organization = request.organization
        unit.property = home
        unit.status = Unit.Status.VACANT
        unit.save()
        messages.success(
            request, f"Unit {unit.unit_number} was added. You can invite a tenant now."
        )
        return redirect("dashboard:properties")
    return render(request, "properties/unit_form.html", {"form": form, "property": home})


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
LEASEFLOW_EOF

cat > static/css/pages.css << 'LEASEFLOW_EOF'
/* Styles used by one page only: the chat, the sign-in pages, the landing page and the checkout. */
/* ---------- Chat ---------- */

.chat { max-width: 780px; margin: 0 auto; width: 100%; padding: 0; overflow: hidden; display: flex; flex-direction: column; }
.chat-header { background: var(--brand); color: var(--on-brand); padding: 22px 24px; display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px 16px; }
.chat-header p { margin: 4px 0 0; color: var(--on-brand-muted); font-size: 0.9rem; }
.chat-header .btn { background: var(--brand-deep); color: var(--accent-soft); }
.chat-header .btn:hover { background: var(--ink); box-shadow: none; }
.messages { display: flex; flex-direction: column; gap: 12px; padding: 22px 24px; min-height: 260px; }
.messages:empty { display: none; }
.question {
  align-self: flex-end; max-width: min(80%, 520px); margin: 0; padding: 11px 16px;
  background: var(--ink); border: 1px solid var(--ink-border); color: var(--on-ink); font-weight: 600;
  border-radius: 20px 20px 6px 20px; animation: rise 220ms var(--ease);
}
.answer {
  align-self: flex-start; max-width: min(90%, 600px); padding: 14px 16px;
  background: var(--surface-2); border: 1px solid var(--border); border-radius: 20px 20px 20px 6px;
  display: flex; flex-direction: column; gap: 10px; animation: rise 260ms var(--ease);
}
.answer p { margin: 0; }
.answer a { word-break: break-all; }
.answer-head { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 6px 10px; font-size: 0.78rem; font-weight: 700; color: var(--muted); }
.verified { white-space: nowrap; display: inline-flex; align-items: center; gap: 5px; padding: 3px 10px; border-radius: 999px; background: var(--gold); color: var(--gold-ink); }
.citations { display: flex; flex-direction: column; gap: 6px; }
.cite summary { padding: 8px 14px; min-height: 44px; border-radius: 16px; background: var(--brand-tint); transition: filter var(--fast) var(--ease); }
.cite summary:hover { filter: brightness(0.96); }
.cite p { margin: 8px 4px 4px; font-size: 0.87rem; animation: rise 200ms var(--ease); }
.chat-empty { padding: 28px 24px 8px; display: flex; flex-direction: column; gap: 12px; }
.messages:not(:empty) ~ .chat-empty, .chat-empty.is-hidden { display: none; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; }
.suggestions button {
  min-height: 44px; padding: 0 16px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface);
  color: var(--text); font: inherit; font-size: 0.87rem; font-weight: 600; cursor: pointer;
  transition: border-color var(--fast) var(--ease), background var(--fast) var(--ease), transform var(--fast) var(--ease);
}
.suggestions button:hover { border-color: var(--accent); background: var(--surface-2); transform: translateY(-1px); }
.chat-form { display: flex; gap: 8px; align-items: center; margin: 8px 16px 16px; padding: 6px 6px 6px 8px; border-radius: 999px; border: 1.5px solid var(--border); background: var(--surface); transition: border-color var(--fast) var(--ease), box-shadow var(--fast) var(--ease); }
.chat-form:focus-within { border-color: var(--focus); box-shadow: 0 0 0 4px color-mix(in srgb, var(--focus) 18%, transparent); }
.chat-form input[type="text"] { flex: 1; border: 0; background: transparent; min-height: 44px; box-shadow: none; }
.chat-form .btn { width: 48px; min-height: 48px; padding: 0; flex-shrink: 0; }
.chat-form.htmx-request .btn { pointer-events: none; opacity: 0.6; }
.htmx-indicator { display: none; }

/* Skeletons */
.skeleton { position: relative; overflow: hidden; background: var(--chip); border-radius: 8px; }
.skeleton::after {
  content: ""; position: absolute; inset: 0; transform: translateX(-100%);
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--surface) 70%, transparent), transparent);
  animation: shimmer 1.3s infinite;
}
.skeleton-line { height: 12px; }
.answer.is-pending { width: min(90%, 420px); }
body.gateway { background: #121110; }
body.gateway .shell { padding-top: 64px; }

/* ---------- Sign-in pages: a frosted glass card over soft grey light ---------- */

.auth-scene { position: fixed; inset: 0; z-index: -1; overflow: hidden; pointer-events: none; }
.auth-scene span { position: absolute; border-radius: 50%; will-change: transform; }
.auth-scene .glow-maroon { width: 900px; aspect-ratio: 1; left: -180px; top: -260px; background: radial-gradient(circle, var(--brand) 0, color-mix(in srgb, var(--brand) 66%, transparent) 35%, transparent 68%); filter: blur(40px); animation: drift-a 18s ease-in-out infinite alternate; }
.auth-scene .glow-gold { width: 760px; aspect-ratio: 1; right: -120px; bottom: -260px; background: radial-gradient(circle, var(--accent) 0, color-mix(in srgb, var(--accent) 66%, transparent) 35%, transparent 68%); filter: blur(50px); animation: drift-b 22s ease-in-out infinite alternate; }
.auth-scene .glow-rose { width: 520px; aspect-ratio: 1; left: 36%; top: 34%; background: radial-gradient(circle, rgba(137, 134, 129, 0.55) 0, transparent 65%); filter: blur(60px); animation: drift-b 16s ease-in-out infinite alternate-reverse; }
.auth-scene .glow-sun { width: 420px; aspect-ratio: 1; right: 160px; top: -120px; background: radial-gradient(circle, var(--accent-soft) 0, transparent 65%); filter: blur(40px); animation: drift-a 20s ease-in-out infinite alternate-reverse; }
.auth-scene .grain { position: absolute; inset: 0; opacity: 0.35; mix-blend-mode: multiply; }
:root[data-theme="dark"] .auth-scene .glow-maroon { opacity: 0.8; }
:root[data-theme="dark"] .auth-scene .glow-gold { opacity: 0.55; }
:root[data-theme="dark"] .auth-scene .glow-sun { opacity: 0.3; }
:root[data-theme="dark"] .auth-scene .grain { opacity: 0.12; mix-blend-mode: screen; }
:root[data-theme="dark"] .glass .btn { background: #121110; color: #ffffff; border: 1px solid color-mix(in srgb, var(--gold) 45%, transparent); box-shadow: 0 10px 24px rgba(0, 0, 0, 0.5); }
:root[data-theme="dark"] .glass .btn:hover { background: #000000; border-color: var(--gold); }
:root[data-theme="dark"] .glass .btn .btn-arrow-dot { background: var(--gold); color: #121110; }
@keyframes drift-a { to { transform: translate(60px, 40px) scale(1.08); } }
@keyframes drift-b { to { transform: translate(-50px, -36px) scale(1.1); } }
@media (prefers-reduced-motion: reduce) { .auth-scene span { animation: none; } }

.glass {
  position: relative; width: 100%; max-width: 440px; margin: clamp(16px, 6vh, 64px) auto 0; padding: 44px 40px 36px;
  display: flex; flex-direction: column; gap: 22px;
  background: color-mix(in srgb, var(--surface) 52%, transparent);
  -webkit-backdrop-filter: blur(26px) saturate(150%); backdrop-filter: blur(26px) saturate(150%);
  border: 1px solid color-mix(in srgb, #ffffff 55%, transparent);
  border-radius: 36px;
  box-shadow: 0 30px 80px rgba(40, 38, 35, 0.22), inset 0 1px 0 color-mix(in srgb, #ffffff 60%, transparent);
  animation: glass-in 620ms var(--ease) both;
}
:root[data-theme="dark"] .glass { background: color-mix(in srgb, var(--surface) 46%, transparent); border-color: color-mix(in srgb, #ffffff 16%, transparent); box-shadow: 0 30px 80px rgba(0, 0, 0, 0.55), inset 0 1px 0 color-mix(in srgb, #ffffff 14%, transparent); }
.glass h1 { font-size: 1.9rem; letter-spacing: 0.06em; text-transform: uppercase; }
.glass h1::after { content: ""; display: block; width: 44px; height: 4px; border-radius: 2px; background: var(--gold); margin-top: 10px; }
.glass .muted { margin: 6px 0 0; }
.glass form { display: flex; flex-direction: column; gap: 14px; margin: 0; }
.glass .field { margin: 0; position: relative; }
.glass input[type="text"], .glass input[type="email"], .glass input[type="password"] {
  min-height: 52px; padding: 0 18px; border-radius: 16px;
  background: color-mix(in srgb, var(--surface) 62%, transparent);
  border: 1px solid color-mix(in srgb, var(--text) 14%, transparent);
  box-shadow: inset 0 1px 2px rgba(40, 38, 35, 0.06);
}
.glass input:hover { border-color: var(--accent); }
.glass input:focus { background: var(--surface); border-color: var(--focus); }
.glass .btn { width: 100%; min-height: 52px; margin-top: 6px; }
.glass .reveal-password { top: 8px; bottom: auto; }
.glass-foot { text-align: center; font-size: 0.92rem; }
.glass > * { animation: fade-up 520ms var(--ease) both; }
.glass > *:nth-child(2) { animation-delay: 120ms; }
.glass > *:nth-child(3) { animation-delay: 200ms; }
@keyframes glass-in { from { opacity: 0; transform: translateY(18px) scale(0.97); } to { opacity: 1; transform: none; } }

/* ---------- Splash: plays once when the site is first opened in a tab ----------
   A light background with the logo in dark grey and a glowing gold shadow under it. */

.splash {
  --splash-ink: var(--brand);
  --splash-glow: var(--gold);
  position: fixed; inset: 0; z-index: 100; display: flex; align-items: center; justify-content: center;
  background: var(--bg-2) linear-gradient(165deg, var(--bg-1) 0%, var(--bg-2) 55%, var(--bg-3) 100%);
  color: var(--splash-ink);
  animation: splash-out 560ms 2500ms var(--ease) forwards;
}
:root[data-theme="dark"] .splash { --splash-ink: var(--accent-soft); }
.splash-seen .splash { display: none; }
.splash-inner { display: flex; flex-direction: column; align-items: center; animation: splash-lift 520ms 2400ms var(--ease) forwards; }
.splash-mark { width: 190px; height: auto; display: block; overflow: visible; filter: drop-shadow(2px 3px 0 var(--splash-glow)) drop-shadow(0 0 14px var(--gold-glow)); animation: splash-glow 1800ms 900ms ease-in-out infinite alternate; }
@keyframes splash-glow { from { filter: drop-shadow(2px 3px 0 var(--splash-glow)) drop-shadow(0 0 8px var(--gold-glow)); } to { filter: drop-shadow(2px 3px 0 var(--splash-glow)) drop-shadow(0 0 26px var(--gold)); } }
@media (prefers-reduced-motion: reduce) { .splash-mark { animation: none; } }
.splash-mark path { fill: none; stroke: var(--splash-ink); stroke-width: 3.2; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 240; stroke-dashoffset: 240; animation: draw 700ms var(--ease) forwards; }
.splash-mark .mark-roof { animation-delay: 150ms; }
.splash-mark .mark-roof-2 { animation-delay: 380ms; }
.splash-mark .mark-line:nth-of-type(3) { animation-delay: 620ms; }
.splash-mark .mark-line:nth-of-type(4) { animation-delay: 720ms; }
.splash-mark .mark-line:nth-of-type(5) { animation-delay: 820ms; }
.splash-mark .mark-line:nth-of-type(6) { animation-delay: 920ms; }
.splash-mark .mark-line:nth-of-type(7) { animation-delay: 1020ms; }
.splash-word {
  display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 0.5em; margin-top: -34px;
  font-family: "Cinzel", "Cormorant Garamond", Georgia, serif; font-weight: 500;
  font-size: clamp(2rem, 1.2rem + 4vw, 3.4rem); letter-spacing: 0.08em; line-height: 1;
  text-shadow: 2px 3px 0 var(--splash-glow), 0 10px 18px color-mix(in srgb, var(--splash-glow) 60%, transparent);
}
.splash-word span { opacity: 0; animation: splash-left 620ms 1150ms var(--ease) forwards; }
.splash-word span:first-child { text-align: right; }
.splash-word span:last-child { text-align: left; animation-name: splash-right; }
.splash-word i { width: 3px; height: 1.5em; margin-top: -0.2em; border-radius: 2px; background: currentColor; box-shadow: 2px 3px 0 var(--splash-glow); transform-origin: top; transform: scaleY(0); animation: splash-drop 420ms 1000ms var(--ease) forwards; }
.splash-tag {
  margin-top: 18px; font-size: clamp(0.7rem, 0.55rem + 0.7vw, 0.95rem); font-weight: 600; text-transform: uppercase;
  letter-spacing: 0.1em; opacity: 0; text-shadow: 1px 2px 0 color-mix(in srgb, var(--splash-glow) 70%, transparent);
  animation: splash-tag 720ms 1500ms var(--ease) forwards;
}
@keyframes splash-left { from { opacity: 0; transform: translateX(-22px); } to { opacity: 1; transform: none; } }
@keyframes splash-right { from { opacity: 0; transform: translateX(22px); } to { opacity: 1; transform: none; } }
@keyframes splash-drop { to { transform: scaleY(1); } }
@keyframes splash-tag { from { opacity: 0; letter-spacing: 0.1em; } to { opacity: 1; letter-spacing: 0.42em; } }
@keyframes splash-lift { to { transform: translateY(-14px) scale(0.97); opacity: 0; } }
@keyframes splash-out { to { opacity: 0; visibility: hidden; } }
.glass .eyebrow { color: var(--muted); margin-bottom: 6px; }

/* Landlord or tenant: a small switch at the top of the login card. */
.portal-switch { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; padding: 4px; border-radius: 999px; background: color-mix(in srgb, var(--text) 8%, transparent); border: 1px solid color-mix(in srgb, var(--text) 10%, transparent); }
.portal-switch a { display: flex; align-items: center; justify-content: center; gap: 8px; min-height: 44px; border-radius: 999px; font-weight: 700; font-size: 0.92rem; color: var(--muted); transition: background var(--fast) var(--ease), color var(--fast) var(--ease), box-shadow var(--fast) var(--ease); }
.portal-switch a:hover { color: var(--text); text-decoration: none; background: color-mix(in srgb, var(--surface) 55%, transparent); }
.portal-switch a[aria-current="true"] { background: var(--ink); color: var(--on-ink); box-shadow: var(--shadow-sm); }
:root[data-theme="dark"] .portal-switch a[aria-current="true"] { background: var(--accent-soft); color: var(--accent-ink); }
body.is-auth .topbar { background: transparent; border-color: transparent; box-shadow: none; backdrop-filter: none; }
.portal-switch a[aria-current="true"] .icon { color: var(--gold); }
:root[data-theme="dark"] .portal-switch a[aria-current="true"] .icon { color: inherit; }
body.is-auth .topbar { position: static; pointer-events: none; }
body.is-auth .topbar a, body.is-auth .topbar button { pointer-events: auto; }

/* ---------- Lease page viewer: the page behind a citation ---------- */
.cite-open { display: inline-flex; align-items: center; gap: 7px; margin: 4px 4px 6px; min-height: 40px; padding: 0 14px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); font-size: 0.85rem; font-weight: 700; color: var(--text); transition: border-color var(--fast) var(--ease), transform var(--fast) var(--ease), box-shadow var(--fast) var(--ease); }
.cite-open:hover { text-decoration: none; border-color: var(--gold); transform: translateY(-1px); box-shadow: var(--shadow-sm); }
.cite-open .icon-arrow { transition: transform var(--fast) var(--ease); }
.cite-open:hover .icon-arrow { transform: translateX(3px); }
.back-link { display: inline-flex; align-items: center; gap: 6px; font-size: 0.87rem; font-weight: 700; color: var(--muted); margin-bottom: 6px; }
.back-link:hover { color: var(--text); text-decoration: none; }
.page-head { display: flex; flex-wrap: wrap; align-items: flex-end; justify-content: space-between; gap: 16px; }
.page-head .muted { margin: 4px 0 0; }
.page-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.lease-view { display: grid; grid-template-columns: minmax(0, 1fr); gap: 20px; align-items: start; }
.lease-view.has-pdf { grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
.lease-page { position: relative; padding: 44px 40px 40px; animation: fade-up 420ms var(--ease) both; }
.lease-page-label { position: absolute; top: 14px; right: 18px; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.12em; text-transform: uppercase; color: var(--muted); }
.lease-text { white-space: pre-line; font-family: Georgia, "Times New Roman", serif; font-size: 1.02rem; line-height: 1.75; }
.lease-text mark { background: color-mix(in srgb, var(--gold) 20%, transparent); color: inherit; border-radius: 3px; padding: 2px 0; scroll-margin-top: 160px; }
.lease-text mark.focus, .lease-text mark#cited:not(.focus) { background: color-mix(in srgb, var(--gold) 58%, transparent); padding: 2px 2px; box-shadow: 0 0 0 3px color-mix(in srgb, var(--gold) 24%, transparent); animation: cited 1400ms var(--ease) 300ms both; }
@keyframes cited { 0% { background: var(--gold); box-shadow: 0 0 0 9px var(--gold-glow); } 100% { background: color-mix(in srgb, var(--gold) 58%, transparent); box-shadow: 0 0 0 3px color-mix(in srgb, var(--gold) 24%, transparent); } }
.lease-key { grid-column: 1 / -1; margin: 0; display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 0.82rem; color: var(--muted); }
.lease-key span { display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; }
.lease-key i { width: 22px; height: 12px; border-radius: 3px; }
.lease-key .key-focus { background: color-mix(in srgb, var(--gold) 58%, transparent); }
.lease-key .key-cited { background: color-mix(in srgb, var(--gold) 20%, transparent); }
@media (prefers-reduced-motion: reduce) { .lease-text mark.focus, .lease-text mark#cited { animation: none; } }

/* ---------- Tenant invitations and profile ---------- */
.invite-link { display: flex; flex-direction: column; gap: 14px; border-color: var(--gold); animation: fade-up 420ms var(--ease) both; }
.invite-link h2 { display: flex; align-items: center; gap: 8px; }
.invite-link h2 .icon { color: var(--good-dot); }
.invite-link .muted { margin: 4px 0 0; }
.copy-row { display: flex; gap: 8px; }
.copy-row input { flex: 1; min-width: 0; font-size: 0.87rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.row-actions { white-space: nowrap; text-align: right; }
.row-actions form { display: inline-block; margin: 0; }
.row-actions .btn { vertical-align: middle; }
.form-2 { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.form-2 .wide, .form-2 > .errorlist { grid-column: 1 / -1; }
.steps-list { margin: 0; padding-left: 20px; display: flex; flex-direction: column; gap: 12px; color: var(--on-ink-muted); }
.steps-list li::marker { color: var(--gold); font-weight: 800; }
.invite-facts { margin: 0; padding: 4px 16px; border-radius: 16px; background: color-mix(in srgb, var(--surface) 55%, transparent); border: 1px solid color-mix(in srgb, var(--text) 10%, transparent); }
.narrow { max-width: 560px; margin-inline: auto; }
.profile-head { justify-content: flex-start; align-items: center; gap: 16px; }
.avatar-large { width: 64px; height: 64px; font-size: 1.3rem; flex-shrink: 0; }
.hint { font-size: 0.8rem; color: var(--muted); }
.helptext { font-size: 0.8rem; color: var(--muted); }
.helptext ul { margin: 4px 0 0; padding-left: 18px; }
.menu-actions { display: flex; gap: 8px; align-items: center; }
.menu-actions form { margin: 0; }
input:disabled { opacity: 0.65; cursor: not-allowed; }
.card-ink .facts dt { color: var(--on-ink-muted); }
.card-ink .facts > div { border-color: var(--ink-line); }
.card-ink .facts dd { color: var(--on-ink); }

.topbar { position: relative; top: auto; }

/* An accordion card: closed until its heading is clicked (the password card on the profile). */
.accordion { padding: 0; overflow: hidden; }
.accordion > summary { list-style: none; cursor: pointer; display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 20px 24px; border-radius: inherit; transition: background var(--fast) var(--ease); }
.accordion > summary::-webkit-details-marker { display: none; }
.accordion > summary:hover { background: var(--surface-2); }
.accordion > summary > span:first-child { display: flex; flex-direction: column; gap: 2px; }
.accordion > summary strong { font-size: 1.15rem; letter-spacing: -0.01em; }
.accordion > summary .muted { font-size: 0.87rem; }
.accordion-mark { width: 38px; height: 38px; flex-shrink: 0; border-radius: 50%; border: 1px solid var(--border); display: grid; place-items: center; transition: transform 260ms var(--ease), background var(--fast) var(--ease), border-color var(--fast) var(--ease); }
.accordion > summary:hover .accordion-mark { border-color: var(--gold); }
.accordion[open] .accordion-mark { transform: rotate(45deg); background: var(--ink); color: var(--gold); border-color: var(--ink); }
.accordion > .form { padding: 4px 24px 24px; }
details.accordion::details-content { block-size: 0; overflow: clip; transition: block-size 300ms var(--ease), content-visibility 300ms allow-discrete; }
details.accordion[open]::details-content { block-size: auto; }
.empty p { margin: 0 0 14px; }

LEASEFLOW_EOF

cat > templates/accounts/profile.html << 'LEASEFLOW_EOF'
{% extends "base.html" %}
{% load ui %}
{% block title %}Profile · LeaseFlow{% endblock %}
{% block content %}
<div class="page-head profile-head">
  <span class="avatar avatar-large">{{ user|initials }}</span>
  <div>
    <h1>{{ user.get_full_name|default:user.email }}</h1>
    <p class="muted">{{ user.get_role_display }} · {{ user.email }}{% if request.organization %} · {{ request.organization.name }}{% endif %}</p>
  </div>
</div>
<div class="grid grid-even">
  <div class="stack">
    <div class="card section">
      <div class="card-head"><h2>Your details</h2></div>
      <form method="post" class="form" novalidate>
        {% csrf_token %}
        <input type="hidden" name="section" value="details">
        <div>
          <label for="profile-email">Email</label>
          <input id="profile-email" type="email" value="{{ user.email }}" disabled>
          <span class="hint">Your email is your login and cannot be changed here.</span>
        </div>
        {{ forms.details.as_div }}
        <button class="btn" type="submit">Save details</button>
      </form>
    </div>
    {% if is_landlord %}
    <div class="card section">
      <div class="card-head"><h2>Your business</h2><span class="muted">Shown to your tenants</span></div>
      <form method="post" class="form" novalidate>
        {% csrf_token %}
        <input type="hidden" name="section" value="business">
        {{ forms.business.as_div }}
        <button class="btn" type="submit">Save business</button>
      </form>
    </div>
    {% endif %}
  </div>
  <div class="stack">
    {% if not is_landlord %}
    <div class="card card-ink section">
      <div class="card-head"><h2>Your tenancy</h2></div>
      {% if lease %}
        <dl class="facts">
          <div><dt>Home</dt><dd>{{ lease.unit.property.name }}, unit {{ lease.unit.unit_number }}</dd></div>
          <div><dt>Address</dt><dd>{{ lease.unit.property.address }}, {{ lease.unit.property.city }}</dd></div>
          <div><dt>Monthly rent</dt><dd>Rs. {{ lease.rent_amount|floatformat:"0g" }}, due on day {{ lease.due_day }}</dd></div>
          <div><dt>Lease runs</dt><dd>{{ lease.start_date|date:"j M Y" }} to {{ lease.end_date|date:"j M Y" }}</dd></div>
          {% for landlord in landlords %}
            <div><dt>Landlord</dt><dd>{{ landlord.get_full_name|default:request.organization.name }}<br>{{ landlord.email }}{% if landlord.phone %} · {{ landlord.phone }}{% endif %}</dd></div>
          {% endfor %}
        </dl>
        <p class="hero-note">Only your landlord can change these. Ask them if something is wrong.</p>
      {% else %}
        <p class="hero-note">You don't have an active lease on file.</p>
      {% endif %}
    </div>
    {% endif %}
    <details class="card section accordion"{% if forms.password.errors %} open{% endif %}>
      <summary>
        <span><strong>Password</strong><span class="muted">Change the password you log in with</span></span>
        <span class="accordion-mark">{% icon "plus" 18 %}</span>
      </summary>
      <form method="post" class="form" novalidate>
        {% csrf_token %}
        <input type="hidden" name="section" value="password">
        {{ forms.password.as_div }}
        <button class="btn" type="submit">Change password</button>
      </form>
    </details>
  </div>
</div>
{% endblock %}
LEASEFLOW_EOF

cat > templates/dashboard/properties.html << 'LEASEFLOW_EOF'
{% extends "base.html" %}
{% load ui %}
{% block title %}Properties · LeaseFlow{% endblock %}
{% block content %}
<div class="page-head"><h1>Properties</h1><a class="btn" href="{% url 'properties:property_add' %}">{% icon "plus" 16 %}Add property</a></div>
{% if new_link %}
  <div class="card invite-link" role="status">
    <div>
      <h2>{% icon "check-circle" 20 %}Invitation sent to {{ new_link.email }}</h2>
      <p class="muted">We emailed them this link. You can also copy it and send it yourself. It works once, expires in 7 days, and will not be shown again.</p>
    </div>
    <div class="copy-row">
      <label class="sr-only" for="invite-url">Invitation link</label>
      <input id="invite-url" type="text" readonly value="{{ new_link.url }}">
      <button class="btn btn-gold" type="button" data-copy="#invite-url">Copy link</button>
    </div>
  </div>
{% endif %}
{% for row in rows %}
  <div class="card section">
    <div class="card-head">
      <div>
        <h2>{{ row.property.name }}</h2>
        <span class="muted">{{ row.property.address }}, {{ row.property.city }}</span>
      </div>
      <div class="actions">
        <span class="badge">{{ row.units|length }} unit{{ row.units|length|pluralize }}</span>
        <a class="btn btn-ghost btn-small" href="{% url 'properties:unit_add' row.property.id %}">{% icon "plus" 16 %}Add unit</a>
      </div>
    </div>
    <div class="table-wrap">
    <table class="table stackable">
      <thead><tr><th>Unit</th><th>Status</th><th>Monthly rent</th><th>Tenant</th><th>Lease ends</th><th><span class="sr-only">Actions</span></th></tr></thead>
      <tbody>
        {% for item in row.units %}
          <tr>
            <td data-label="Unit" class="strong">{{ item.unit.unit_number }}</td>
            <td data-label="Status"><span class="badge status-{{ item.unit.status }}">{{ item.unit.get_status_display }}</span></td>
            <td data-label="Monthly rent">Rs. {{ item.unit.monthly_rent|floatformat:"0g" }}</td>
            <td data-label="Tenant">
              {% if item.lease %}{{ item.lease.tenant.get_full_name|default:item.lease.tenant.email }}
              {% elif item.invitation %}<span class="badge status-pending">Invited</span> {{ item.invitation.email }}
              {% else %}<span class="muted">None</span>{% endif %}
            </td>
            <td data-label="Lease ends">
              {% if item.lease %}{{ item.lease.end_date|date:"j M Y" }}
              {% elif item.invitation %}<span class="muted">{% if item.invitation.is_expired %}Invitation expired{% else %}Invitation expires {{ item.invitation.expires_at|date:"j M" }}{% endif %}</span>
              {% else %}<span class="muted">-</span>{% endif %}
            </td>
            {% if item.lease %}<td class="row-actions is-empty"></td>{% else %}
            <td class="row-actions">
              {% if item.invitation %}
                <form method="post" action="{% url 'properties:resend' item.invitation.id %}">{% csrf_token %}<button class="btn btn-ghost btn-small" type="submit">New link</button></form>
                <form method="post" action="{% url 'properties:cancel' item.invitation.id %}">{% csrf_token %}<button class="btn btn-quiet btn-small" type="submit">Cancel</button></form>
              {% else %}
                <a class="btn btn-small" href="{% url 'properties:invite' item.unit.id %}">{% icon "plus" 16 %}Invite tenant</a>
              {% endif %}
            </td>
            {% endif %}
          </tr>
        {% empty %}
          <tr><td colspan="6" class="muted">No units yet. Use "Add unit" to create the first one.</td></tr>
        {% endfor %}
      </tbody>
    </table>
    </div>
  </div>
{% empty %}
  <div class="card empty">{% icon "building" 28 %}<p>No properties yet. Add your first one to start inviting tenants.</p><a class="btn" href="{% url 'properties:property_add' %}">{% icon "plus" 16 %}Add property</a></div>
{% endfor %}
{% endblock %}
LEASEFLOW_EOF

cat > templates/properties/property_form.html << 'LEASEFLOW_EOF'
{% extends "base.html" %}
{% load ui %}
{% block title %}Add a property · LeaseFlow{% endblock %}
{% block content %}
<div>
  <a class="back" href="{% url 'dashboard:properties' %}">{% icon "back" 16 %}Properties</a>
  <div class="page-head"><h1>Add a property</h1></div>
</div>
<div class="grid grid-2">
  <div class="card section">
    <div class="card-head"><h2>Property details</h2></div>
    <form method="post" class="form" novalidate>
      {% csrf_token %}
      {{ form.as_div }}
      <button class="btn btn-arrow" type="submit">Save property<span class="btn-arrow-dot">{% icon "arrow" 16 %}</span></button>
    </form>
  </div>
  <div class="card card-ink section">
    <div class="card-head"><h2>Good to know</h2></div>
    <ol class="steps-list">
      <li>A property is a building or house you rent out.</li>
      <li>Next you add its units, such as "A1" or "Ground floor".</li>
      <li>Then you invite a tenant to each vacant unit.</li>
    </ol>
  </div>
</div>
{% endblock %}
LEASEFLOW_EOF

cat > templates/properties/unit_form.html << 'LEASEFLOW_EOF'
{% extends "base.html" %}
{% load ui %}
{% block title %}Add a unit · LeaseFlow{% endblock %}
{% block content %}
<div>
  <a class="back" href="{% url 'dashboard:properties' %}">{% icon "back" 16 %}Properties</a>
  <div class="page-head"><h1>Add a unit</h1></div>
</div>
<div class="grid grid-2">
  <div class="card section">
    <div class="card-head"><h2>{{ property.name }}</h2><span class="muted">{{ property.address }}, {{ property.city }}</span></div>
    <form method="post" class="form" novalidate>
      {% csrf_token %}
      {{ form.as_div }}
      <button class="btn btn-arrow" type="submit">Save unit<span class="btn-arrow-dot">{% icon "arrow" 16 %}</span></button>
    </form>
  </div>
  <div class="card card-ink section">
    <div class="card-head"><h2>Good to know</h2></div>
    <ol class="steps-list">
      <li>The unit starts as vacant.</li>
      <li>Use "Invite tenant" on the Properties page to offer it to someone.</li>
      <li>The rent here is the default for new leases; you can change it per invitation.</li>
    </ol>
  </div>
</div>
{% endblock %}
LEASEFLOW_EOF

cat > tests/test_property_setup.py << 'LEASEFLOW_EOF'
"""A landlord sets up their own properties and units, so a new sign-up is not a dead end."""

import pytest

from apps.accounts.models import User
from apps.properties.models import Property, Unit

PASSWORD = "demo12345"
PROPERTY = {"name": "Model Town House", "address": "5 Park Road", "city": "Lahore"}
UNIT = {"unit_number": "G1", "bedrooms": "2", "monthly_rent": "48000"}


def alpha():
    return User.objects.get(email="landlord@alpha.test").organization


@pytest.mark.django_db
def test_a_landlord_adds_a_property_then_a_unit_and_can_invite(client):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    response = client.post("/properties/add/", PROPERTY)
    home = Property.objects.get(name="Model Town House")
    assert home.organization == alpha()
    assert response.url == f"/properties/{home.id}/units/add/"

    client.post(f"/properties/{home.id}/units/add/", UNIT)
    unit = Unit.objects.get(property=home)
    page = client.get("/properties/").content.decode()

    assert unit.organization == alpha() and unit.status == "vacant" and unit.monthly_rent == 48000
    assert "Model Town House" in page
    assert f"/units/{unit.id}/invite/" in page


@pytest.mark.django_db
def test_a_brand_new_landlord_starts_with_a_way_forward(client):
    client.post(
        "/signup/",
        {
            "organization_name": "Fresh Homes",
            "email": "new@fresh.test",
            "password": "a-long-pass-42",
        },
    )

    page = client.get("/properties/").content.decode()

    assert "No properties yet" in page and "/properties/add/" in page


@pytest.mark.django_db
def test_tenants_cannot_add_properties_or_units(client):
    home = Property.objects.for_org(alpha()).first()
    client.login(email="ali@alpha.test", password=PASSWORD)

    assert client.post("/properties/add/", PROPERTY).status_code == 403
    assert client.post(f"/properties/{home.id}/units/add/", UNIT).status_code == 403
    assert not Property.objects.filter(name="Model Town House").exists()


@pytest.mark.django_db
def test_a_landlord_cannot_add_a_unit_to_another_organizations_property(client):
    other = Property.objects.exclude(organization=alpha()).first()
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert client.post(f"/properties/{other.id}/units/add/", UNIT).status_code == 404
    assert not Unit.objects.filter(property=other, unit_number="G1").exists()


@pytest.mark.django_db
def test_the_organization_and_status_cannot_be_set_from_the_form(client):
    other_org = Property.objects.exclude(organization=alpha()).first().organization
    home = Property.objects.for_org(alpha()).first()
    client.login(email="landlord@alpha.test", password=PASSWORD)

    client.post("/properties/add/", {**PROPERTY, "organization": other_org.id})
    client.post(
        f"/properties/{home.id}/units/add/",
        {**UNIT, "status": "occupied", "organization": other_org.id, "property": 999},
    )

    assert Property.objects.get(name="Model Town House").organization == alpha()
    unit = Unit.objects.get(unit_number="G1")
    assert unit.property == home and unit.organization == alpha() and unit.status == "vacant"


@pytest.mark.django_db
def test_duplicate_unit_numbers_and_bad_rent_are_refused(client):
    home = Property.objects.for_org(alpha()).first()
    taken = home.units.first().unit_number
    client.login(email="landlord@alpha.test", password=PASSWORD)
    before = home.units.count()

    duplicate = client.post(
        f"/properties/{home.id}/units/add/", {**UNIT, "unit_number": taken.lower()}
    )
    free = client.post(f"/properties/{home.id}/units/add/", {**UNIT, "monthly_rent": "0"})

    assert "already has a unit" in duplicate.content.decode()
    assert free.status_code == 200
    assert home.units.count() == before


@pytest.mark.django_db
def test_the_password_card_is_closed_until_opened_or_wrong(client):
    client.login(email="ali@alpha.test", password=PASSWORD)

    closed = client.get("/profile/").content.decode()
    wrong = client.post(
        "/profile/",
        {"section": "password", "old_password": "nope", "new_password1": "x", "new_password2": "y"},
    ).content.decode()

    assert '<details class="card section accordion">' in closed
    assert '<details class="card section accordion" open>' in wrong
LEASEFLOW_EOF

ruff check .
# Only the tests for what changed, so this takes a minute, not a quarter of an hour.
pytest tests/test_property_setup.py tests/test_profile.py tests/test_invitations.py

# If this script was saved inside the project, delete it now that it has finished.
if [ "$SELF_DIR" = "$(pwd)" ]; then
  rm -f "$0"
fi

echo ""
echo "Done. Start the server with: python manage.py runserver"
echo "Then hard refresh the browser (Cmd+Shift+R)."