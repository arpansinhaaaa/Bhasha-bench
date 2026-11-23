"""Stub clients for the runner and CLI tests: no network, no key, no waiting."""

import time
from types import SimpleNamespace


class StubStatusError(Exception):
    """Mimics what the runner reads off an OpenAI APIStatusError."""

    def __init__(self, status_code, code=None, retry_after=None):
        super().__init__(f"stub HTTP {status_code}")
        self.status_code = status_code
        self.body = {"error": {"code": code}} if code else None
        headers = {} if retry_after is None else {"Retry-After": str(retry_after)}
        self.response = SimpleNamespace(headers=headers)


def chunk(content=None, finish_reason=None, usage=None):
    """A streaming chunk: choices carry delta/finish_reason, or usage only."""
    choices = []
    if content is not None or finish_reason is not None:
        choices = [SimpleNamespace(
            delta=SimpleNamespace(content=content),
            finish_reason=finish_reason,
        )]
    return SimpleNamespace(choices=choices, usage=usage)


def usage_block(prompt_tokens, completion_tokens, cached_tokens=0):
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
    )


def ok_action(text_parts=("नमस्ते", " दुनिया"), usage=(37, 11), finish="stop",
              hold_s=0.0):
    """A successful streaming response: some deltas, a finish, a usage block."""
    chunks = [chunk(content=part) for part in text_parts]
    chunks.append(chunk(finish_reason=finish))
    if usage is not None:
        chunks.append(chunk(usage=usage_block(*usage)))
    return {"chunks": chunks, "hold_s": hold_s}


def err_action(status, code=None, retry_after=None, hold_s=0.0):
    """An HTTP error raised after an optional artificial delay."""
    return {"status": status, "code": code, "retry_after": retry_after,
            "hold_s": hold_s}


class StubClient:
    """chat.completions.create(**kwargs) from a script of actions.

    A one-action script repeats forever (safe under the concurrent fan-out);
    a longer script is consumed in order (single-call tests only).
    """

    def __init__(self, script):
        self.script = [dict(action) for action in script]
        self.calls = []
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(kwargs)
        action = self.script[0] if len(self.script) == 1 else self.script.pop(0)
        hold_s = action.get("hold_s", 0.0)
        if hold_s:
            time.sleep(hold_s)
        if "chunks" in action:
            return action["chunks"]
        raise StubStatusError(action["status"], action.get("code"),
                               action.get("retry_after"))
