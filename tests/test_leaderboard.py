"""The leaderboard builder, PRD P8/P11, against a fake run.

No network, no API key, no live call. The fixture is four rows over two
models and two real prompts, with one error row and one truncated row; the
instruction and answer checks are deterministic functions of the prompt
spec, so every aggregate below is hand-computed from those numbers and a
regression in metrics, checks, registry or the builder breaks exactly one
named assertion. Prices are never typed here: expected costs come from
bench.registry.cost_inr, the only place a price lives.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bench import cli, leaderboard, registry, store
from bench import prompts as prompt_set

DAY = "2026-11-21"
RUN_ID = "2026-11-21T100000"
TIMESTAMP = "2026-11-21T10:00:00+05:30"
MODELS = list(registry.MODELS)[:2]          # never a typed model id


def _fake_row(model, prompt_id, *, text="", usage=None, ttft=None, total=None,
              finish="stop", error=None, retried=False, attempts=1, effort="low",
              run_id=RUN_ID):
    """A results.jsonl row in the schema the runner writes."""
    prompt_tokens, completion_tokens = usage if usage else (None, None)
    cost = None
    if usage:
        cost = registry.cost_inr(model, usage[0], usage[1])
    return {
        "run_id": run_id, "model": model, "prompt_id": prompt_id,
        "reasoning_effort": effort,
        "ttft_ms": ttft, "total_ms": total,
        "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
        "cached_tokens": 0, "cost_inr": cost,
        "text": text, "finish_reason": finish, "error_code": error,
        "retried": retried, "attempts": attempts,
    }


def _fixture_rows():
    """Four rows: good, good, errored, truncated - the honesty cases."""
    m1, m2 = MODELS
    return [
        _fake_row(m1, "hi-1", text="विक्रय मूल्य ₹172.50 है।", usage=(100, 200),
                  ttft=100, total=500),                # carries the value: correct
        _fake_row(m1, "hi-3", text="namaste duniya", usage=(50, 100),
                  ttft=200, total=800),                # one fragment, not three points
        _fake_row(m2, "hi-1", error="429 model_rate_limit_exceeded_error",
                  retried=True, attempts=4),          # a failed call is a row
        _fake_row(m2, "hi-3", text="नमस्ते", usage=(60, 1500),
                  ttft=300, total=900, finish="length"),  # deva answer, hit budget
    ]


def _write_run(base, rows, prompt_hash, run_id=RUN_ID):
    """A run directory with results.jsonl and run.json, like the runner leaves it."""
    run_dir = Path(base) / DAY / run_id
    run_dir.mkdir(parents=True)
    with open(run_dir / store.RESULTS_NAME, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (run_dir / store.METADATA_NAME).write_text(
        json.dumps({
            "run_id": run_id, "timestamp": TIMESTAMP,
            "prompt_set_hash": prompt_hash, "models": MODELS,
            "total_cost_inr": None, "reasoning_effort_fallback_models": [],
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return run_dir


@pytest.fixture
def fake_run(tmp_path):
    """A two-model, two-prompt run."""
    prompts, prompt_hash = prompt_set.load_prompts()
    run_dir = _write_run(tmp_path, _fixture_rows(), prompt_hash)
    return run_dir, prompts, prompt_hash


def _build(fake_run):
    run_dir, prompts, prompt_hash = fake_run
    return leaderboard.build_leaderboard(run_dir, prompts, prompt_hash)


# -- aggregates are hand-computed arithmetic, never estimates ----------------


def test_per_model_aggregates_match_hand_computed_values(fake_run):
    payload = _build(fake_run)
    m1, m2 = MODELS
    summary = payload["models_summary"]

    # m1: two clean cells; costs from the registry, percentiles from [100, 200].
    # hi-1 carries the value (correct, no constraints declared); hi-3 is one
    # fragment against the three-points rule.
    m1_cost = registry.cost_inr(m1, 100, 200) + registry.cost_inr(m1, 50, 100)
    assert summary[m1] == {
        "calls": 2, "errors": 0,
        "costed_cells": 2,
        "cost_inr_total": round(m1_cost, 6),
        "cost_inr_mean": round(m1_cost / 2, 6),
        "ttft_p50_ms": 150.0, "ttft_p90_ms": 190.0,
        "latency_p50_ms": 650.0,
        "fidelity_mean_pct": 100.0,
        "fidelity_labels": {"native_script": 2},
        "instructions_followed": {"passed": 1, "total": 2},
        "answers_correct": {"passed": 1, "checkable": 1},
        "truncated_cells": 0,
    }

    # m2: one error row (no measurement, no cost, nothing followed) and one
    # truncated row.
    m2_cost = registry.cost_inr(m2, 60, 1500)
    assert summary[m2] == {
        "calls": 2, "errors": 1,
        "costed_cells": 1,
        "cost_inr_total": round(m2_cost, 6),
        "cost_inr_mean": round(m2_cost, 6),
        "ttft_p50_ms": 300.0, "ttft_p90_ms": 300.0,
        "latency_p50_ms": 900.0,
        "fidelity_mean_pct": 0.0,               # deva answer to a latin ask
        "fidelity_labels": {"empty": 1, "other_script": 1},
        "instructions_followed": {"passed": 0, "total": 2},
        "answers_correct": {"passed": 0, "checkable": 1},
        "truncated_cells": 1,
    }

    total = round(m1_cost + m2_cost, 6)
    assert payload["total_cost_inr"] == total
    assert payload["missing_cells"] == 0
    assert payload["models"] == MODELS


def test_a_failed_call_stays_a_cell_and_never_a_dash(fake_run):
    payload = _build(fake_run)
    cells = {prompt["id"]: {c["model"]: c for c in prompt["cells"]}
             for prompt in payload["prompts"]}
    error_cell = cells["hi-1"][MODELS[1]]
    assert error_cell["error_code"] == "429 model_rate_limit_exceeded_error"
    assert error_cell["retried"] is True and error_cell["attempts"] == 4
    assert error_cell["text"] == "" and error_cell["cost_inr"] is None
    assert error_cell["fidelity_label"] == "empty"
    assert error_cell["answer_correct"] is False      # checkable, and absent
    assert error_cell["constraints_met"] is False

    truncated = cells["hi-3"][MODELS[1]]
    assert truncated["finish_reason"] == "length"       # the page says "hit token budget"
    assert truncated["cost_inr"] == registry.cost_inr(MODELS[1], 60, 1500)
    assert truncated["answer_correct"] is None           # hi-3 has no value to check

    assert [p["id"] for p in payload["prompts"]] == ["hi-1", "hi-3"]  # file order
    for prompt in payload["prompts"]:
        assert [c["model"] for c in prompt["cells"]] == MODELS       # run order


def test_checks_come_from_the_prompt_spec_not_from_the_answers(fake_run):
    """Every cell's two checks are recomputed from prompts.yaml, deterministically."""
    payload = _build(fake_run)
    cells = {(p["id"], c["model"]): c for p in payload["prompts"] for c in p["cells"]}
    # m1/hi-1 carries the 172.50 value and hi-1 declares no constraints.
    assert cells[("hi-1", MODELS[0])]["answer_correct"] is True
    assert cells[("hi-1", MODELS[0])]["constraints_met"] is True
    # m1/hi-3 answers in one fragment: three points fail, Devanagari is absent.
    assert cells[("hi-3", MODELS[0])]["answer_correct"] is None
    assert cells[("hi-3", MODELS[0])]["constraints_met"] is False


def test_honest_labels_travel_inside_the_payload(fake_run):
    payload = _build(fake_run)
    assert payload["run_id"] == RUN_ID
    assert payload["run_date"] == DAY and payload["run_timestamp"] == TIMESTAMP
    assert payload["disclaimer"] == leaderboard.DISCLAIMER
    assert payload["n_per_cell"] == 1
    _, prompt_hash = prompt_set.load_prompts()
    assert payload["prompt_set_hash"] == prompt_hash
    assert payload["prices_read_on"] == registry.PRICES_READ_ON
    assert payload["pricing_url"] == registry.PRICING_URL
    assert payload["introductory_models"] == [
        m for m in MODELS if registry.MODELS[m]["introductory"]]


def test_payload_carries_every_key_the_site_reads(fake_run):
    """The static page renders exactly these keys; the builder is its only source."""
    payload = _build(fake_run)
    assert set(payload) == {
        "run_id", "run_timestamp", "run_date", "prompt_set_hash", "models",
        "n_per_cell", "disclaimer", "prices_read_on", "pricing_url",
        "introductory_models", "total_cost_inr", "missing_cells",
        "models_summary", "prompts",
    }
    for entry in payload["models_summary"].values():
        assert set(entry) == {
            "calls", "errors", "costed_cells", "cost_inr_total", "cost_inr_mean",
            "ttft_p50_ms", "ttft_p90_ms", "latency_p50_ms",
            "fidelity_mean_pct", "fidelity_labels",
            "instructions_followed", "answers_correct",
            "truncated_cells",
        }
    for prompt in payload["prompts"]:
        assert set(prompt) == {"id", "language", "script", "category",
                               "text", "rubric", "cells"}
        for cell in prompt["cells"]:
            assert set(cell) == {
                "model", "reasoning_effort", "ttft_ms", "total_ms",
                "prompt_tokens", "completion_tokens", "cost_inr",
                "finish_reason", "error_code", "retried", "attempts",
                "fidelity_label", "fidelity_pct",
                "answer_correct", "constraints_met", "text",
            }


def test_the_denominators_travel_in_the_payload(fake_run):
    """x/12 and x/4 are printed as such because only some prompts check."""
    payload = _build(fake_run)
    for entry in payload["models_summary"].values():
        instructions = entry["instructions_followed"]
        answers = entry["answers_correct"]
        assert instructions["total"] == entry["calls"]
        assert instructions["passed"] <= instructions["total"]
        assert answers["checkable"] <= entry["calls"]
        assert answers["passed"] <= answers["checkable"]


def test_a_partial_run_counts_its_missing_cells(tmp_path):
    prompts, prompt_hash = prompt_set.load_prompts()
    rows = [r for r in _fixture_rows()
            if not (r["model"] == MODELS[1] and r["prompt_id"] == "hi-3")]
    run_dir = _write_run(tmp_path, rows, prompt_hash)
    payload = leaderboard.build_leaderboard(run_dir, prompts, prompt_hash)

    assert payload["missing_cells"] == 1                 # one cell never ran
    hi3 = next(p for p in payload["prompts"] if p["id"] == "hi-3")
    assert [c["model"] for c in hi3["cells"]] == [MODELS[0]]
    assert payload["models_summary"][MODELS[1]]["calls"] == 1
    # the denominators count what the run actually holds, never what it should
    assert payload["models_summary"][MODELS[1]]["instructions_followed"] == {
        "passed": 0, "total": 1}


def test_a_changed_prompt_set_refuses_to_build(tmp_path):
    prompts, real_hash = prompt_set.load_prompts()
    run_dir = _write_run(tmp_path, _fixture_rows(), "0" * 64)  # a stale run
    with pytest.raises(leaderboard.PromptSetChanged) as caught:
        leaderboard.build_leaderboard(run_dir, prompts, real_hash)
    assert "prompt set has changed" in str(caught.value)


def test_a_run_with_no_rows_refuses_to_build(tmp_path):
    prompts, prompt_hash = prompt_set.load_prompts()
    run_dir = _write_run(tmp_path, [], prompt_hash)
    with pytest.raises(ValueError):
        leaderboard.build_leaderboard(run_dir, prompts, prompt_hash)


def test_write_leaderboard_creates_the_site_data_file(fake_run, tmp_path):
    target = tmp_path / "site" / "data" / "leaderboard.json"
    written = leaderboard.write_leaderboard(_build(fake_run), target)
    assert written == target and target.exists()
    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert on_disk["run_id"] == RUN_ID and on_disk["models"] == MODELS


# -- the command, with the same seams the run and score tests use ------------


def _build_args(**over):
    args = {"run": RUN_ID, "out": None}
    args.update(over)
    return SimpleNamespace(**args)


def test_cmd_build_writes_the_payload_and_prints_the_table(
        fake_run, tmp_path, capsys):
    out_path = tmp_path / "site" / "data" / "leaderboard.json"
    rc = cli.cmd_build(_build_args(), runs_base=tmp_path, out_path=out_path)
    assert rc == 0

    out = capsys.readouterr().out
    assert f"built run {RUN_ID}" in out
    assert f"wrote {out_path}" in out
    assert "no model scored another model" in out
    # the per-model table, with both denominators printed as such
    assert "instructions" in out and "correct" in out
    m1, m2 = MODELS
    assert f"{m1:<28}" in out and "1/2" in out    # instructions: hi-1 only
    assert "1/1" in out                          # correct: hi-1 carries the value
    assert "0/2" in out and "0/1" in out         # m2 errored and truncated

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == RUN_ID
    assert payload["models_summary"][m1]["answers_correct"] == {
        "passed": 1, "checkable": 1}
    assert payload["models_summary"][m2]["instructions_followed"] == {
        "passed": 0, "total": 2}


def test_cmd_build_defaults_to_the_newest_run(fake_run, tmp_path, capsys):
    rc = cli.cmd_build(_build_args(run=None), runs_base=tmp_path,
                       out_path=tmp_path / "lb.json")
    assert rc == 0
    payload = json.loads((tmp_path / "lb.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == RUN_ID


def test_cmd_build_refuses_a_changed_prompt_set(tmp_path, capsys):
    _write_run(tmp_path, _fixture_rows(), "0" * 64)
    rc = cli.cmd_build(_build_args(), runs_base=tmp_path,
                       out_path=tmp_path / "lb.json")
    assert rc == 2
    assert "prompt set has changed" in capsys.readouterr().err
    assert not (tmp_path / "lb.json").exists()


def test_cmd_build_unknown_run_fails_cleanly(tmp_path, capsys):
    rc = cli.cmd_build(_build_args(run="never-ran"), runs_base=tmp_path,
                       out_path=tmp_path / "lb.json")
    assert rc == 2
    assert "no run found for never-ran" in capsys.readouterr().err


def test_build_parser_defaults_match_the_workflow():
    args = cli.build_parser().parse_args(["build"])
    assert args.run is None and args.out is None
