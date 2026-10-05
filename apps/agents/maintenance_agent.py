"""The maintenance agent: a model that can call ticket tools on the tenant's behalf."""

from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from apps.core.ai import get_chat_model

from .tool_loop import GAVE_UP, history_messages, run_tool_loop
from .tools.maintenance import build_maintenance_tools

__all__ = ["GAVE_UP", "run_maintenance_agent"]

PROMPT = (Path(__file__).parent / "prompts" / "maintenance_agent.md").read_text()


def run_maintenance_agent(*, user, text, history=(), trace=None):
    tools = build_maintenance_tools(user)
    model = get_chat_model().bind_tools(tools)
    messages = [SystemMessage(PROMPT), *history_messages(history), HumanMessage(text)]
    return run_tool_loop(
        model=model, tools=tools, messages=messages, name="maintenance_agent", trace=trace
    )
