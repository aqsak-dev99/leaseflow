"""Records what an agent run did, step by step, so it can be inspected later."""

import time


class Trace:
    def __init__(self):
        self.started = time.monotonic()
        self.steps = []
        self.input_tokens = 0
        self.output_tokens = 0

    def add(self, kind, name, started, detail=None, input_tokens=0, output_tokens=0):
        self.steps.append(
            {
                "type": kind,
                "name": name,
                "ms": int((time.monotonic() - started) * 1000),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "detail": detail or {},
            }
        )
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens

    def add_model_call(self, name, started, reply, detail=None):
        usage = getattr(reply, "usage_metadata", None) or {}
        self.add(
            "model",
            name,
            started,
            detail,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )

    def elapsed_ms(self):
        return int((time.monotonic() - self.started) * 1000)
