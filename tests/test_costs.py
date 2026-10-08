from decimal import Decimal
from importlib import import_module
from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command

from apps.accounts.models import User
from apps.agents import services as agent_services
from apps.agents.costs import estimate_cost
from apps.agents.evals.runner import Result
from apps.agents.management.commands import run_evals
from apps.agents.models import AgentRun

PASSWORD = "demo12345"


def test_cost_is_tokens_times_the_price_per_million(settings):
    settings.LLM_INPUT_PRICE = 0.15
    settings.LLM_OUTPUT_PRICE = 0.60

    assert estimate_cost(1_000_000, 0) == Decimal("0.15")
    assert estimate_cost(0, 1_000_000) == Decimal("0.60")
    assert estimate_cost(1390, 239) == Decimal("0.000352")
    assert estimate_cost(0, 0) == 0
    assert estimate_cost(None, None) == 0


def test_cost_follows_the_prices_in_settings(settings):
    settings.LLM_INPUT_PRICE = 3
    settings.LLM_OUTPUT_PRICE = 15

    assert estimate_cost(1000, 1000) == Decimal("0.018")


@pytest.mark.django_db
def test_a_chat_run_is_saved_with_its_cost(client, monkeypatch, settings):
    settings.LLM_INPUT_PRICE = 0.15
    settings.LLM_OUTPUT_PRICE = 0.60

    def fake_run_chat(*, user, text, history, trace):
        trace.add("model", "supervisor", 0, input_tokens=1000, output_tokens=500)
        return {"route": "other", "answer": "Hello.", "citations": []}

    monkeypatch.setattr(agent_services, "run_chat", fake_run_chat)
    client.login(email="ali@alpha.test", password=PASSWORD)

    client.post("/chat/send/", {"question": "Hello"})

    assert AgentRun.objects.get().cost == Decimal("0.00045")


@pytest.mark.django_db
def test_activity_page_totals_cost_for_the_landlords_organization_only(client, settings):
    settings.LLM_INPUT_PRICE = 0.15
    settings.LLM_OUTPUT_PRICE = 0.60
    alpha = User.objects.get(email="landlord@alpha.test").organization
    beta = User.objects.get(email="landlord@beta.test").organization
    AgentRun.objects.create(organization=alpha, route="lease", cost=Decimal("0.0100"))
    AgentRun.objects.create(organization=alpha, route="lease", cost=Decimal("0.0200"))
    AgentRun.objects.create(organization=alpha, route="payment", cost=Decimal("0.0500"))
    AgentRun.objects.create(organization=beta, route="lease", cost=Decimal("9.0000"))
    client.login(email="landlord@alpha.test", password=PASSWORD)

    response = client.get("/activity/")

    html = response.content.decode()
    by_route = {row["route"]: row for row in response.context["by_route"]}
    assert response.context["totals"]["cost"] == Decimal("0.08")
    assert "$0.0800" in html
    assert by_route["lease"]["runs"] == 2
    assert by_route["lease"]["cost"] == Decimal("0.03")
    assert by_route["payment"]["cost"] == Decimal("0.05")
    assert "$9" not in html
    assert "$0.15 per million input tokens" in html


@pytest.mark.django_db
def test_run_page_shows_the_run_cost_and_each_steps_cost(client, settings):
    settings.LLM_INPUT_PRICE = 0.15
    settings.LLM_OUTPUT_PRICE = 0.60
    alpha = User.objects.get(email="landlord@alpha.test").organization
    steps = [
        {"type": "model", "name": "supervisor", "ms": 5, "input_tokens": 384, "output_tokens": 38},
        {"type": "retrieval", "name": "search_lease_documents", "ms": 9},
    ]
    run = AgentRun.objects.create(
        organization=alpha, route="lease", steps=steps, cost=Decimal("0.000352")
    )
    client.login(email="landlord@alpha.test", password=PASSWORD)

    html = client.get(f"/runs/{run.id}/").content.decode()

    assert "estimated cost $0.000352" in html
    assert "384 in, 38 out · $0.000080" in html


@pytest.mark.django_db
def test_older_runs_get_a_cost_from_their_tokens(settings):
    settings.LLM_INPUT_PRICE = 0.15
    settings.LLM_OUTPUT_PRICE = 0.60
    alpha = User.objects.get(email="landlord@alpha.test").organization
    old = AgentRun.objects.create(organization=alpha, input_tokens=1000, output_tokens=500)
    empty = AgentRun.objects.create(organization=alpha)
    priced = AgentRun.objects.create(organization=alpha, input_tokens=1000, cost=Decimal("0.5"))
    migration = import_module("apps.agents.migrations.0003_backfill_run_cost")

    migration.fill_in_costs(django_apps, None)

    old.refresh_from_db()
    empty.refresh_from_db()
    priced.refresh_from_db()
    assert old.cost == Decimal("0.00045")
    assert empty.cost == 0
    assert priced.cost == Decimal("0.5")


@pytest.mark.django_db
def test_eval_summary_includes_the_estimated_cost(monkeypatch, settings):
    settings.LLM_INPUT_PRICE = 0.15
    settings.LLM_OUTPUT_PRICE = 0.60
    monkeypatch.setattr(
        run_evals,
        "run_case",
        lambda case: Result(
            id=case["id"], group=case["group"], input_tokens=24455, output_tokens=5057
        ),
    )
    monkeypatch.setattr(run_evals.Command, "check_demo_data", lambda self, cases: None)
    out = StringIO()

    call_command("run_evals", "--case", "notice-ali", stdout=out)

    assert "Est. cost $0.0067" in out.getvalue()
