import pytest
from django.core import mail

from apps.accounts.models import User
from apps.agents import approvals
from apps.billing import services as billing_services
from apps.billing.models import Invoice
from apps.maintenance import services as maintenance_services
from apps.notifications import services as notifications
from apps.notifications.models import Notification

PASSWORD = "demo12345"


@pytest.fixture
def people(db):
    """The demo users, with any notifications from seeding cleared away."""
    Notification.objects.all().delete()
    return {
        "ali": User.objects.get(email="ali@alpha.test"),
        "sara": User.objects.get(email="sara@alpha.test"),
        "landlord": User.objects.get(email="landlord@alpha.test"),
        "other_landlord": User.objects.get(email="landlord@beta.test"),
    }


def titles(user):
    return list(notifications.for_user(user).values_list("title", flat=True))


def overdue_invoice(user):
    return Invoice.objects.filter(lease__tenant=user, status=Invoice.Status.OVERDUE).first()


def test_a_new_ticket_tells_the_landlord_of_that_organization_only(people):
    ticket = maintenance_services.create_ticket(
        user=people["ali"], title="Kitchen sink leaking", description="It drips"
    )

    note = notifications.for_user(people["landlord"]).get()
    assert note.title == "New repair ticket: Kitchen sink leaking"
    assert note.url == f"/tickets/{ticket.id}/"
    assert note.kind == "repair"
    assert titles(people["other_landlord"]) == []
    assert titles(people["ali"]) == []


def test_a_status_change_tells_the_tenant_who_reported_the_ticket(people):
    ticket = maintenance_services.create_ticket(
        user=people["ali"], title="Kitchen sink leaking", description="It drips"
    )

    maintenance_services.update_status(
        user=people["landlord"], ticket_id=ticket.id, new_status="in_progress"
    )

    assert titles(people["ali"]) == ["Your repair ticket is now in progress"]
    assert titles(people["sara"]) == []


def test_a_waiver_request_tells_the_landlord_once_and_the_decision_tells_the_tenant(people):
    invoice = overdue_invoice(people["ali"])
    request, _ = approvals.request_waiver(user=people["ali"], invoice=invoice, reason="Lost job")
    approvals.request_waiver(user=people["ali"], invoice=invoice, reason="Asking again")

    assert titles(people["landlord"]) == ["Waiver request from Ali Raza"]

    approvals.reject(user=people["landlord"], request_id=request.id)

    assert titles(people["ali"]) == ["Your waiver request was declined"]


def test_an_approved_waiver_and_an_approved_reminder_each_tell_the_tenant(people):
    invoice = overdue_invoice(people["ali"])
    reminder, _ = approvals.request_reminder(invoice=invoice, subject="Rent reminder", body="Hi")
    approvals.approve(user=people["landlord"], request_id=reminder.id)
    waiver, _ = approvals.request_waiver(user=people["ali"], invoice=invoice, reason="Lost job")
    approvals.approve(user=people["landlord"], request_id=waiver.id)

    assert titles(people["ali"]) == ["Your waiver request was approved", "Rent reminder"]
    assert len(mail.outbox) == 1
    assert "A rent reminder was drafted for your approval" in titles(people["landlord"])


def test_a_payment_tells_the_tenant_and_the_landlord(people):
    invoice = overdue_invoice(people["ali"])

    billing_services.record_manual_payment(user=people["landlord"], invoice_id=invoice.id)

    assert titles(people["ali"]) == ["Payment received"]
    assert titles(people["landlord"]) == [f"Ali Raza paid {invoice.period:%B} rent"]


def test_an_invoice_going_overdue_tells_its_tenant(people):
    issued = Invoice.objects.filter(
        lease__tenant=people["sara"], status=Invoice.Status.ISSUED
    ).first()

    billing_services.mark_overdue(today=issued.due_date.replace(day=28))

    assert f"Your {issued.period:%B} rent is overdue" in titles(people["sara"])


def test_opening_a_notification_marks_it_read_and_returns_its_page(people):
    note = notifications.notify(
        user=people["ali"], kind="rent", title="Payment received", url="/invoices/"
    )

    assert notifications.unread_count(people["ali"]) == 1
    assert notifications.open_notification(people["ali"], note.id) == "/invoices/"
    assert notifications.unread_count(people["ali"]) == 0


def test_bell_shows_the_unread_count_and_the_panel_lists_only_my_notifications(client, people):
    notifications.notify(user=people["ali"], kind="rent", title="For Ali only")
    notifications.notify(user=people["sara"], kind="rent", title="For Sara only")
    client.login(email="ali@alpha.test", password=PASSWORD)

    home = client.get("/").content.decode()
    panel = client.get("/notifications/panel/").content.decode()
    page = client.get("/notifications/").content.decode()

    assert 'aria-label="1 unread"' in home
    assert "For Ali only" in panel and "For Sara only" not in panel
    assert "For Ali only" in page and "For Sara only" not in page


def test_one_user_cannot_open_anothers_notification(client, people):
    note = notifications.notify(user=people["sara"], kind="rent", title="Private", url="/invoices/")
    client.login(email="ali@alpha.test", password=PASSWORD)

    response = client.get(f"/notifications/{note.id}/open/")

    note.refresh_from_db()
    assert response.status_code == 404
    assert note.read_at is None


def test_opening_follows_only_links_inside_the_site(client, people):
    inside = notifications.notify(user=people["ali"], kind="rent", title="A", url="/invoices/")
    outside = notifications.notify(
        user=people["ali"], kind="rent", title="B", url="https://example.com/"
    )
    client.login(email="ali@alpha.test", password=PASSWORD)

    assert client.get(f"/notifications/{inside.id}/open/").url == "/invoices/"
    assert client.get(f"/notifications/{outside.id}/open/").url == "/notifications/"


def test_mark_all_as_read_clears_only_my_unread_count(client, people):
    notifications.notify(user=people["ali"], kind="rent", title="One")
    notifications.notify(user=people["ali"], kind="rent", title="Two")
    notifications.notify(user=people["sara"], kind="rent", title="Three")
    client.login(email="ali@alpha.test", password=PASSWORD)

    client.post("/notifications/read-all/")

    assert notifications.unread_count(people["ali"]) == 0
    assert notifications.unread_count(people["sara"]) == 1


def test_notification_pages_need_a_login(client, db):
    for url in ["/notifications/", "/notifications/panel/", "/notifications/count/"]:
        assert client.get(url).status_code == 302
