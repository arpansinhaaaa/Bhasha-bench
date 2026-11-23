"""One streaming chat completion per call, with retry, backoff and fan-out.

The request shape follows Sarvam's Chat Completions V2 API: the OpenAI SDK
against https://api.sarvam.ai/v2, streaming always, with
stream_options={"include_usage": True} so token counts are real, max_tokens
1500 (it counts reasoning tokens), reasoning_effort "low" by default, and
temperature never set.

Retry policy: 429 and 503 only, at most 4 attempts, exponential
backoff (1 s, 2 s, 4 s), honouring Retry-After when the server sends it.
400, 402 and 403 are never retried as status errors - but a 400 gets exactly
one probe without `reasoning_effort`, since some models reject the field,
and the row then records reasoning_effort: null. A call that fails is still
returned as a row carrying its error code; it is never dropped.

Model IDs and prices come from bench.registry; none are typed here.
"""

from __future__ import annotations

import asyncio
import os
import time

from openai import OpenAI

from bench import registry

BASE_URL = "https://api.sarvam.ai/v2"
MAX_ATTEMPTS = 4
RETRYABLE_STATUSES = frozenset({429, 503})
STOP_RUN_STATUSES = frozenset({402, 403})  # wallet / key: the run stops
BACKOFF_BASE_S = 1.0


def _default_client() -> OpenAI:
    try:
        api_key = os.environ["SARVAM_API_KEY"]
    except KeyError:
        raise RuntimeError(
            "SARVAM_API_KEY is not set. Export it in your shell and re-run."
        ) from None
    return OpenAI(base_url=BASE_URL, api_key=api_key)


def one_call(model: str, prompt: str, *, client=None, max_tokens: int = 1500,
             reasoning_effort: str | None = "low",
             sleep=time.sleep) -> dict:
    """Send one prompt to one model, streaming, and return a result row.

    The row is returned whether the call succeeded or failed. `client`
    (anything exposing chat.completions.create(**kwargs)) and `sleep` are
    injectable, so tests run without network, key or real waiting.
    """
    if client is None:
        client = _default_client()
    t0 = time.perf_counter()
    effort = reasoning_effort
    attempts = 0
    while True:
        attempts += 1
        kwargs = dict(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,          # counts reasoning tokens
            stream=True,
            stream_options={"include_usage": True},
        )
        if effort:
            kwargs["reasoning_effort"] = effort
        try:
            stream = client.chat.completions.create(**kwargs)
            return _row_from_stream(
                stream, model=model, effort=effort, t0=t0, attempts=attempts
            )
        except Exception as exc:
            # Every failure becomes a row; nothing here kills the run.
            status = getattr(exc, "status_code", None)
            if status == 400 and effort is not None:
                # Some models 400 on reasoning_effort. Retry once without
                # the field; the row records reasoning_effort: null.
                effort = None
                continue
            if status in RETRYABLE_STATUSES and attempts < MAX_ATTEMPTS:
                sleep(_wait_seconds(exc, attempts))
                continue
            return _error_row(model=model, effort=effort, t0=t0,
                              attempts=attempts, exc=exc)


def _row_from_stream(stream, *, model, effort, t0, attempts) -> dict:
    """Consume the stream and assemble the row."""
    ttft_ms, text, usage, finish = None, [], None, None
    for chunk in stream:
        if chunk.choices:
            delta = chunk.choices[0].delta.content
            if delta:
                if ttft_ms is None:
                    ttft_ms = (time.perf_counter() - t0) * 1000
                text.append(delta)
            if chunk.choices[0].finish_reason:
                finish = chunk.choices[0].finish_reason
        if getattr(chunk, "usage", None):
            usage = chunk.usage
    prompt_tokens = usage.prompt_tokens if usage else None
    completion_tokens = usage.completion_tokens if usage else None
    cached_tokens = _cached_tokens(usage)
    # Cost from the API's own token counts times the dated registry price.
    # No usage block means nulls, never estimates from character counts.
    cost_inr = (
        registry.cost_inr(model, prompt_tokens, completion_tokens, cached_tokens)
        if usage else None
    )
    return {
        "model": model,
        "reasoning_effort": effort,
        "ttft_ms": round(ttft_ms or -1),
        "total_ms": round((time.perf_counter() - t0) * 1000),
        "text": "".join(text),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cached_tokens": cached_tokens,
        "cost_inr": cost_inr,
        "finish_reason": finish,
        "error_code": None,
        "retried": attempts > 1,
        "attempts": attempts,
    }


def _cached_tokens(usage) -> int | None:
    """Cached input tokens as reported by the API; None when unreported."""
    if usage is None:
        return None
    details = getattr(usage, "prompt_tokens_details", None)
    return getattr(details, "cached_tokens", None) or 0


def _error_row(*, model, effort, t0, attempts, exc) -> dict:
    """A failed call is a row carrying its error code - never a dropped line."""
    return {
        "model": model,
        "reasoning_effort": effort,
        "ttft_ms": None,
        "total_ms": round((time.perf_counter() - t0) * 1000),
        "text": "",
        "prompt_tokens": None,
        "completion_tokens": None,
        "cached_tokens": None,
        "cost_inr": None,
        "finish_reason": None,
        "error_code": _error_code(exc),
        "retried": attempts > 1,
        "attempts": attempts,
    }


def _error_code(exc) -> str:
    """'<status> <server code>' when both are known, else the exception's name."""
    status = getattr(exc, "status_code", None)
    if status is None:
        return type(exc).__name__
    server = _server_code(exc)
    return f"{status} {server}" if server else str(status)


def _server_code(exc) -> str | None:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict) and error.get("code"):
            return str(error["code"])
        if body.get("code"):
            return str(body["code"])
    return None


def _wait_seconds(exc, failed_attempt: int) -> float:
    """Retry-After when the server sends it, else exponential backoff."""
    headers = getattr(getattr(exc, "response", None), "headers", None)
    if headers is not None:
        raw = headers.get("Retry-After")
        if raw is None and isinstance(headers, dict):
            raw = headers.get("retry-after")
        if raw is not None:
            try:
                return max(float(raw), 0.0)
            except ValueError:
                pass  # not seconds (e.g. an HTTP date): fall back to backoff
    return BACKOFF_BASE_S * 2 ** (failed_attempt - 1)


async def run_all(models, prompts, *, client=None, concurrency=3,
                  max_tokens: int = 1500, reasoning_effort: str | None = "low",
                  on_row=None):
    """Fan one call out per (model, prompt) at the given concurrency.

    `prompts` is a list of (prompt_id, text) pairs. `on_row(row)` is called
    once per completed call, in completion order, with prompt_id attached.
    Returns (rows, stop_reason): stop_reason is the error code that halted
    the run (402 wallet / 403 key) or None. A
    call that never ran because the run stopped produces no row.
    """
    if client is None:
        client = _default_client()
    semaphore = asyncio.Semaphore(concurrency)
    stop = asyncio.Event()

    async def call(model: str, prompt_id: str, text: str):
        async with semaphore:
            if stop.is_set():
                return None
            row = await asyncio.to_thread(
                one_call, model, text,
                client=client, max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
            # Set the stop flag while this task still holds the semaphore,
            # so the next waiter is guaranteed to see it and never starts.
            if _status_of(row["error_code"]) in STOP_RUN_STATUSES:
                stop.set()
        row["prompt_id"] = prompt_id
        return row

    tasks = [
        asyncio.ensure_future(call(model, prompt_id, text))
        for model in models
        for prompt_id, text in prompts
    ]
    rows = []
    stop_reason = None
    for pending in asyncio.as_completed(tasks):
        row = await pending
        if row is None:
            continue
        if stop_reason is None and _status_of(row["error_code"]) in STOP_RUN_STATUSES:
            stop_reason = row["error_code"]
        if on_row is not None:
            on_row(row)
        rows.append(row)
    return rows, stop_reason


def _status_of(error_code: str | None) -> int | None:
    """The numeric status behind an error code like '429 model_overloaded'."""
    if not error_code:
        return None
    first = error_code.split(" ", 1)[0]
    return int(first) if first.isdigit() else None
