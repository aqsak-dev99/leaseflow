"""The supervisor graph: decide which agent handles a message, then run it."""

import time
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from apps.core.ai import get_chat_model

from .lease_agent import answer_lease_question
from .maintenance_agent import run_maintenance_agent
from .payment_agent import run_payment_agent
from .text import text_of

SUPERVISOR_PROMPT = (Path(__file__).parent / "prompts" / "supervisor.md").read_text()
OUT_OF_SCOPE = (
    "I can help with questions about your lease and building rules, with reporting or "
    "checking maintenance problems, and with your rent balance and payments. "
    "What would you like to do?"
)
ROUTES = ("lease", "maintenance", "payment", "other")


class ChatState(TypedDict, total=False):
    user: object
    text: str
    history: list
    trace: object
    route: str
    answer: str
    citations: list


def _parse_route(reply_text):
    reply_text = reply_text.lower()
    for route in ROUTES:
        if route in reply_text:
            return route
    return "other"


def supervisor(state):
    recent = "\n".join(f"{role}: {content}" for role, content in state.get("history", [])[-4:])
    prompt = (
        f"Recent conversation:\n{recent or '(none)'}\n\n"
        f"New message from tenant:\n{state['text']}"
    )
    started = time.monotonic()
    reply = get_chat_model().invoke([("system", SUPERVISOR_PROMPT), ("human", prompt)])
    route = _parse_route(text_of(reply.content))
    trace = state.get("trace")
    if trace is not None:
        trace.add_model_call("supervisor", started, reply, {"route": route})
    return {"route": route}


def lease_node(state):
    return answer_lease_question(
        user=state["user"], question=state["text"], trace=state.get("trace")
    )


def maintenance_node(state):
    return run_maintenance_agent(
        user=state["user"],
        text=state["text"],
        history=state.get("history", []),
        trace=state.get("trace"),
    )


def payment_node(state):
    return run_payment_agent(
        user=state["user"],
        text=state["text"],
        history=state.get("history", []),
        trace=state.get("trace"),
    )


def other_node(state):
    return {"answer": OUT_OF_SCOPE, "citations": []}


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("supervisor", supervisor)
    graph.add_node("lease", lease_node)
    graph.add_node("maintenance", maintenance_node)
    graph.add_node("payment", payment_node)
    graph.add_node("other", other_node)
    graph.add_edge(START, "supervisor")
    graph.add_conditional_edges(
        "supervisor", lambda state: state["route"], {route: route for route in ROUTES}
    )
    for route in ROUTES:
        graph.add_edge(route, END)
    return graph.compile()


chat_graph = build_graph()


def run_chat(*, user, text, history=(), trace=None):
    """Route one tenant message and return the route, the answer and any citations."""
    result = chat_graph.invoke(
        {"user": user, "text": text, "history": list(history), "trace": trace}
    )
    return {
        "route": result["route"],
        "answer": result["answer"],
        "citations": result.get("citations", []),
    }
