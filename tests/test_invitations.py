"""Tenant invitations: who can send them, how the link behaves, and what the tenant gets."""

import re
from datetime import date, timedelta

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.properties import invitations
from apps.properties.models import Lease, TenantInvitation, Unit

PASSWORD = "demo12345"
NEW_PASSWORD = "a-long-new-passphrase-42"


def landlord(email="landlord@alpha.test"):
    return User.objects.get(email=email)


def vacant_unit(owner=None):
    owner = owner or landlord()
    return Unit.objects.for_org(owner.organization).filter(status=Unit.Status.VACANT).first()


def invite(email="newtenant@example.com", owner=None, unit=None, **changes):
    owner = owner or landlord()
    details = {
        "landlord": owner,
        "unit_id": (unit or vacant_unit(owner)).id,
        "email": email,
        "first_name": "Nida",
        "last_name": "Khan",
        "start_date": date(2026, 11, 1),
        "end_date": date(2027, 10, 31),
        "rent_amount": 55000,
        "deposit": 110000,
        "due_day": 5,
    }
    details.update(changes)
    return invitations.create_invitation(**details)


FORM = {
    "email": "newtenant@example.com",
    "first_name": "Nida",
    "last_name": "Khan",
    "start_date": "2026-11-01",
    "end_date": "2027-10-31",
    "rent_amount": "55000",
    "deposit": "110000",
    "due_day": "5",
}
ACCOUNT = {
    "first_name": "Nida",
    "last_name": "Khan",
    "password": NEW_PASSWORD,
    "password_again": NEW_PASSWORD,
}


# ---------- sending


@pytest.mark.django_db
def test_only_the_hash_of_the_link_token_is_stored():
    invitation, raw_token = invite()

    assert len(raw_token) >= 40
    assert raw_token not in str(invitation.__dict__)
    assert invitation.token_hash == invitations.hash_token(raw_token)
    assert invitation.expires_at > timezone.now() + timedelta(days=6)


@pytest.mark.django_db
def test_a_landlord_invites_a_tenant_from_the_properties_page(client, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    unit = vacant_unit()
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert f"/units/{unit.id}/invite/" in client.get("/properties/").content.decode()
    response = client.post(f"/units/{unit.id}/invite/", FORM, follow=True)
    page = response.content.decode()

    invitation = TenantInvitation.objects.get(email="newtenant@example.com")
    assert invitation.unit == unit and invitation.status == "pending"
    assert "Invitation sent to newtenant@example.com" in page
    assert "/invite/" in page
    assert len(mail.outbox) == 1 and "/invite/" in mail.outbox[0].body
    # The link is shown once only.
    assert "Invitation sent to" not in client.get("/properties/").content.decode()
    assert "Invited" in client.get("/properties/").content.decode()


@pytest.mark.django_db
def test_a_tenant_cannot_invite_anyone(client):
    unit = vacant_unit()
    client.login(email="ali@alpha.test", password=PASSWORD)

    assert client.get(f"/units/{unit.id}/invite/").status_code == 403
    assert client.post(f"/units/{unit.id}/invite/", FORM).status_code == 403
    with pytest.raises(PermissionDenied):
        invite(owner=User.objects.get(email="ali@alpha.test"), unit=unit)
    assert not TenantInvitation.objects.exists()


@pytest.mark.django_db
def test_a_landlord_cannot_invite_to_another_organizations_unit(client):
    other_unit = vacant_unit(landlord("landlord@beta.test")) or Unit.objects.for_org(
        landlord("landlord@beta.test").organization
    ).first()
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert client.post(f"/units/{other_unit.id}/invite/", FORM).status_code == 404
    with pytest.raises(PermissionDenied):
        invite(unit=other_unit)


@pytest.mark.django_db
def test_an_occupied_unit_cannot_be_offered_again():
    occupied = Lease.objects.get(tenant__email="ali@alpha.test").unit

    with pytest.raises(ValidationError):
        invite(unit=occupied)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "email", ["landlord@alpha.test", "omar@beta.test", "ali@alpha.test", "ALI@alpha.test"]
)
def test_some_existing_accounts_cannot_be_invited(email):
    """A landlord, someone from another organization, or a tenant who already has a lease."""
    with pytest.raises(ValidationError):
        invite(email=email)


@pytest.mark.django_db
def test_bad_lease_details_are_refused():
    with pytest.raises(ValidationError):
        invite(end_date=date(2026, 10, 1))
    with pytest.raises(ValidationError):
        invite(due_day=31)
    with pytest.raises(ValidationError):
        invite(rent_amount=0)


@pytest.mark.django_db
def test_a_second_invitation_to_a_unit_replaces_the_first():
    first, first_token = invite(email="one@example.com")
    second, second_token = invite(email="two@example.com")

    first.refresh_from_db()
    assert first.status == "cancelled"
    assert invitations.find_open(first_token) is None
    assert invitations.find_open(second_token) == second


# ---------- accepting


@pytest.mark.django_db
def test_a_new_tenant_accepts_and_lands_in_their_own_home(client):
    invitation, raw_token = invite()
    unit = invitation.unit

    page = client.get(f"/invite/{raw_token}/").content.decode()
    assert f"Unit {unit.unit_number}" in page and "newtenant@example.com" in page

    response = client.post(f"/invite/{raw_token}/", ACCOUNT, follow=True)
    home = response.content.decode()

    tenant = User.objects.get(email="newtenant@example.com")
    lease = Lease.objects.get(tenant=tenant)
    unit.refresh_from_db()
    assert tenant.role == "tenant" and tenant.organization == invitation.organization
    assert tenant.check_password(NEW_PASSWORD) and tenant.get_full_name() == "Nida Khan"
    assert lease.unit == unit and lease.status == "active" and lease.rent_amount == 55000
    assert unit.status == "occupied"
    assert response.redirect_chain[-1][0] == "/"
    assert "Welcome, Nida" in home and unit.property.name in home
    # The landlord is told.
    note = Notification.objects.filter(user=landlord(), kind="tenant").first()
    assert note is not None and "Nida Khan accepted" in note.title


@pytest.mark.django_db
def test_the_new_tenant_sees_only_their_own_unit_and_lease(client):
    invitation, raw_token = invite()
    client.post(f"/invite/{raw_token}/", ACCOUNT)
    others = Lease.objects.for_org(invitation.organization).exclude(
        tenant__email="newtenant@example.com"
    )

    home = client.get("/").content.decode()

    for lease in others:
        assert f"unit {lease.unit.unit_number}" not in home
        assert lease.tenant.email not in home
    for landlord_page in ("/properties/", "/approvals/", "/activity/", "/tickets/"):
        assert client.get(landlord_page).status_code == 403
    assert client.get(f"/units/{invitation.unit_id}/invite/").status_code == 403


@pytest.mark.django_db
def test_a_link_works_only_once(client):
    _, raw_token = invite()
    client.post(f"/invite/{raw_token}/", ACCOUNT)
    client.logout()

    again = client.post(f"/invite/{raw_token}/", ACCOUNT)

    assert again.status_code == 404
    assert Lease.objects.filter(tenant__email="newtenant@example.com").count() == 1


@pytest.mark.django_db
def test_wrong_expired_and_cancelled_links_all_look_the_same(client):
    expired, expired_token = invite(email="late@example.com")
    TenantInvitation.objects.filter(pk=expired.pk).update(
        expires_at=timezone.now() - timedelta(minutes=1)
    )
    pages = [client.get(f"/invite/{expired_token}/"), client.get("/invite/not-a-real-token/")]
    cancelled, cancelled_token = invite(email="gone@example.com")
    invitations.cancel(landlord(), cancelled.id)
    pages.append(client.get(f"/invite/{cancelled_token}/"))

    assert [page.status_code for page in pages] == [404, 404, 404]
    bodies = {re.sub(r"X-CSRFToken[^}]*", "", page.content.decode()) for page in pages}
    assert len(bodies) == 1 and "Link not valid" in bodies.pop()
    assert client.post(f"/invite/{expired_token}/", ACCOUNT).status_code == 404
    assert not User.objects.filter(email="late@example.com").exists()


@pytest.mark.django_db
def test_a_weak_or_mismatched_password_is_refused(client):
    _, raw_token = invite()

    weak = client.post(f"/invite/{raw_token}/", {**ACCOUNT, "password": "12345678"})
    mismatch = client.post(f"/invite/{raw_token}/", {**ACCOUNT, "password_again": "different"})

    assert weak.status_code == 200 and mismatch.status_code == 200
    assert "do not match" in mismatch.content.decode()
    assert not User.objects.filter(email="newtenant@example.com").exists()


@pytest.mark.django_db
def test_someone_signed_in_as_another_person_cannot_accept(client):
    _, raw_token = invite()
    client.login(email="ali@alpha.test", password=PASSWORD)

    response = client.post(f"/invite/{raw_token}/", ACCOUNT)

    assert "for someone else" in response.content.decode()
    assert not User.objects.filter(email="newtenant@example.com").exists()
    assert invitations.find_open(raw_token) is not None


def returning_tenant():
    """A tenant with an account in this organization but no lease any more."""
    org = landlord().organization
    return User.objects.create_user(
        email="back@example.com", password=PASSWORD, organization=org, role=User.Role.TENANT
    )


@pytest.mark.django_db
def test_a_returning_tenant_accepts_with_their_existing_password(client):
    tenant = returning_tenant()
    invitation, raw_token = invite(email="back@example.com")

    wrong = client.post(f"/invite/{raw_token}/", {"password": "not-my-password"})
    assert "not correct" in wrong.content.decode()
    assert not Lease.objects.filter(tenant=tenant).exists()

    client.post(f"/invite/{raw_token}/", {"password": PASSWORD})

    assert Lease.objects.get(tenant=tenant).unit == invitation.unit
    assert User.objects.filter(email="back@example.com").count() == 1
    assert tenant.check_password(PASSWORD)


@pytest.mark.django_db
def test_a_returning_tenants_account_cannot_be_taken_over_through_an_invitation(client):
    tenant = returning_tenant()
    _, raw_token = invite(email="back@example.com")

    client.post(f"/invite/{raw_token}/", ACCOUNT)

    tenant.refresh_from_db()
    assert tenant.check_password(PASSWORD) and not tenant.check_password(NEW_PASSWORD)
    assert not Lease.objects.filter(tenant=tenant).exists()


# ---------- managing


@pytest.mark.django_db
def test_a_landlord_can_cancel_or_replace_a_link(client):
    invitation, old_token = invite()
    client.login(email="landlord@alpha.test", password=PASSWORD)

    page = client.post(f"/invitations/{invitation.id}/resend/", follow=True).content.decode()
    assert "Invitation sent to newtenant@example.com" in page
    assert invitations.find_open(old_token) is None
    invitation.refresh_from_db()
    assert invitation.status == "pending"

    client.post(f"/invitations/{invitation.id}/cancel/")
    invitation.refresh_from_db()
    assert invitation.status == "cancelled"


@pytest.mark.django_db
def test_nobody_else_can_cancel_or_replace_an_invitation(client):
    invitation, raw_token = invite()

    for email in ("ali@alpha.test", "landlord@beta.test"):
        client.login(email=email, password=PASSWORD)
        assert client.post(f"/invitations/{invitation.id}/cancel/").status_code == 403
        assert client.post(f"/invitations/{invitation.id}/resend/").status_code == 403
    assert client.get(f"/invitations/{invitation.id}/cancel/").status_code == 405
    assert invitations.find_open(raw_token) is not None
