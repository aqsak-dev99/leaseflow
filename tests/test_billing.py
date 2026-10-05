import datetime
import json

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.billing import services
from apps.billing.models import Invoice, Payment, WebhookEvent
from apps.billing.providers import get_provider
from apps.billing.providers.fake_gateway import sign
from apps.billing.webhooks import InvalidSignature, process_webhook
from apps.properties.models import Lease

PASSWORD = "demo12345"
JUNE = datetime.date(2026, 6, 1)


def user(email):
    return User.objects.get(email=email)


@pytest.fixture
def invoice(db):
    """An unpaid June invoice for Ali."""
    lease = Lease.objects.get(tenant=user("ali@alpha.test"))
    return Invoice.objects.create(
        organization=lease.organization,
        lease=lease,
        period=JUNE,
        amount=lease.rent_amount,
        due_date=datetime.date(2026, 6, 5),
    )


def event_for(payment, succeeded=True):
    return get_provider("fake_gateway").build_event(payment, succeeded=succeeded)


@pytest.mark.django_db
def test_generating_invoices_twice_creates_them_only_once():
    alpha = user("landlord@alpha.test").organization

    first = services.generate_invoices(period=JUNE, organization=alpha)
    second = services.generate_invoices(period=JUNE, organization=alpha)

    assert (first, second) == (2, 0)
    ali_invoice = Invoice.objects.get(lease__tenant=user("ali@alpha.test"), period=JUNE)
    assert ali_invoice.amount == 65000
    assert ali_invoice.due_date == datetime.date(2026, 6, 5)


@pytest.mark.django_db
def test_generating_for_one_organization_leaves_the_other_alone():
    alpha = user("landlord@alpha.test").organization

    services.generate_invoices(period=JUNE, organization=alpha)

    assert not Invoice.objects.filter(period=JUNE).exclude(organization=alpha).exists()


def test_due_date_moves_back_in_a_short_month(invoice):
    invoice.lease.due_day = 31

    assert services.due_date_for(invoice.lease, datetime.date(2026, 2, 1)) == datetime.date(
        2026, 2, 28
    )


def test_mark_overdue_flags_only_past_due_issued_invoices(invoice):
    assert invoice not in services.mark_overdue(today=datetime.date(2026, 6, 5))
    assert invoice in services.mark_overdue(today=datetime.date(2026, 6, 6))
    invoice.refresh_from_db()
    assert invoice.status == "overdue"
    # Running it again finds nothing new.
    assert invoice not in services.mark_overdue(today=datetime.date(2026, 6, 7))


def test_tenant_sees_only_their_own_invoices(invoice):
    assert invoice in services.invoices_for(user("ali@alpha.test"))
    assert invoice not in services.invoices_for(user("sara@alpha.test"))
    assert invoice in services.invoices_for(user("landlord@alpha.test"))
    assert invoice not in services.invoices_for(user("landlord@beta.test"))


def test_only_the_landlord_can_record_a_manual_payment(invoice):
    with pytest.raises(PermissionDenied):
        services.record_manual_payment(user=user("ali@alpha.test"), invoice_id=invoice.id)
    with pytest.raises(PermissionDenied):
        services.record_manual_payment(user=user("landlord@beta.test"), invoice_id=invoice.id)

    services.record_manual_payment(
        user=user("landlord@alpha.test"), invoice_id=invoice.id, reference="Cash"
    )

    invoice.refresh_from_db()
    assert invoice.status == "paid"
    assert invoice.payments.get().provider == "manual"


def test_a_paid_invoice_cannot_be_paid_again(invoice):
    landlord = user("landlord@alpha.test")
    services.record_manual_payment(user=landlord, invoice_id=invoice.id)

    with pytest.raises(ValidationError):
        services.record_manual_payment(user=landlord, invoice_id=invoice.id)
    with pytest.raises(ValidationError):
        services.start_gateway_payment(user=user("ali@alpha.test"), invoice_id=invoice.id)
    assert invoice.payments.count() == 1


def test_a_tenant_cannot_start_a_payment_on_someone_elses_invoice(invoice):
    with pytest.raises(PermissionDenied):
        services.start_gateway_payment(user=user("sara@alpha.test"), invoice_id=invoice.id)
    assert invoice.payments.count() == 0


def test_starting_a_payment_twice_reuses_the_pending_one(invoice):
    ali = user("ali@alpha.test")

    first, url = services.start_gateway_payment(user=ali, invoice_id=invoice.id)
    second, _ = services.start_gateway_payment(user=ali, invoice_id=invoice.id)

    assert first.id == second.id
    assert first.provider_reference in url


def test_signed_webhook_marks_the_invoice_paid(invoice):
    payment, _ = services.start_gateway_payment(user=user("ali@alpha.test"), invoice_id=invoice.id)
    body, signature = event_for(payment)

    assert process_webhook(body, signature) == "processed"

    invoice.refresh_from_db()
    payment.refresh_from_db()
    assert invoice.status == "paid"
    assert payment.status == "succeeded"


def test_the_same_webhook_delivered_twice_is_handled_once(invoice):
    payment, _ = services.start_gateway_payment(user=user("ali@alpha.test"), invoice_id=invoice.id)
    body, signature = event_for(payment)

    assert process_webhook(body, signature) == "processed"
    assert process_webhook(body, signature) == "duplicate"

    assert WebhookEvent.objects.filter(payment=payment).count() == 1
    assert Payment.objects.filter(invoice=invoice, status="succeeded").count() == 1


def test_webhook_with_a_bad_signature_is_rejected_and_changes_nothing(invoice):
    payment, _ = services.start_gateway_payment(user=user("ali@alpha.test"), invoice_id=invoice.id)
    body, _ = event_for(payment)

    with pytest.raises(InvalidSignature):
        process_webhook(body, "not-the-real-signature")

    invoice.refresh_from_db()
    assert invoice.status == "issued"
    assert WebhookEvent.objects.filter(payment=payment).count() == 0


def test_webhook_whose_body_was_changed_after_signing_is_rejected(invoice):
    payment, _ = services.start_gateway_payment(user=user("ali@alpha.test"), invoice_id=invoice.id)
    body, signature = event_for(payment, succeeded=False)
    tampered = body.replace(b"payment.failed", b"payment.succeeded")

    with pytest.raises(InvalidSignature):
        process_webhook(tampered, signature)


def test_webhook_for_the_wrong_amount_does_not_pay_the_invoice(invoice):
    payment, _ = services.start_gateway_payment(user=user("ali@alpha.test"), invoice_id=invoice.id)
    event = {
        "event_id": "evt-wrong-amount",
        "type": "payment.succeeded",
        "reference": payment.provider_reference,
        "amount": "1.00",
    }
    body = json.dumps(event).encode()

    process_webhook(body, sign(body))

    invoice.refresh_from_db()
    payment.refresh_from_db()
    assert invoice.status == "issued"
    assert payment.status == "failed"


def test_webhook_endpoint_checks_the_signature_header(client, invoice):
    payment, _ = services.start_gateway_payment(user=user("ali@alpha.test"), invoice_id=invoice.id)
    body, signature = event_for(payment)
    url = "/webhooks/fake-gateway/"

    bad = client.post(url, data=body, content_type="application/json", HTTP_X_SIGNATURE="nope")
    good = client.post(url, data=body, content_type="application/json", HTTP_X_SIGNATURE=signature)
    again = client.post(url, data=body, content_type="application/json", HTTP_X_SIGNATURE=signature)

    assert bad.status_code == 400
    assert good.json() == {"status": "processed"}
    assert again.json() == {"status": "duplicate"}
    invoice.refresh_from_db()
    assert invoice.status == "paid"


def test_tenant_pays_through_the_gateway_pages(client, invoice):
    client.login(email="ali@alpha.test", password=PASSWORD)

    started = client.post(f"/invoices/{invoice.id}/pay/")
    checkout = client.get(started.url)
    finished = client.post(started.url, {"outcome": "success", "duplicate": "1"})

    assert started.status_code == 302
    assert "FakePay" in checkout.content.decode()
    assert finished.status_code == 302
    invoice.refresh_from_db()
    assert invoice.status == "paid"
    assert invoice.payments.filter(status="succeeded").count() == 1


def test_a_failed_gateway_payment_leaves_the_invoice_unpaid(client, invoice):
    client.login(email="ali@alpha.test", password=PASSWORD)
    started = client.post(f"/invoices/{invoice.id}/pay/")

    client.post(started.url, {"outcome": "fail"})

    invoice.refresh_from_db()
    assert invoice.status == "issued"
    assert invoice.payments.get().status == "failed"


def test_invoice_pages_respect_roles_and_organizations(client, invoice):
    client.login(email="sara@alpha.test", password=PASSWORD)
    assert client.post(f"/invoices/{invoice.id}/pay/").status_code == 404
    assert client.post(f"/invoices/{invoice.id}/record-payment/").status_code == 403
    assert client.post("/invoices/generate/").status_code == 403
    client.logout()

    client.login(email="landlord@beta.test", password=PASSWORD)
    assert client.post(f"/invoices/{invoice.id}/record-payment/").status_code == 404
    assert "June 2026" not in client.get("/invoices/").content.decode()
    client.logout()

    client.login(email="landlord@alpha.test", password=PASSWORD)
    assert "June 2026" in client.get("/invoices/").content.decode()
    assert client.post(f"/invoices/{invoice.id}/record-payment/").status_code == 302
    invoice.refresh_from_db()
    assert invoice.status == "paid"


def test_balance_adds_up_unpaid_invoices_only(invoice):
    ali = user("ali@alpha.test")
    before = services.balance_for(ali)

    services.record_manual_payment(user=user("landlord@alpha.test"), invoice_id=invoice.id)

    assert before - services.balance_for(ali) == invoice.amount
