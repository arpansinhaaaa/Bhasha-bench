"""The human scorer: prompt, rubric and answer in; a typed 0/1/2 out.

Every score asserted here was typed by the scripted input - the command must
never invent, default or estimate one. No network, no key."""

import csv
from types import SimpleNamespace

from bench import cli
from bench.store import RunStore

SCORES_NAME = "scores.csv"


def _row(run_id, model, prompt_id, text, error=None):
    return {"run_id": run_id, "model": model, "prompt_id": prompt_id,
            "text": text, "error_code": error, "reasoning_effort": "low",
            "ttft_ms": 12, "total_ms": 34, "prompt_tokens": 10,
            "completion_tokens": 5, "cached_tokens": 0, "cost_inr": 0.001,
            "finish_reason": "stop", "retried": False, "attempts": 1}


def _run(base, specs):
    run = RunStore.create(base=base)
    with run:
        for spec in specs:
            run.append_row(_row(run.run_id, **spec))
    return run


class ScriptedInput:
    """input() with a script; records every prompt it was asked."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        return self.replies.pop(0) if self.replies else "q"


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_score_records_what_a_human_types(tmp_path):
    run = _run(tmp_path, [
        {"model": "m1", "prompt_id": "hi-1", "text": "पहला उत्तर"},
        {"model": "m2", "prompt_id": "hi-1", "text": "दूसरा उत्तर"},
        {"model": "m1", "prompt_id": "hi-2", "text": "तीसरा उत्तर"},
    ])
    typed = ScriptedInput(["2", "1", "q"])
    shown = []
    scores = tmp_path / SCORES_NAME
    rc = cli.cmd_score(SimpleNamespace(run=None, force=False),
                       input_fn=typed, output=shown.append,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    rows = _read_csv(scores)
    assert {(r["run_id"], r["model"], r["prompt_id"], r["score"]) for r in rows} == {
        (run.run_id, "m1", "hi-1", "2"),
        (run.run_id, "m2", "hi-1", "1"),
    }
    transcript = "\n".join(shown)
    assert "rubric:" in transcript
    assert "पहला उत्तर" in transcript and "दूसरा उत्तर" in transcript
    assert "तीसरा उत्तर" in transcript      # shown, then the walk was stopped
    assert len(_read_csv(scores)) == 2       # but never scored


def test_score_never_invents_a_value(tmp_path):
    _run(tmp_path, [{"model": "m1", "prompt_id": "hi-1", "text": "कोई उत्तर"}])
    typed = ScriptedInput([""])              # quit before typing anything
    scores = tmp_path / SCORES_NAME
    shown = []
    rc = cli.cmd_score(SimpleNamespace(run=None, force=False),
                       input_fn=typed, output=shown.append,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    assert not scores.exists()               # nothing typed, nothing written
    assert "stopped after 0 score(s)" in "\n".join(shown)


def test_score_rejects_anything_but_zero_one_two(tmp_path):
    _run(tmp_path, [{"model": "m1", "prompt_id": "hi-1", "text": "उत्तर"}])
    typed = ScriptedInput(["3", "bad", "1"])
    scores = tmp_path / SCORES_NAME
    rc = cli.cmd_score(SimpleNamespace(run=None, force=False),
                       input_fn=typed, output=lambda *_: None,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    assert len(typed.prompts) == 3           # asked again after each bad input
    assert _read_csv(scores)[0]["score"] == "1"


def test_score_skips_keys_that_already_carry_a_score(tmp_path):
    run = _run(tmp_path, [
        {"model": "m1", "prompt_id": "hi-1", "text": "पहला उत्तर"},
        {"model": "m2", "prompt_id": "hi-1", "text": "दूसरा उत्तर"},
    ])
    scores = tmp_path / SCORES_NAME
    cli._write_scores(scores, {(run.run_id, "m1", "hi-1"): 1})
    typed = ScriptedInput(["2"])
    rc = cli.cmd_score(SimpleNamespace(run=None, force=False),
                       input_fn=typed, output=lambda *_: None,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    rows = _read_csv(scores)
    assert {(r["model"], r["score"]) for r in rows} == {("m1", "1"), ("m2", "2")}
    assert len(typed.prompts) == 1           # m1 was never asked again


def test_score_force_overwrites_when_asked(tmp_path):
    run = _run(tmp_path, [{"model": "m1", "prompt_id": "hi-1", "text": "उत्तर"}])
    scores = tmp_path / SCORES_NAME
    cli._write_scores(scores, {(run.run_id, "m1", "hi-1"): 1})
    rc = cli.cmd_score(SimpleNamespace(run=None, force=True),
                       input_fn=ScriptedInput(["2"]), output=lambda *_: None,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    assert _read_csv(scores)[0]["score"] == "2"


def test_score_skips_errored_and_empty_cells(tmp_path):
    _run(tmp_path, [
        {"model": "m1", "prompt_id": "hi-1", "text": ""},
        {"model": "m2", "prompt_id": "hi-2", "text": "",
         "error": "429 model_rate_limit_exceeded_error"},
        {"model": "m3", "prompt_id": "hi-3", "text": "असली उत्तर"},
    ])
    typed = ScriptedInput(["1"])
    scores = tmp_path / SCORES_NAME
    rc = cli.cmd_score(SimpleNamespace(run=None, force=False),
                       input_fn=typed, output=lambda *_: None,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    assert len(typed.prompts) == 1           # only the answerable cell
    assert _read_csv(scores)[0]["prompt_id"] == "hi-3"


def test_score_resumes_where_it_stopped(tmp_path):
    _run(tmp_path, [
        {"model": "m1", "prompt_id": "hi-1", "text": "एक"},
        {"model": "m2", "prompt_id": "hi-1", "text": "दो"},
    ])
    scores = tmp_path / SCORES_NAME
    cli.cmd_score(SimpleNamespace(run=None, force=False),
                  input_fn=ScriptedInput(["0", "q"]), output=lambda *_: None,
                  scores_path=scores, runs_base=tmp_path)
    rc = cli.cmd_score(SimpleNamespace(run=None, force=False),
                       input_fn=ScriptedInput(["2"]), output=lambda *_: None,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    rows = _read_csv(scores)
    assert {(r["model"], r["score"]) for r in rows} == {("m1", "0"), ("m2", "2")}


def test_score_reports_when_there_is_nothing_new(tmp_path):
    run = _run(tmp_path, [{"model": "m1", "prompt_id": "hi-1", "text": "उत्तर"}])
    scores = tmp_path / SCORES_NAME
    cli._write_scores(scores, {(run.run_id, "m1", "hi-1"): 2})

    def never(prompt=""):
        raise AssertionError("nothing should have been asked")

    shown = []
    rc = cli.cmd_score(SimpleNamespace(run=None, force=False),
                       input_fn=never, output=shown.append,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    assert "nothing to score" in "\n".join(shown)


def test_score_can_target_a_specific_run_id(tmp_path):
    _run(tmp_path, [{"model": "m1", "prompt_id": "hi-1", "text": "पहला"}])
    second = _run(tmp_path, [{"model": "m2", "prompt_id": "hi-1", "text": "दूसरा"}])
    scores = tmp_path / SCORES_NAME
    rc = cli.cmd_score(SimpleNamespace(run=second.run_id, force=False),
                       input_fn=ScriptedInput(["1"]), output=lambda *_: None,
                       scores_path=scores, runs_base=tmp_path)
    assert rc == 0
    rows = _read_csv(scores)
    assert len(rows) == 1
    assert rows[0]["run_id"] == second.run_id
    assert rows[0]["model"] == "m2"
