"""The loop shared by agents that use tools: ask the model, run any tools it asks for, repeat."""

import time

from langchain_core.messages import ToolMessage

from .text import text_of

MAX_TURNS = 4
GAVE_UP = "I couldn't finish that. Please try again, or describe what you need in one message."


def run_tool_loop(*, model, tools, messages, name, trace=None):
    by_name = {tool.name: tool for tool in tools}
    for _ in range(MAX_TURNS):
        started = time.monotonic()
        reply = model.invoke(messages)
        if trace is not None:
            trace.add_model_call(name, started, reply)
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
                    "tool", call["name"], started, {"args": call["args"], "result": result[:300]}
                )
            messages.append(ToolMessage(content=result, tool_call_id=call["id"]))

    return {"answer": GAVE_UP, "citations": []}


def history_messages(history):
    from langchain_core.messages import AIMessage, HumanMessage

    return [
        HumanMessage(content) if role == "user" else AIMessage(content)
        for role, content in history
    ]
