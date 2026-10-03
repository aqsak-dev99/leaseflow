"""The maintenance agent: a model that can call ticket tools on the tenant's behalf."""

import time
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from apps.core.ai import get_chat_model

from .text import text_of
from .tools.maintenance import build_maintenance_tools

PROMPT = (Path(__file__).parent / "prompts" / "maintenance_agent.md").read_text()
MAX_TURNS = 4
GAVE_UP = "I couldn't finish that. Please try again, or describe the problem in one message."


def _history_messages(history):
    messages = []
    for role, content in history:
        messages.append(HumanMessage(content) if role == "user" else AIMessage(content))
    return messages


def run_maintenance_agent(*, user, text, history=(), trace=None):
    tools = build_maintenance_tools(user)
    by_name = {tool.name: tool for tool in tools}
    model = get_chat_model().bind_tools(tools)
    messages = [SystemMessage(PROMPT), *_history_messages(history), HumanMessage(text)]

    for _ in range(MAX_TURNS):
        started = time.monotonic()
        reply = model.invoke(messages)
        if trace is not None:
            trace.add_model_call("maintenance_agent", started, reply)
        messages.append(reply)

        tool_calls = getattr(reply, "tool_calls", None) or []
        if not tool_calls:
            return {"answer": text_of(reply.content) or GAVE_UP, "citations": []}

        for call in tool_calls:
            started = time.monotonic()
            tool = by_name.get(call["name"])
            if tool is None:
                result = f"Error: there is no tool called {call['name']}."
            else:
                try:
                    result = str(tool.invoke(call["args"]))
                except Exception as exc:
                    result = f"Error: {exc}"
            if trace is not None:
                trace.add(
                    "tool",
                    call["name"],
                    started,
                    {"args": call["args"], "result": result[:300]},
                )
            messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

    return {"answer": GAVE_UP, "citations": []}
