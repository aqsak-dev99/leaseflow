from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.agents import lease_agent
from apps.agents import services as agent_services
from apps.agents.models import AgentRun, Message
from apps.agents.tracing import Trace


def fake_chunk(title, page, text):
    return SimpleNamespace(document=SimpleNamespace(title=title), page_number=page, text=text)


class FakeModel:
    def __init__(self, reply):
        self.reply = reply
        self.messages = None

    def invoke(self, messages):
        self.messages = messages
        return SimpleNamespace(
            content=self.reply, usage_metadata={"input_tokens": 120, "output_tokens": 15}
        )


def fake_answer(**kwargs):
    return {
        "route": "lease",
        "answer": "30 days [1].",
        "citations": [{"number": 1, "title": "Lease", "page": 2, "text": "Notice..."}],
    }


@pytest.mark.django_db
def test_lease_agent_answers_with_page_citation_and_records_a_trace(monkeypatch):
    chunks = [
        fake_chunk("Lease agreement, unit A1", 2, "Notice period is 30 days."),
        fake_chunk("Lease agreement, unit A1", 3, "Pets are not allowed."),
    ]
    model = FakeModel("You must give 30 days written notice [1].")
    monkeypatch.setattr(lease_agent, "search_chunks", lambda **kwargs: chunks)
    monkeypatch.setattr(lease_agent, "get_chat_model", lambda: model)
    ali = User.objects.get(email="ali@alpha.test")
    trace = Trace()

    result = lease_agent.answer_lease_question(
        user=ali, question="What is my notice period?", trace=trace
    )

    assert "30 days" in result["answer"]
    assert [(c["number"], c["page"]) for c in result["citations"]] == [(1, 2)]
    assert "Notice period is 30 days." in model.messages[1][1]
    assert [step["type"] for step in trace.steps] == ["retrieval", "model"]
    assert trace.input_tokens == 120
    assert trace.output_tokens == 15


@pytest.mark.django_db
def test_lease_agent_searches_only_the_users_own_lease(monkeypatch):
    seen = {}

    def fake_search(**kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(lease_agent, "search_chunks", fake_search)
    sara = User.objects.get(email="sara@alpha.test")

    result = lease_agent.answer_lease_question(user=sara, question="Can I have a cat?")

    assert seen["lease"].tenant == sara
    assert seen["organization"] == sara.organization
    assert result["answer"] == lease_agent.NOT_FOUND


@pytest.mark.django_db
def test_chat_is_for_logged_in_tenants_only(client):

    assert client.get("/chat/").status_code == 302

    client.login(email="landlord@alpha.test", password="demo12345")
    assert client.get("/chat/").status_code == 403

    client.login(email="ali@alpha.test", password="demo12345")
    assert client.get("/chat/").status_code == 200


@pytest.mark.django_db
def test_chat_saves_messages_and_a_run_and_shows_history(client, monkeypatch):
    monkeypatch.setattr(agent_services, "run_chat", fake_answer)
    client.login(email="ali@alpha.test", password="demo12345")

    response = client.post("/chat/send/", {"question": "What is my notice period?"})

    html = response.content.decode()
    assert response.status_code == 200
    assert "30 days [1]." in html
    assert "page 2" in html
    assert Message.objects.count() == 2
    run = AgentRun.objects.get()
    assert run.route == "lease"
    assert run.status == "ok"
    # The history is still there when the page is loaded again.
    assert "What is my notice period?" in client.get("/chat/").content.decode()


@pytest.mark.django_db
def test_one_tenant_cannot_see_anothers_conversation(client, monkeypatch):
    monkeypatch.setattr(agent_services, "run_chat", fake_answer)
    client.login(email="ali@alpha.test", password="demo12345")
    client.post("/chat/send/", {"question": "A private question from Ali"})
    client.logout()

    client.login(email="sara@alpha.test", password="demo12345")
    html = client.get("/chat/").content.decode()

    assert "A private question from Ali" not in html


@pytest.mark.django_db
def test_agent_failure_gives_a_polite_reply_and_an_error_run(client, monkeypatch):

    def broken(**kwargs):
        raise RuntimeError("model is down")

    monkeypatch.setattr(agent_services, "run_chat", broken)
    client.login(email="ali@alpha.test", password="demo12345")

    response = client.post("/chat/send/", {"question": "Hello?"})

    assert agent_services.UNAVAILABLE in response.content.decode()
    run = AgentRun.objects.get()
    assert run.status == "error"
    assert "model is down" in run.error
