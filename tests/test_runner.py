"""Runner behaviour against stub clients. No network, no API key, no waiting:
`sleep` is injected, so backoff waits are recorded rather than slept."""

import asyncio
import time
from types import SimpleNamespace

import pytest

from bench import registry, runner
from tests.stubs import StubClient, StubStatusError, err_action, ok_action

MODEL = next(iter(registry.MODELS))  # registry-sourced; never typed here


def test_success_row_carries_the_verified_request_shape():
    client = StubClient([ok_action()])
    row = runner.one_call(MODEL, "a prompt", client=client)
    assert row["model"] == MODEL
    assert row["error_code"] is None
    assert row["attempts"] == 1 and row["retried"] is False
    assert row["reasoning_effort"] == "low"
    assert row["text"] == "नमस्ते दुनिया"
    assert row["finish_reason"] == "stop"
    assert row["prompt_tokens"] == 37 and row["completion_tokens"] == 11
    assert row["cached_tokens"] == 0
    assert row["ttft_ms"] >= 0
    assert row["total_ms"] >= row["ttft_ms"]
    entry = registry.MODELS[MODEL]
    assert row["cost_inr"] == round(37 / 1e6 * entry["in"] + 11 / 1e6 * entry["out"], 6)
    # The verified request shape: streaming with usage, no temperature, a 1500 budget.
    sent = client.calls[0]
    assert sent["stream"] is True
    assert sent["stream_options"] == {"include_usage": True}
    assert sent["max_tokens"] == 1500
    assert sent["reasoning_effort"] == "low"
    assert "temperature" not in sent
    assert sent["messages"] == [{"role": "user", "content": "a prompt"}]


def test_missing_usage_block_means_nulls_never_estimates():
    client = StubClient([ok_action(usage=None)])
    row = runner.one_call(MODEL, "p", client=client)
    assert row["text"] == "नमस्ते दुनिया"
    assert row["finish_reason"] == "stop"
    assert row["prompt_tokens"] is None
    assert row["completion_tokens"] is None
    assert row["cached_tokens"] is None
    assert row["cost_inr"] is None


def test_cached_tokens_bill_at_the_cached_rate():
    client = StubClient([ok_action(usage=(1000, 500, 400))])
    row = runner.one_call(MODEL, "p", client=client)
    entry = registry.MODELS[MODEL]
    expected = round(600 / 1e6 * entry["in"] + 400 / 1e6 * entry["cached"]
                     + 500 / 1e6 * entry["out"], 6)
    assert row["cached_tokens"] == 400
    assert row["cost_inr"] == expected


def test_429_retries_with_exponential_backoff_then_succeeds():
    client = StubClient([
        err_action(429, "rate_limit_exceeded_error"),
        err_action(429, "rate_limit_exceeded_error"),
        ok_action(),
    ])
    waits = []
    row = runner.one_call(MODEL, "p", client=client, sleep=waits.append)
    assert row["error_code"] is None
    assert row["attempts"] == 3 and row["retried"] is True
    assert waits == [1.0, 2.0]


def test_retry_after_header_is_honoured_over_the_backoff_curve():
    client = StubClient([
        err_action(429, "model_rate_limit_exceeded_error", retry_after=7),
        ok_action(),
    ])
    waits = []
    row = runner.one_call(MODEL, "p", client=client, sleep=waits.append)
    assert waits == [7.0]
    assert row["attempts"] == 2 and row["error_code"] is None


def test_exhausted_429_is_still_a_row_with_its_error_code():
    client = StubClient([err_action(429, "model_rate_limit_exceeded_error")])
    waits = []
    row = runner.one_call(MODEL, "p", client=client, sleep=waits.append)
    assert row["error_code"] == "429 model_rate_limit_exceeded_error"
    assert row["attempts"] == 4 and row["retried"] is True
    assert waits == [1.0, 2.0, 4.0]
    assert row["prompt_tokens"] is None and row["completion_tokens"] is None
    assert row["cost_inr"] is None
    assert row["text"] == "" and row["finish_reason"] is None


def test_503_retries_then_succeeds():
    client = StubClient([err_action(503, "model_overloaded"), ok_action()])
    row = runner.one_call(MODEL, "p", client=client, sleep=lambda s: None)
    assert row["error_code"] is None
    assert row["attempts"] == 2 and row["retried"] is True


@pytest.mark.parametrize("status,code", [
    (402, "insufficient_quota_error"),
    (403, "invalid_api_key_error"),
])
def test_wallet_and_key_errors_are_never_retried(status, code):
    client = StubClient([err_action(status, code)])
    row = runner.one_call(MODEL, "p", client=client, sleep=lambda s: None)
    assert row["attempts"] == 1 and row["retried"] is False
    assert row["reasoning_effort"] == "low"
    assert row["error_code"] == f"{status} {code}"
    assert row["prompt_tokens"] is None and row["cost_inr"] is None


def test_400_on_reasoning_effort_is_probed_once_without_the_field():
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if "reasoning_effort" in kwargs:
            raise StubStatusError(400, "reasoning_effort_not_supported")
        return ok_action()["chunks"]

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    row = runner.one_call(MODEL, "p", client=client)
    assert row["error_code"] is None
    assert row["reasoning_effort"] is None
    assert row["attempts"] == 2 and row["retried"] is True
    assert len(calls) == 2
    assert "reasoning_effort" in calls[0]
    assert "reasoning_effort" not in calls[1]
    assert row["prompt_tokens"] == 37


def test_400_that_persists_is_one_row_with_the_error_code():
    client = StubClient([err_action(400, "invalid_request_error")])
    row = runner.one_call(MODEL, "p", client=client, sleep=lambda s: None)
    assert row["attempts"] == 2          # one probe without reasoning_effort, no more
    assert row["reasoning_effort"] is None
    assert row["error_code"] == "400 invalid_request_error"
    assert row["cost_inr"] is None


def test_missing_api_key_is_a_clean_local_error(monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as caught:
        runner.one_call(MODEL, "p")
    assert "SARVAM_API_KEY" in str(caught.value)


# -- the fan-out ---------------------------------------------------------------


def test_run_all_bounds_concurrency_at_three():
    inflight = []
    peaks = []

    def create(**kwargs):
        inflight.append(1)
        peaks.append(len(inflight))
        time.sleep(0.05)
        inflight.pop()
        return ok_action()["chunks"]

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    models = list(registry.MODELS)[:2]
    prompts = [("p1", "t1"), ("p2", "t2"), ("p3", "t3")]
    rows, stop_reason = asyncio.run(runner.run_all(models, prompts, client=client))
    assert stop_reason is None
    assert len(rows) == 6
    assert {r["prompt_id"] for r in rows} == {"p1", "p2", "p3"}
    assert {r["model"] for r in rows} == set(models)
    assert max(peaks) <= 3
    assert max(peaks) >= 2      # it really did run in parallel


def test_run_all_at_concurrency_one_never_overlaps():
    inflight = []
    peaks = []

    def create(**kwargs):
        inflight.append(1)
        peaks.append(len(inflight))
        time.sleep(0.01)
        inflight.pop()
        return ok_action()["chunks"]

    client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    models = list(registry.MODELS)[:2]
    prompts = [("p1", "t1"), ("p2", "t2")]
    rows, _ = asyncio.run(
        runner.run_all(models, prompts, client=client, concurrency=1))
    assert len(rows) == 4
    assert max(peaks) == 1


def test_run_all_stops_the_run_on_402():
    # hold_s puts all three in flight before the first 402 lands, which is
    # what real latency guarantees; an instant stub lets the first call
    # finish before the others even acquire the semaphore.
    client = StubClient([err_action(402, "insufficient_quota_error", hold_s=0.05)])
    models = list(registry.MODELS)[:2]
    prompts = [("p1", "t1"), ("p2", "t2"), ("p3", "t3")]
    rows, stop_reason = asyncio.run(
        runner.run_all(models, prompts, client=client, concurrency=3))
    assert stop_reason == "402 insufficient_quota_error"
    # The three calls already in flight produced rows; nothing else was sent.
    assert len(rows) == 3
    assert len(client.calls) == 3
    for row in rows:
        assert row["error_code"] == "402 insufficient_quota_error"
        assert row["attempts"] == 1
