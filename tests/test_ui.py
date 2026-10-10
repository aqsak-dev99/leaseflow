import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.agents import approvals
from apps.agents.models import AgentRun, Conversation, Message
from apps.billing.models import Invoice
from apps.dashboard.templatetags import ui
from apps.dashboard.trace import describe_step, describe_steps
from apps.maintenance import services as maintenance_services

PASSWORD = "demo12345"

LANDLORD_PAGES = ["/", "/properties/", "/tickets/", "/invoices/", "/approvals/", "/activity/"]
TENANT_PAGES = ["/", "/chat/", "/invoices/"]


@pytest.fixture
def ali(db):
    return User.objects.get(email="ali@alpha.test")


@pytest.mark.parametrize(
    "step,sentence,state",
    [
        (
            {"type": "model", "name": "supervisor", "detail": {"route": "lease"}},
            "Sent to the lease assistant",
            "",
        ),
        (
            {"type": "model", "name": "supervisor", "detail": {"route": "maintenance"}},
            "Sent to the repairs assistant",
            "",
        ),
        (
            {"type": "retrieval", "name": "search", "detail": {"results": [{}, {}, {}]}},
            "Found 3 matching passages in the tenant's own lease documents",
            "",
        ),
        (
            {"type": "retrieval", "name": "search", "detail": {"results": []}},
            "Found nothing relevant in the lease documents",
            "",
        ),
        (
            {"type": "model", "name": "verifier", "detail": {"verdict": "supported"}},
            "Checked against the lease: supported",
            "done",
        ),
        (
            {"type": "model", "name": "verifier", "detail": {"verdict": "unsupported"}},
            "Checked against the lease: not supported, so the answer was withheld",
            "bad",
        ),
        (
            {"type": "check", "name": "verifier", "detail": {"verdict": "no_citation"}},
            "Answer withheld: it did not cite the lease",
            "bad",
        ),
        (
            {"type": "tool", "name": "request_waiver", "detail": {"result": "Filed."}},
            "Filed a waiver request for the landlord to decide",
            "",
        ),
        (
            {"type": "model", "name": "payment_agent", "detail": {"task": "draft_reminder"}},
            "Drafted a rent reminder for the landlord to approve",
            "",
        ),
        ({"type": "tool", "name": "new_tool"}, "Used the tool new_tool", ""),
        ({"name": "something_else"}, "something_else", ""),
    ],
)
def test_a_step_is_described_in_plain_words(step, sentence, state):
    title, _, got_state = describe_step(step)

    assert title == sentence
    assert got_state == state


def test_described_steps_keep_their_original_fields():
    steps = [{"type": "tool", "name": "get_balance", "ms": 12, "detail": {"result": "Rs. 5"}}]

    described = describe_steps(steps)

    assert described[0]["ms"] == 12
    assert described[0]["title"] == "Looked up what the tenant owes"
    assert described[0]["note"] == "Rs. 5"
    assert describe_steps(None) == []


def test_initials_come_from_the_name_or_the_email():
    assert ui.initials(SimpleNamespace(first_name="Ali", last_name="Raza", email="a@b.c")) == "AR"
    assert ui.initials(SimpleNamespace(first_name="", last_name="", email="landlord@x.y")) == "LA"


@pytest.mark.django_db
def test_every_landlord_page_renders_with_the_new_shell(client):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    for url in LANDLORD_PAGES:
        html = client.get(url).content.decode()
        assert "data-theme-toggle" in html, url
        assert 'class="tabs"' in html, url
        assert 'class="bottom-nav"' not in html, url


@pytest.mark.django_db
def test_every_tenant_page_renders_with_the_phone_navigation(client):
    client.login(email="ali@alpha.test", password=PASSWORD)

    for url in TENANT_PAGES:
        response = client.get(url)
        html = response.content.decode()
        assert response.status_code == 200, url
        assert 'class="bottom-nav"' in html, url
        assert "Approvals" not in html, url


@pytest.mark.django_db
def test_the_current_page_is_marked_in_the_navigation(client):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    html = client.get("/tickets/").content.decode()

    assert '<a href="/tickets/" aria-current="page">Tickets</a>' in html
    assert '<a href="/properties/">Properties</a>' in html


@pytest.mark.django_db
def test_landlord_navigation_counts_requests_waiting_for_approval(client, ali):
    invoice = Invoice.objects.filter(lease__tenant=ali, status=Invoice.Status.OVERDUE).first()
    approvals.request_waiver(user=ali, invoice=invoice, reason="Lost my job")
    client.login(email="landlord@alpha.test", password=PASSWORD)

    response = client.get("/properties/")

    assert response.context["nav_pending_approvals"] == 1
    assert 'aria-label="1 waiting"' in response.content.decode()


@pytest.mark.django_db
def test_landlord_home_shows_collection_progress_pending_decisions_and_the_latest_run(
    client, ali
):
    invoice = Invoice.objects.filter(lease__tenant=ali, status=Invoice.Status.OVERDUE).first()
    approvals.request_waiver(user=ali, invoice=invoice, reason="Lost my job")
    steps = [{"type": "model", "name": "supervisor", "ms": 5, "detail": {"route": "lease"}}]
    AgentRun.objects.create(organization=ali.organization, route="lease", steps=steps)
    AgentRun.objects.create(
        organization=User.objects.get(email="omar@beta.test").organization, route="payment"
    )
    client.login(email="landlord@alpha.test", password=PASSWORD)

    response = client.get("/")

    html = response.content.decode()
    context = response.context
    assert context["invoiced"] == Decimal("274000")
    assert context["collected"] == Decimal("72000")
    assert context["collected_percent"] == 26
    assert context["latest_run"].route == "lease"
    assert "Sent to the lease assistant" in html
    assert "Lost my job" in html
    assert "Review and decide" in html


@pytest.mark.django_db
def test_tenant_home_offers_to_pay_the_oldest_unpaid_invoice(client, ali):
    oldest = Invoice.objects.filter(lease__tenant=ali).order_by("due_date").first()
    client.login(email="ali@alpha.test", password=PASSWORD)

    response = client.get("/")

    assert response.context["next_invoice"] == oldest
    assert f'action="/invoices/{oldest.id}/pay/"' in response.content.decode()


@pytest.mark.django_db
def test_tenant_home_says_all_paid_when_nothing_is_owed(client):
    sara = User.objects.get(email="sara@alpha.test")
    Invoice.objects.filter(lease__tenant=sara).update(status=Invoice.Status.PAID)
    client.login(email="sara@alpha.test", password=PASSWORD)

    response = client.get("/")

    assert response.context["next_invoice"] is None
    assert "All paid" in response.content.decode()


@pytest.mark.django_db
def test_long_lists_are_split_into_pages_and_keep_their_filter(client, ali):
    for number in range(12):
        maintenance_services.create_ticket(
            user=ali, title=f"Problem {number}", description="Something is wrong"
        )
    client.login(email="landlord@alpha.test", password=PASSWORD)

    first = client.get("/tickets/?status=open")
    second = client.get("/tickets/?status=open&page=2")

    assert len(first.context["tickets"]) == 10
    assert len(second.context["tickets"]) == 2
    assert 'href="?status=open&amp;page=2"' in first.content.decode()
    assert "Showing 1 to 10 of 12" in first.content.decode()
    assert "Problem 0" in second.content.decode()


@pytest.mark.django_db
def test_short_lists_show_no_page_links(client):
    client.login(email="landlord@alpha.test", password=PASSWORD)

    assert 'class="pagination"' not in client.get("/tickets/").content.decode()


@pytest.mark.django_db
def test_chat_marks_an_answer_as_checked_only_when_the_verifier_supported_it(client, ali):
    conversation = Conversation.objects.create(organization=ali.organization, user=ali)
    supported = AgentRun.objects.create(
        organization=ali.organization,
        route="lease",
        steps=[{"type": "model", "name": "verifier", "detail": {"verdict": "supported"}}],
    )
    plain = AgentRun.objects.create(organization=ali.organization, route="maintenance")
    for run, text in [(supported, "Notice is 30 days [1]."), (plain, "Ticket opened.")]:
        Message.objects.create(
            organization=ali.organization,
            conversation=conversation,
            role="assistant",
            content=text,
            run=run,
        )
    client.login(email="ali@alpha.test", password=PASSWORD)

    html = client.get("/chat/").content.decode()

    assert html.count("Checked against your lease") == 1
    assert "Lease assistant" in html
    assert "Repairs assistant" in html


@pytest.mark.django_db
def test_run_page_explains_steps_and_keeps_the_raw_details(client):
    alpha = User.objects.get(email="landlord@alpha.test").organization
    steps = [
        {"type": "model", "name": "supervisor", "ms": 5, "detail": {"route": "lease"}},
        {"type": "model", "name": "verifier", "ms": 9, "detail": {"verdict": "supported"}},
    ]
    run = AgentRun.objects.create(organization=alpha, route="lease", steps=steps)
    client.login(email="landlord@alpha.test", password=PASSWORD)

    html = client.get(f"/runs/{run.id}/").content.decode()

    assert "Sent to the lease assistant" in html
    assert "Checked against the lease: supported" in html
    assert "Show details" in html
    assert "&quot;verdict&quot;: &quot;supported&quot;" in html


@pytest.mark.django_db
def test_form_errors_are_shown_next_to_the_field(client):
    response = client.post("/login/", {"username": "ali@alpha.test", "password": "wrong"})

    html = response.content.decode()
    assert response.status_code == 200
    assert "errorlist" in html
    assert 'class="btn btn-arrow"' in html


def test_every_stylesheet_the_pages_link_to_exists():
    root = Path(__file__).resolve().parent.parent
    for template in ["templates/base.html", "templates/billing/fake_checkout.html"]:
        linked = re.findall(r"{% static 'css/([a-z]+\.css)' %}", (root / template).read_text())
        assert linked == [
            "tokens.css",
            "base.css",
            "layout.css",
            "components.css",
            "pages.css",
            "responsive.css",
        ]
        assert all((root / "static" / "css" / name).exists() for name in linked)


def test_a_tool_using_assistants_last_step_is_the_reply():
    steps = [
        {"type": "model", "name": "maintenance_agent"},
        {"type": "tool", "name": "create_ticket", "detail": {"result": "Created"}},
        {"type": "model", "name": "maintenance_agent"},
    ]

    described = describe_steps(steps)

    assert described[0]["title"] == "The repairs assistant decided what to do next"
    assert described[2]["title"] == "Wrote the reply to the tenant"


@pytest.mark.django_db
def test_the_app_opens_on_the_login_page_with_the_splash(client):
    response = client.get("/", follow=True)
    page = response.content.decode()

    assert response.redirect_chain == [("/login/", 302)]
    assert 'class="splash"' in page
    assert 'class="splash"' not in client.get("/signup/").content.decode()
    client.login(email="ali@alpha.test", password=PASSWORD)
    assert 'class="splash"' not in client.get("/").content.decode()


@pytest.mark.django_db
def test_the_login_page_has_a_landlord_and_a_tenant_portal(client):
    tenant = client.get("/login/?portal=tenant").content.decode()
    landlord = client.get("/login/?portal=landlord").content.decode()
    plain = client.get("/login/?portal=admin").content.decode()

    assert "/login/?portal=landlord" in plain and "/login/?portal=tenant" in plain
    assert "Tenant login" in tenant
    assert "Your landlord creates it for you" in tenant
    assert "Landlord login" in landlord
    assert "Create an account" in landlord
    assert "Landlord login" in plain


@pytest.mark.django_db
def test_the_account_role_decides_the_portal_not_the_switch(client):
    response = client.post(
        "/login/?portal=landlord",
        {"username": "ali@alpha.test", "password": PASSWORD, "portal": "landlord"},
        follow=True,
    )
    page = response.content.decode()

    assert "This is a tenant account" in page
    assert client.get("/approvals/").status_code in (302, 403, 404)


@pytest.mark.django_db
def test_logging_in_through_the_matching_portal_shows_no_note(client):
    response = client.post(
        "/login/?portal=tenant",
        {"username": "ali@alpha.test", "password": PASSWORD, "portal": "tenant"},
        follow=True,
    )

    assert "This is a tenant account" not in response.content.decode()
