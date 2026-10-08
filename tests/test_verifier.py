from types import SimpleNamespace

import pytest

from apps.accounts.models import User
from apps.agents import lease_agent, verifier
from apps.agents.tracing import Trace


def fake_chunk(title, page, text):
    return SimpleNamespace(document=SimpleNamespace(title=title), page_number=page, text=text)


class FakeModel:
    """Gives the prepared replies in order: first the answer, then the verifier's verdict."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return SimpleNamespace(
            content=self.replies.pop(0), usage_metadata={"input_tokens": 100, "output_tokens": 5}
        )


CHUNKS = [
    fake_chunk("Lease agreement, unit A1", 2, "Notice period is 30 days."),
    fake_chunk("Lease agreement, unit A1", 3, "Pets are not allowed."),
]


def ask(monkeypatch, *replies):
    """Run the lease agent for Ali with a stand-in model. Returns result, model and trace."""
    model = FakeModel(*replies)
    monkeypatch.setattr(lease_agent, "search_chunks", lambda **kwargs: CHUNKS)
    monkeypatch.setattr(lease_agent, "get_chat_model", lambda: model)
    trace = Trace()
    result = lease_agent.answer_lease_question(
        user=User.objects.get(email="ali@alpha.test"), question="Can I keep a dog?", trace=trace
    )
    return result, model, trace


@pytest.mark.parametrize(
    "reply,expected",
    [
        ("SUPPORTED", verifier.SUPPORTED),
        ("supported.", verifier.SUPPORTED),
        ("UNSUPPORTED", verifier.UNSUPPORTED),
        ("Not supported by the source", verifier.UNSUPPORTED),
        ("I think it is fine", verifier.UNSUPPORTED),
        ("", verifier.UNSUPPORTED),
    ],
)
def test_verdict_is_supported_only_when_the_checker_clearly_says_so(reply, expected):
    assert verifier.parse_verdict(reply) == expected


@pytest.mark.django_db
def test_supported_answer_is_shown_with_its_citations(monkeypatch):
    result, model, trace = ask(monkeypatch, "Pets are not allowed [2].", "SUPPORTED")

    assert result["answer"] == "Pets are not allowed [2]."
    assert [c["page"] for c in result["citations"]] == [3]
    # The checker sees only the cited source, not everything that was retrieved.
    checked = model.calls[1][1][1]
    assert "Pets are not allowed." in checked
    assert "Notice period is 30 days." not in checked


@pytest.mark.django_db
def test_unsupported_answer_is_replaced_and_kept_in_the_trace(monkeypatch):
    result, model, trace = ask(monkeypatch, "Yes, small dogs are fine [2].", "UNSUPPORTED")

    assert result == {"answer": lease_agent.NOT_FOUND, "citations": []}
    assert trace.steps[-1]["name"] == "verifier"
    assert trace.steps[-1]["detail"] == {
        "verdict": "unsupported",
        "answer": "Yes, small dogs are fine [2].",
    }


@pytest.mark.django_db
def test_answer_without_a_citation_is_blocked_without_a_second_model_call(monkeypatch):
    result, model, trace = ask(monkeypatch, "Yes, dogs are usually allowed in flats.")

    assert result == {"answer": lease_agent.NOT_FOUND, "citations": []}
    assert len(model.calls) == 1
    assert trace.steps[-1]["type"] == "check"
    assert trace.steps[-1]["detail"]["verdict"] == "no_citation"


@pytest.mark.django_db
def test_answer_citing_a_source_it_was_not_given_is_blocked(monkeypatch):
    result, model, trace = ask(monkeypatch, "Pets are not allowed [2], see also [7].")

    assert result == {"answer": lease_agent.NOT_FOUND, "citations": []}
    assert len(model.calls) == 1
    assert trace.steps[-1]["detail"]["verdict"] == "bad_citation"


@pytest.mark.django_db
def test_nothing_is_verified_when_no_lease_text_was_found(monkeypatch):
    monkeypatch.setattr(lease_agent, "search_chunks", lambda **kwargs: [])
    trace = Trace()

    result = lease_agent.answer_lease_question(
        user=User.objects.get(email="ali@alpha.test"), question="Can I keep a dog?", trace=trace
    )

    assert result["answer"] == lease_agent.NOT_FOUND
    assert [step["name"] for step in trace.steps] == ["search_lease_documents"]
