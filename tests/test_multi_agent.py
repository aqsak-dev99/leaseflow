from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage

from apps.accounts.models import User
from apps.agents import graph, maintenance_agent
from apps.agents.models import AgentRun
from apps.agents.tools.maintenance import build_maintenance_tools
from apps.agents.tracing import Trace
from apps.maintenance import services as maintenance_services
from apps.maintenance.models import MaintenanceTicket, TicketUpdate


class ScriptedModel:
    """A stand-in model that returns prepared replies in order."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def bind_tools(self, tools):
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0)


def tool_call(name, **args):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": "call_1"}])


@pytest.fixture
def ali(db):
    return User.objects.get(email="ali@alpha.test")


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("maintenance", "maintenance"),
        ("Lease", "lease"),
        ("payment", "payment"),
        ("other", "other"),
        ("I am not sure", "other"),
    ],
)
def test_supervisor_reply_is_parsed_into_a_known_route(reply, expected):
    assert graph._parse_route(reply) == expected


def test_supervisor_sends_a_repair_report_to_the_maintenance_agent(ali, monkeypatch):
    monkeypatch.setattr(graph, "get_chat_model", lambda: ScriptedModel(AIMessage("maintenance")))
    monkeypatch.setattr(
        graph, "run_maintenance_agent", lambda **kwargs: {"answer": "ticket", "citations": []}
    )
    trace = Trace()

    result = graph.run_chat(user=ali, text="My sink is leaking", trace=trace)

    assert result["route"] == "maintenance"
    assert result["answer"] == "ticket"
    assert trace.steps[0]["name"] == "supervisor"


def test_supervisor_sends_a_lease_question_to_the_lease_agent(ali, monkeypatch):
    monkeypatch.setattr(graph, "get_chat_model", lambda: ScriptedModel(AIMessage("lease")))
    monkeypatch.setattr(
        graph, "answer_lease_question", lambda **kwargs: {"answer": "30 days", "citations": []}
    )

    result = graph.run_chat(user=ali, text="What is my notice period?")

    assert result["route"] == "lease"
    assert result["answer"] == "30 days"


def test_out_of_scope_message_gets_a_fixed_reply_without_an_agent(ali, monkeypatch):
    monkeypatch.setattr(graph, "get_chat_model", lambda: ScriptedModel(AIMessage("other")))

    result = graph.run_chat(user=ali, text="Tell me a joke")

    assert result["route"] == "other"
    assert result["answer"] == graph.OUT_OF_SCOPE


def test_maintenance_agent_creates_a_ticket_for_the_tenants_own_unit(ali, monkeypatch):
    model = ScriptedModel(
        tool_call(
            "create_ticket",
            title="Kitchen sink leaking",
            description="Water drips from the pipe under the kitchen sink.",
            category="plumbing",
            priority="high",
        ),
        AIMessage("I've created ticket #1 for the leaking sink."),
    )
    monkeypatch.setattr(maintenance_agent, "get_chat_model", lambda: model)
    trace = Trace()

    result = maintenance_agent.run_maintenance_agent(
        user=ali, text="My kitchen sink is leaking under the pipe", trace=trace
    )

    ticket = MaintenanceTicket.objects.get()
    assert ticket.reported_by == ali
    assert ticket.unit.unit_number == "A1"
    assert ticket.category == "plumbing"
    assert ticket.updates.get().via_agent is True
    assert "created ticket" in result["answer"]
    assert [step["type"] for step in trace.steps] == ["model", "tool", "model"]


def test_create_tool_warns_about_a_duplicate_before_making_a_second_ticket(ali):
    create_ticket = build_maintenance_tools(ali)[0]
    args = {"title": "Sink leaking", "description": "Kitchen sink drips.", "category": "plumbing"}

    first = create_ticket.invoke(args)
    second = create_ticket.invoke(args)
    third = create_ticket.invoke({**args, "allow_duplicate": True})

    assert first.startswith("Created ticket")
    assert second.startswith("Not created")
    assert third.startswith("Created ticket")
    assert MaintenanceTicket.objects.count() == 2


def test_tools_cannot_reach_another_tenants_ticket(ali):
    sara = User.objects.get(email="sara@alpha.test")
    saras_ticket = maintenance_services.create_ticket(
        user=sara, title="Broken window", description="Bedroom window is cracked."
    )
    _, list_my_tickets, add_ticket_comment = build_maintenance_tools(ali)

    listing = list_my_tickets.invoke({})
    comment = add_ticket_comment.invoke({"ticket_id": saras_ticket.id, "note": "Close this."})

    assert "Broken window" not in listing
    assert comment.startswith("Error")
    assert TicketUpdate.objects.filter(ticket=saras_ticket).count() == 1


def test_tools_have_no_way_to_change_a_tickets_status(ali):
    names = {tool.name for tool in build_maintenance_tools(ali)}
    arguments = set()
    for tool in build_maintenance_tools(ali):
        arguments.update(tool.args.keys())

    assert names == {"create_ticket", "list_my_tickets", "add_ticket_comment"}
    assert "status" not in arguments
    assert "user" not in arguments and "user_id" not in arguments


def test_agent_stops_after_a_fixed_number_of_tool_rounds(ali, monkeypatch):
    replies = [tool_call("list_my_tickets") for _ in range(10)]
    monkeypatch.setattr(maintenance_agent, "get_chat_model", lambda: ScriptedModel(*replies))

    result = maintenance_agent.run_maintenance_agent(user=ali, text="loop forever")

    assert result["answer"] == maintenance_agent.GAVE_UP


def test_full_chat_turn_records_the_route_and_tool_calls(client, ali, monkeypatch):
    monkeypatch.setattr(graph, "get_chat_model", lambda: ScriptedModel(AIMessage("maintenance")))
    model = ScriptedModel(
        tool_call(
            "create_ticket",
            title="Bathroom light not working",
            description="The bathroom ceiling light does not turn on.",
            category="electrical",
        ),
        AIMessage("Ticket created for the bathroom light."),
    )
    monkeypatch.setattr(maintenance_agent, "get_chat_model", lambda: model)
    client.login(email="ali@alpha.test", password="demo12345")

    response = client.post("/chat/send/", {"question": "My bathroom light is not working"})

    assert "Ticket created for the bathroom light." in response.content.decode()
    run = AgentRun.objects.get()
    assert run.route == "maintenance"
    assert [step["name"] for step in run.steps] == [
        "supervisor",
        "maintenance_agent",
        "create_ticket",
        "maintenance_agent",
    ]
    assert MaintenanceTicket.objects.filter(category="electrical").count() == 1


def test_fake_reply_without_usage_data_still_traces(ali, monkeypatch):
    reply = SimpleNamespace(content="other")
    monkeypatch.setattr(graph, "get_chat_model", lambda: ScriptedModel(reply))
    trace = Trace()

    graph.run_chat(user=ali, text="hello", trace=trace)

    assert trace.input_tokens == 0
