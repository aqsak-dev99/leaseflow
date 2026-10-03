"""The lease agent: retrieve the relevant lease text, then answer with citations."""

import re
import time
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from apps.core.ai import get_chat_model
from apps.documents.retrieval import search_chunks
from apps.properties.models import Lease

from .text import text_of

PROMPT = (Path(__file__).parent / "prompts" / "lease_agent.md").read_text()
NOT_FOUND = "I can't find that in your lease documents."
NO_LEASE = "You don't have an active lease on file, so I can't answer lease questions yet."


class LeaseState(TypedDict, total=False):
    question: str
    organization: object
    lease: object
    trace: object
    chunks: list
    answer: str
    citations: list


def retrieve(state):
    started = time.monotonic()
    chunks = search_chunks(
        organization=state["organization"],
        lease=state["lease"],
        query=state["question"],
        limit=4,
    )
    trace = state.get("trace")
    if trace is not None:
        results = [
            {
                "title": chunk.document.title,
                "page": chunk.page_number,
                "distance": round(float(getattr(chunk, "distance", 0) or 0), 3),
            }
            for chunk in chunks
        ]
        trace.add(
            "retrieval",
            "search_lease_documents",
            started,
            {"query": state["question"], "results": results},
        )
    return {"chunks": chunks}


def generate(state):
    chunks = state["chunks"]
    if not chunks:
        return {"answer": NOT_FOUND, "citations": []}

    sources = "\n\n".join(
        f"[{number}] ({chunk.document.title}, page {chunk.page_number})\n{chunk.text}"
        for number, chunk in enumerate(chunks, 1)
    )
    messages = [
        ("system", PROMPT),
        ("human", f"Sources:\n{sources}\n\nQuestion: {state['question']}"),
    ]
    started = time.monotonic()
    reply = get_chat_model().invoke(messages)
    answer = text_of(reply.content)
    trace = state.get("trace")
    if trace is not None:
        trace.add_model_call("lease_agent", started, reply)

    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    citations = [
        {
            "number": number,
            "title": chunks[number - 1].document.title,
            "page": chunks[number - 1].page_number,
            "text": chunks[number - 1].text,
        }
        for number in cited
        if 1 <= number <= len(chunks)
    ]
    return {"answer": answer, "citations": citations}


def build_graph():
    graph = StateGraph(LeaseState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


lease_graph = build_graph()


def answer_lease_question(*, user, question, trace=None):
    """Answer a tenant's question from their own lease. Returns answer and citations."""
    lease = (
        Lease.objects.for_org(user.organization)
        .filter(tenant=user, status=Lease.Status.ACTIVE)
        .first()
    )
    if lease is None:
        return {"answer": NO_LEASE, "citations": []}
    result = lease_graph.invoke(
        {
            "question": question,
            "organization": user.organization,
            "lease": lease,
            "trace": trace,
        }
    )
    return {"answer": result["answer"], "citations": result["citations"]}
