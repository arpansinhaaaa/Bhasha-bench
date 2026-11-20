"""The CLI run path end to end against a fake client: the Day-1 acceptance,
minus the network. SARVAM_API_KEY is never needed or read here."""

import json
from types import SimpleNamespace

from bench import cli, registry
from fakes import FakeClient, err_action, ok_action


def _day_dir(base):
    dirs = [p for p in base.iterdir() if p.is_dir()]
    assert len(dirs) == 1
    return dirs[0]


def _run_dirs(base):
    return sorted(p for p in _day_dir(base).iterdir() if p.is_dir())


def _only_run_dir(base):
    runs = _run_dirs(base)
    assert len(runs) == 1
    return runs[0]


def _rows(base):
    lines = (_only_run_dir(base) / "results.jsonl").read_text(encoding="utf-8").splitlines()
    assert all(line.strip() for line in lines)
    return [json.loads(line) for line in lines]


def test_run_one_call_prints_one_line_and_appends_one_row(tmp_path, capsys):
    model = next(iter(registry.MODELS))
    client = FakeClient([ok_action()])
    args = SimpleNamespace(models=model, prompts="hi-1", reasoning_effort="low",
                           yes=True, dry_run=False)
    rc = cli.cmd_run(args, client=client, runs_base=tmp_path)
    assert rc == 0

    out = capsys.readouterr().out
    assert model in out and "hi-1" in out
    assert "ttft" in out and "₹" in out
    assert "1 call ·" in out and "0 errors" in out

    rows = _rows(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"]
    assert row["model"] == model and row["prompt_id"] == "hi-1"
    assert row["prompt_tokens"] == 37 and row["completion_tokens"] == 11
    entry = registry.MODELS[model]
    assert row["cost_inr"] == round(37 / 1e6 * entry["in"] + 11 / 1e6 * entry["out"], 6)
    assert row["finish_reason"] == "stop" and row["error_code"] is None

    meta = json.loads((_only_run_dir(tmp_path) / "run.json").read_text(encoding="utf-8"))
    assert meta["run_id"] == row["run_id"]
    assert meta["models"] == [model]
    assert meta["total_cost_inr"] == row["cost_inr"]
    assert len(meta["prompt_set_hash"]) == 64
    assert meta["reasoning_effort_fallback_models"] == []


def test_models_all_runs_every_registry_model(tmp_path):
    client = FakeClient([ok_action()])
    args = SimpleNamespace(models="all", prompts="hi-3", reasoning_effort="low",
                           yes=True, dry_run=False)
    rc = cli.cmd_run(args, client=client, runs_base=tmp_path)
    assert rc == 0
    rows = _rows(tmp_path)
    assert len(rows) == len(registry.MODELS)
    assert {r["model"] for r in rows} == set(registry.MODELS)
    assert all(r["prompt_id"] == "hi-3" for r in rows)


def test_a_failed_call_is_still_written_as_a_row(tmp_path, capsys):
    model = next(iter(registry.MODELS))
    client = FakeClient([
        err_action(429, "model_rate_limit_exceeded_error", retry_after=0)])
    args = SimpleNamespace(models=model, prompts="hi-1", reasoning_effort="low",
                           yes=True, dry_run=False)
    rc = cli.cmd_run(args, client=client, runs_base=tmp_path)
    assert rc == 0                       # the call failed; the run recorded it
    rows = _rows(tmp_path)
    assert len(rows) == 1
    assert rows[0]["error_code"] == "429 model_rate_limit_exceeded_error"
    assert rows[0]["attempts"] == 4 and rows[0]["retried"] is True
    assert rows[0]["prompt_tokens"] is None and rows[0]["cost_inr"] is None
    out = capsys.readouterr().out
    assert "1 error" in out


def test_unknown_model_id_is_rejected_before_anything_runs(tmp_path, capsys):
    client = FakeClient([ok_action()])
    args = SimpleNamespace(models="nope", prompts="all", reasoning_effort="low")
    rc = cli.cmd_run(args, client=client, runs_base=tmp_path)
    assert rc == 2
    assert "unknown model id" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_unknown_prompt_id_is_rejected_before_anything_runs(tmp_path, capsys):
    client = FakeClient([ok_action()])
    args = SimpleNamespace(models="all", prompts="hi-99", reasoning_effort="low")
    rc = cli.cmd_run(args, client=client, runs_base=tmp_path)
    assert rc == 2
    assert "unknown prompt id" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_missing_key_is_reported_cleanly(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("SARVAM_API_KEY", raising=False)
    args = SimpleNamespace(models=next(iter(registry.MODELS)), prompts="hi-1",
                           reasoning_effort="low", dry_run=False, yes=False)
    rc = cli.cmd_run(args, client=None, runs_base=tmp_path)
    assert rc == 2
    assert "SARVAM_API_KEY is not set" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []


def test_parser_defaults_match_the_handoff():
    args = cli.build_parser().parse_args(["run"])
    assert args.models == next(iter(registry.MODELS))  # Block G: the run default
    assert args.prompts == "all"
    assert args.reasoning_effort == "low"
    assert args.dry_run is False and args.yes is False
    score_args = cli.build_parser().parse_args(["score"])
    assert score_args.run is None and score_args.force is False


def test_dry_run_prints_the_projection_and_touches_nothing(tmp_path, capsys):
    model = next(iter(registry.MODELS))
    args = SimpleNamespace(models=model, prompts="hi-1",
                           reasoning_effort="low", dry_run=True, yes=False)
    rc = cli.cmd_run(args, client=None, runs_base=tmp_path)  # no key, no client
    assert rc == 0
    out = capsys.readouterr().out
    assert "projected cost ceiling" in out
    assert "₹" in out
    assert list(tmp_path.iterdir()) == []       # nothing written, nothing sent


def test_run_aborts_when_not_confirmed(tmp_path, capsys):
    model = next(iter(registry.MODELS))
    client = FakeClient([ok_action()])
    args = SimpleNamespace(models=model, prompts="hi-1",
                           reasoning_effort="low", dry_run=False, yes=False)
    rc = cli.cmd_run(args, client=client, runs_base=tmp_path,
                     approve=lambda planned: False)
    assert rc == 1
    assert "run cancelled" in capsys.readouterr().err
    assert client.calls == []                   # nothing was ever sent
    assert list(tmp_path.iterdir()) == []       # and nothing was written


def test_confirmation_is_asked_after_the_projection(tmp_path, capsys):
    model = next(iter(registry.MODELS))
    client = FakeClient([ok_action()])
    asked = []

    def approve(planned):
        asked.append(planned)
        return True

    args = SimpleNamespace(models=model, prompts="hi-1",
                           reasoning_effort="low", dry_run=False, yes=False)
    rc = cli.cmd_run(args, client=client, runs_base=tmp_path, approve=approve)
    assert rc == 0
    assert asked == [1]
    assert "projected cost ceiling" in capsys.readouterr().out
    assert len(_rows(tmp_path)) == 1


def test_running_total_prints_after_each_call(tmp_path, capsys):
    model = next(iter(registry.MODELS))
    client = FakeClient([ok_action()])
    args = SimpleNamespace(models=model, prompts="hi-1,hi-2",
                           reasoning_effort="low", dry_run=False, yes=True)
    rc = cli.cmd_run(args, client=client, runs_base=tmp_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert out.count("Σ ₹") == 2                # one running total per line
    assert "Σ ₹0.0013" in out                   # 2 x 0.000645, cumulative
    assert "2 calls ·" in out


def test_two_consecutive_runs_keep_separate_run_json(tmp_path):
    model = next(iter(registry.MODELS))
    client = FakeClient([ok_action()])
    args = SimpleNamespace(models=model, prompts="hi-1", reasoning_effort="low",
                           yes=True, dry_run=False)
    assert cli.cmd_run(args, client=client, runs_base=tmp_path) == 0
    assert cli.cmd_run(args, client=client, runs_base=tmp_path) == 0

    runs = _run_dirs(tmp_path)
    assert len(runs) == 2
    metas = [json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
             for run_dir in runs]
    assert metas[0]["run_id"] != metas[1]["run_id"]
    for run_dir, meta in zip(runs, metas):
        # Each run.json survived, in its own directory, named by its run_id...
        assert run_dir.name == meta["run_id"]
        # ...with its own results.jsonl holding exactly one stamped row.
        lines = (run_dir / "results.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        row = json.loads(lines[0])
        assert row["run_id"] == meta["run_id"]
        assert row["model"] == model and row["prompt_id"] == "hi-1"
