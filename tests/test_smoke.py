"""The smoke checker's criteria, on fabricated rows. No network, no key."""

from bench import registry, smoke
from bench.store import RunStore

MODEL = next(iter(registry.MODELS))  # registry-sourced; never typed here


def _row(**overrides):
    row = {
        "run_id": "2026-11-20T150000",
        "model": MODEL,
        "prompt_id": "hi-1",
        "reasoning_effort": "low",
        "ttft_ms": 412,
        "total_ms": 1800,
        "text": "एक वस्तु का विक्रय मूल्य ₹172.50 है।",
        "prompt_tokens": 120,
        "completion_tokens": 80,
        "cached_tokens": 0,
        "cost_inr": registry.cost_inr(MODEL, 120, 80),
        "finish_reason": "stop",
        "error_code": None,
        "retried": False,
        "attempts": 1,
    }
    row.update(overrides)
    return row


def test_a_good_row_passes_every_criterion():
    assert smoke.check_row(_row()) == []


def test_zero_ttft_or_short_total_fails():
    failures = smoke.check_row(_row(ttft_ms=0))
    assert any("ttft_ms" in f for f in failures)
    failures = smoke.check_row(_row(total_ms=100))
    assert any("total_ms" in f for f in failures)


def test_missing_usage_is_not_smoothed_over():
    failures = smoke.check_row(_row(prompt_tokens=None, completion_tokens=None,
                                    cost_inr=None))
    assert any("usage block missing" in f for f in failures)


def test_wrong_script_or_missing_amount_fails():
    failures = smoke.check_row(_row(text="The selling price is Rs 172.50."))
    assert any("Devanagari" in f for f in failures)
    failures = smoke.check_row(_row(text="उत्तर बताया नहीं गया।"))
    assert any("172" in f for f in failures)


def test_truncation_and_errors_are_not_a_pass():
    failures = smoke.check_row(_row(finish_reason="length"))
    assert any("finish_reason" in f for f in failures)
    failures = smoke.check_row(_row(error_code="500 model_overloaded"))
    assert any("error_code" in f for f in failures)


def test_cost_mismatch_fails():
    failures = smoke.check_row(_row(cost_inr=0.5))
    assert any("cost_inr" in f for f in failures)


def test_main_checks_the_newest_run(tmp_path, capsys):
    stale = RunStore.create(base=tmp_path)
    with stale:
        stale.append_row(_row(run_id=stale.run_id, ttft_ms=0))   # would fail
    newest = RunStore.create(base=tmp_path)
    with newest:
        newest.append_row(_row(run_id=newest.run_id))

    rc = smoke.main([str(tmp_path)])
    out = capsys.readouterr().out
    # rc == 0 proves it picked the newest run; the stale row would have failed.
    assert rc == 0
    assert "PASS" in out
    assert newest.run_id in out


def test_main_exits_nonzero_when_the_criteria_fail(tmp_path, capsys):
    run = RunStore.create(base=tmp_path)
    with run:
        run.append_row(_row(run_id=run.run_id, ttft_ms=0, finish_reason="length"))
    rc = smoke.main([str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAIL" in out


def test_main_with_no_runs_at_all(tmp_path, capsys):
    rc = smoke.main([str(tmp_path)])
    assert rc == 2
    assert "no runs found" in capsys.readouterr().err
