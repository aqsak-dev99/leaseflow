"""Entry point for chat: saves the messages, runs the agents, records the trace."""

import logging

from .graph import run_chat
from .models import AgentRun, Conversation, Message
from .tracing import Trace

logger = logging.getLogger(__name__)

UNAVAILABLE = "Sorry, the assistant is unavailable right now. Please try again in a minute."
HISTORY_LIMIT = 10


def current_conversation(user):
    """The user's most recent conversation, created if they have none."""
    conversation = (
        Conversation.objects.for_org(user.organization).filter(user=user).order_by("-id").first()
    )
    if conversation is None:
        conversation = start_conversation(user)
    return conversation


def start_conversation(user):
    return Conversation.objects.create(organization=user.organization, user=user)


def handle_message(*, user, text):
    """Store the user's message, get the agents' reply, and store that with its trace."""
    conversation = current_conversation(user)
    earlier = list(conversation.messages.order_by("-id")[:HISTORY_LIMIT])
    history = [(message.role, message.content) for message in reversed(earlier)]

    if not conversation.title:
        conversation.title = text[:120]
        conversation.save(update_fields=["title"])
    user_message = Message.objects.create(
        organization=user.organization,
        conversation=conversation,
        role=Message.Role.USER,
        content=text,
    )

    trace = Trace()
    status, error = AgentRun.Status.OK, ""
    try:
        result = run_chat(user=user, text=text, history=history, trace=trace)
    except Exception as exc:
        logger.exception("Agent run failed")
        result = {"route": "", "answer": UNAVAILABLE, "citations": []}
        status, error = AgentRun.Status.ERROR, str(exc)[:500]

    run = AgentRun.objects.create(
        organization=user.organization,
        conversation=conversation,
        trigger=AgentRun.Trigger.CHAT,
        route=result["route"],
        status=status,
        input_tokens=trace.input_tokens,
        output_tokens=trace.output_tokens,
        latency_ms=trace.elapsed_ms(),
        steps=trace.steps,
        error=error,
    )
    reply = Message.objects.create(
        organization=user.organization,
        conversation=conversation,
        role=Message.Role.ASSISTANT,
        content=result["answer"],
        citations=result["citations"],
        run=run,
    )
    return user_message, reply
