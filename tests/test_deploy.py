"""What the live site depends on: health check, scheduled jobs, demo mode and who sees cost."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.agents.models import AgentRun
from apps.billing.models import Invoice
from apps.documents.models import Document

PASSWORD = "demo12345"
NEW_PASSWORD = "a-long-new-passphrase-42"


def test_the_health_check_answers_without_a_login(client):
    response = client.get("/healthz/")

    assert response.status_code == 200 and response.content == b"ok"


# ---------- scheduled jobs


@pytest.mark.django_db
def test_jobs_are_switched_off_when_no_secret_is_set(client, settings):
    settings.CRON_SECRET = ""

    response = client.post("/internal/jobs/monthly-invoices/", HTTP_AUTHORIZATION="Bearer ")

    assert response.status_code == 404


@pytest.mark.django_db
def test_jobs_need_the_right_secret(client, settings):
    settings.CRON_SECRET = "right-secret"
    before = Invoice.objects.count()

    missing = client.post("/internal/jobs/monthly-invoices/")
    wrong = client.post("/internal/jobs/monthly-invoices/", HTTP_AUTHORIZATION="Bearer wrong")
    get = client.get("/internal/jobs/monthly-invoices/", HTTP_AUTHORIZATION="Bearer right-secret")
    unknown = client.post("/internal/jobs/drop-tables/", HTTP_AUTHORIZATION="Bearer right-secret")

    assert [missing.status_code, wrong.status_code, unknown.status_code] == [404, 404, 404]
    assert get.status_code == 405
    assert Invoice.objects.count() == before


@pytest.mark.django_db
def test_the_monthly_invoice_job_runs_with_the_secret(client, settings):
    settings.CRON_SECRET = "right-secret"
    this_month = Invoice.objects.order_by("-period").first().period
    Invoice.objects.filter(period=this_month).delete()
    before = Invoice.objects.count()

    response = client.post(
        "/internal/jobs/monthly-invoices/", HTTP_AUTHORIZATION="Bearer right-secret"
    )

    assert response.status_code == 200
    assert response.json()["invoices"] == Invoice.objects.count() - before > 0


@pytest.mark.django_db
def test_the_overdue_job_calls_the_overdue_check(client, settings, monkeypatch):
    settings.CRON_SECRET = "right-secret"
    seen = {}

    def fake_check(**kwargs):
        seen.update(kwargs)
        return ["one", "two"]

    monkeypatch.setitem(
        __import__("apps.core.views", fromlist=["JOBS"]).JOBS,
        "overdue-check",
        lambda: {"drafted": len(fake_check(pause=3))},
    )

    response = client.post(
        "/internal/jobs/overdue-check/", HTTP_AUTHORIZATION="Bearer right-secret"
    )

    assert response.json() == {"job": "overdue-check", "drafted": 2}
    assert seen == {"pause": 3}


# ---------- demo mode


@pytest.mark.django_db
def test_demo_accounts_cannot_change_password_or_business_name(client, settings):
    settings.DEMO_MODE = True
    client.login(email="landlord@alpha.test", password=PASSWORD)
    name = User.objects.get(email="landlord@alpha.test").organization.name

    page = client.get("/profile/").content.decode()
    client.post(
        "/profile/",
        {
            "section": "password",
            "old_password": PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )
    client.post("/profile/", {"section": "business", "name": "Locked Out Ltd"})

    user = User.objects.get(email="landlord@alpha.test")
    assert "shared demo account" in page and 'name="old_password"' not in page
    assert user.check_password(PASSWORD)
    assert user.organization.name == name


@pytest.mark.django_db
def test_demo_mode_does_not_lock_real_accounts(client, settings):
    settings.DEMO_MODE = True
    org = User.objects.get(email="landlord@alpha.test").organization
    User.objects.create_user(
        email="real@example.com", password=PASSWORD, organization=org, role="tenant"
    )
    client.login(email="real@example.com", password=PASSWORD)

    client.post(
        "/profile/",
        {
            "section": "password",
            "old_password": PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )

    assert User.objects.get(email="real@example.com").check_password(NEW_PASSWORD)


@pytest.mark.django_db
def test_demo_buttons_show_on_the_login_page_only_in_demo_mode(client, settings):
    settings.DEMO_MODE = False
    assert "data-demo-email" not in client.get("/login/").content.decode()

    settings.DEMO_MODE = True
    page = client.get("/login/").content.decode()

    assert 'data-demo-email="landlord@alpha.test"' in page
    assert 'data-demo-email="ali@alpha.test"' in page


# ---------- cost is for the platform owner only


@pytest.mark.django_db
def test_a_landlord_sees_the_record_of_a_run_but_not_tokens_or_cost(client):
    alpha = User.objects.get(email="landlord@alpha.test").organization
    step = {"type": "model", "name": "supervisor", "ms": 5}
    step.update(input_tokens=384, output_tokens=38)
    run = AgentRun.objects.create(
        organization=alpha,
        route="lease",
        steps=[step],
        cost=Decimal("0.000352"),
        input_tokens=384,
        output_tokens=38,
    )
    client.login(email="landlord@alpha.test", password=PASSWORD)

    pages = "".join(
        client.get(url).content.decode() for url in ("/", "/activity/", f"/runs/{run.id}/")
    )

    assert f"/runs/{run.id}/" in pages
    for hidden in ("0.000352", "$0.0004", "Tokens in", "tokens in", "Estimated cost", "384 in"):
        assert hidden not in pages


# ---------- demo files after the host wipes its disk


@pytest.mark.django_db
def test_missing_demo_pdfs_are_rebuilt_and_existing_ones_left_alone(client):
    documents = Document.objects.filter(organization__slug="alpha-rentals")
    lease = documents.get(lease__tenant__email="ali@alpha.test")
    assert not lease.file.storage.exists(lease.file.name)

    call_command("restore_demo_documents")

    for document in documents:
        document.refresh_from_db()
        with document.file.open("rb") as handle:
            assert handle.read(4) == b"%PDF"
    lease.refresh_from_db()
    saved_as = lease.file.name
    call_command("restore_demo_documents")
    lease.refresh_from_db()
    assert lease.file.name == saved_as

    client.login(email="ali@alpha.test", password=PASSWORD)
    page = client.get(f"/documents/{lease.id}/page/2/").content.decode()
    assert "Notice period" in page and "Open the PDF" in page
