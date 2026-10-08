"""Checks a lease answer against the sources it cites, before the tenant sees it.

Two checks, cheapest first:
1. A code check: the answer must cite at least one source, and only sources it was given.
2. A second model call: do the cited sources really say what the answer claims?

An answer that fails either check is never shown. The check runs once; there is no retry.
"""

import re
import time
from pathlib import Path

from .text import text_of

PROMPT = (Path(__file__).parent / "prompts" / "verifier.md").read_text()

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
NO_CITATION = "no_citation"
BAD_CITATION = "bad_citation"


def cited_numbers(answer):
    """The source numbers an answer cites, such as [1] and [3], in order."""
    return sorted({int(number) for number in re.findall(r"\[(\d+)\]", answer)})


def parse_verdict(reply_text):
    """Turn the checker's reply into a verdict. Anything unclear counts as unsupported."""
    reply_text = reply_text.upper()
    if "UNSUPPORTED" in reply_text or "NOT SUPPORTED" in reply_text:
        return UNSUPPORTED
    if "SUPPORTED" in reply_text:
        return SUPPORTED
    return UNSUPPORTED


def verify_answer(*, question, answer, citations, source_count, model, trace=None):
    """Return SUPPORTED only if the answer is backed by the sources it cites."""
    started = time.monotonic()
    numbers = cited_numbers(answer)
    verdict = None
    if not numbers:
        verdict = NO_CITATION
    elif any(number < 1 or number > source_count for number in numbers):
        verdict = BAD_CITATION
    if verdict is not None:
        if trace is not None:
            trace.add("check", "verifier", started, {"verdict": verdict, "answer": answer})
        return verdict

    sources = "\n\n".join(
        f"[{citation['number']}] ({citation['title']}, page {citation['page']})\n"
        f"{citation['text']}"
        for citation in citations
    )
    messages = [
        ("system", PROMPT),
        ("human", f"Question: {question}\n\nSources:\n{sources}\n\nAnswer to check:\n{answer}"),
    ]
    reply = model.invoke(messages)
    verdict = parse_verdict(text_of(reply.content))
    if trace is not None:
        detail = {"verdict": verdict}
        if verdict != SUPPORTED:
            detail["answer"] = answer
        trace.add_model_call("verifier", started, reply, detail)
    return verdict
