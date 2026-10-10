"""Inviting a tenant to a unit, and accepting that invitation.

The rules, all enforced here and not in the views:

- Only a landlord can invite, and only to a vacant unit in their own organization.
- The invitation link holds a random token. Only its SHA-256 hash is stored.
- A link works once, for seven days, and can be cancelled or replaced by the landlord.
- Accepting creates the tenant account (or reuses the tenant's existing one), the
  lease, and marks the unit occupied, all in one transaction.
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications import services as notifications
from apps.notifications.models import Notification

from .models import Lease, TenantInvitation, Unit

INVITE_DAYS = 7
CANNOT_INVITE = "This email address cannot be invited. Ask the tenant for a different one."


def hash_token(raw_token):
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _new_token():
    raw_token = secrets.token_urlsafe(32)
    return raw_token, hash_token(raw_token)


def _require_landlord(user):
    if user.role != User.Role.LANDLORD:
        raise PermissionDenied


def accept_url(raw_token):
    """The full link a tenant opens to accept."""
    return settings.SITE_URL.rstrip("/") + reverse("properties:accept", args=[raw_token])


def account_for(email):
    """The existing account with this email, if there is one."""
    return User.objects.filter(email__iexact=email).first()


def _check_email(organization, email):
    """A new address is fine. An existing one must be a tenant here with no active lease."""
    account = account_for(email)
    if account is None:
        return
    if account.role != User.Role.TENANT or account.organization_id != organization.id:
        raise ValidationError(CANNOT_INVITE)
    if Lease.objects.filter(tenant=account, status=Lease.Status.ACTIVE).exists():
        raise ValidationError("This tenant already has an active lease.")


@transaction.atomic
def create_invitation(
    *, landlord, unit_id, email, start_date, end_date, rent_amount, deposit=0, due_day=1,
    first_name="", last_name="",
):
    """Invite a tenant to a vacant unit. Returns (invitation, raw_token)."""
    _require_landlord(landlord)
    unit = (
        Unit.objects.for_org(landlord.organization)
        .select_for_update()
        .filter(pk=unit_id)
        .first()
    )
    if unit is None:
        raise PermissionDenied
    if unit.leases.filter(status=Lease.Status.ACTIVE).exists():
        raise ValidationError("This unit already has a tenant.")
    if end_date <= start_date:
        raise ValidationError("The lease must end after it starts.")
    if rent_amount <= 0:
        raise ValidationError("The rent must be more than zero.")
    if not 1 <= due_day <= 28:
        raise ValidationError("The rent due day must be between 1 and 28.")
    email = email.strip().lower()
    _check_email(landlord.organization, email)

    # A newer invitation replaces an older one that is still waiting.
    unit.invitations.filter(status=TenantInvitation.Status.PENDING).update(
        status=TenantInvitation.Status.CANCELLED
    )
    raw_token, token_hash = _new_token()
    invitation = TenantInvitation.objects.create(
        organization=landlord.organization,
        unit=unit,
        email=email,
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        start_date=start_date,
        end_date=end_date,
        rent_amount=rent_amount,
        deposit=deposit,
        due_day=due_day,
        token_hash=token_hash,
        invited_by=landlord,
        expires_at=timezone.now() + timedelta(days=INVITE_DAYS),
    )
    return invitation, raw_token


def send_invitation_email(invitation, raw_token):
    unit = invitation.unit
    body = (
        f"Hello{' ' + invitation.first_name if invitation.first_name else ''},\n\n"
        f"{invitation.organization.name} has invited you to LeaseFlow for unit "
        f"{unit.unit_number} at {unit.property.name}.\n\n"
        f"Open this link to set up your account:\n{accept_url(raw_token)}\n\n"
        f"The link works once and expires in {INVITE_DAYS} days. If you were not "
        "expecting this, you can ignore this email."
    )
    send_mail(
        f"Your invitation from {invitation.organization.name}",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [invitation.email],
        fail_silently=True,
    )


def find_open(raw_token):
    """The invitation this link belongs to, if it can still be accepted."""
    invitation = (
        TenantInvitation.objects.select_related("unit", "unit__property", "organization")
        .filter(token_hash=hash_token(raw_token))
        .first()
    )
    if invitation is None or not invitation.is_open:
        return None
    return invitation


@transaction.atomic
def accept(invitation, *, password=None, first_name="", last_name="", user=None):
    """Turn an invitation into a tenant account and an active lease. Returns the tenant.

    Pass `user` when the tenant already has an account and has proved who they are;
    otherwise pass the `password` they chose for their new account.
    """
    invitation = (
        TenantInvitation.objects.select_for_update().select_related("unit").get(pk=invitation.pk)
    )
    if not invitation.is_open:
        raise ValidationError("This invitation is no longer valid.")
    unit = Unit.objects.select_for_update().get(pk=invitation.unit_id)
    if unit.leases.filter(status=Lease.Status.ACTIVE).exists():
        raise ValidationError("This unit already has a tenant.")

    existing = account_for(invitation.email)
    if existing is not None:
        if user is None or user.pk != existing.pk:
            raise PermissionDenied
        _check_email(invitation.organization, invitation.email)
        tenant = existing
    else:
        if not password:
            raise ValidationError("Choose a password.")
        tenant = User.objects.create_user(
            email=invitation.email,
            password=password,
            organization=invitation.organization,
            role=User.Role.TENANT,
            first_name=first_name.strip() or invitation.first_name,
            last_name=last_name.strip() or invitation.last_name,
        )

    lease = Lease.objects.create(
        organization=invitation.organization,
        unit=unit,
        tenant=tenant,
        start_date=invitation.start_date,
        end_date=invitation.end_date,
        rent_amount=invitation.rent_amount,
        deposit=invitation.deposit,
        due_day=invitation.due_day,
    )
    unit.status = Unit.Status.OCCUPIED
    unit.save(update_fields=["status"])
    invitation.status = TenantInvitation.Status.ACCEPTED
    invitation.accepted_at = timezone.now()
    invitation.lease = lease
    invitation.save(update_fields=["status", "accepted_at", "lease"])
    notifications.notify_landlords(
        invitation.organization,
        kind=Notification.Kind.TENANT,
        title=f"{notifications.display_name(tenant)} accepted your invitation",
        body=f"Unit {unit.unit_number} at {unit.property.name} now has a tenant.",
        url=reverse("dashboard:properties"),
    )
    return tenant


def _own_pending(landlord, invitation_id):
    _require_landlord(landlord)
    invitation = (
        TenantInvitation.objects.for_org(landlord.organization)
        .select_related("unit", "unit__property", "organization")
        .filter(pk=invitation_id, status=TenantInvitation.Status.PENDING)
        .first()
    )
    if invitation is None:
        raise PermissionDenied
    return invitation


def cancel(landlord, invitation_id):
    """Withdraw an invitation. Its link stops working at once."""
    invitation = _own_pending(landlord, invitation_id)
    invitation.status = TenantInvitation.Status.CANCELLED
    invitation.save(update_fields=["status"])
    return invitation


def resend(landlord, invitation_id):
    """Give an invitation a fresh link and seven more days. The old link stops working."""
    invitation = _own_pending(landlord, invitation_id)
    raw_token, invitation.token_hash = _new_token()
    invitation.expires_at = timezone.now() + timedelta(days=INVITE_DAYS)
    invitation.save(update_fields=["token_hash", "expires_at"])
    return invitation, raw_token


def pending_by_unit(organization):
    """Invitations still waiting, keyed by unit id, for the properties page."""
    waiting = TenantInvitation.objects.for_org(organization).filter(
        status=TenantInvitation.Status.PENDING
    )
    return {invitation.unit_id: invitation for invitation in waiting}
