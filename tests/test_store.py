"""Append-only JSONL storage and the run metadata file."""

import json
from datetime import datetime

from bench.store import METADATA_NAME, RESULTS_NAME, RunStore


def test_create_layout_and_run_id_format(tmp_path):
    run = RunStore.create(base=tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    assert run.directory == tmp_path / today
    assert run.results_path.name == RESULTS_NAME
    assert run.metadata_path.name == METADATA_NAME
    assert run.run_id.startswith(today + "T")
    assert len(run.run_id) == len("YYYY-MM-DDTHHMMSS")
    assert run.directory.is_dir()


def test_rows_round_trip_in_written_order(tmp_path):
    run = RunStore.create(base=tmp_path)
    with run:
        run.append_row({"run_id": run.run_id, "model": "m", "prompt_id": "p",
                        "text": "नमस्ते"})
        run.append_row({"run_id": run.run_id, "model": "m", "prompt_id": "p2", "n": 2})
        run.append_row({"run_id": run.run_id, "model": "m", "prompt_id": "p3", "n": 3})
    rows = run.read_rows()
    assert len(rows) == 3
    assert [r["prompt_id"] for r in rows] == ["p", "p2", "p3"]
    assert rows[0]["text"] == "नमस्ते"


def test_rows_are_appended_never_rewritten(tmp_path):
    run = RunStore.create(base=tmp_path)
    with run:
        run.append_row({"prompt_id": "p1", "n": 1})
    # A later store on the same directory appends; existing lines stay put.
    later = RunStore(run.run_id + "b", run.directory)
    with later:
        later.append_row({"prompt_id": "p2", "n": 2})
    raw = run.results_path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["prompt_id"] == "p1"
    assert json.loads(lines[1])["prompt_id"] == "p2"
    # One JSON object per line, UTF-8 text kept readable, trailing newline.
    assert raw.endswith("\n")
    assert "नमस्ते" not in raw  # this run wrote no such row
    first = RunStore.create(base=tmp_path)
    with first:
        first.append_row({"text": "नमस्ते"})
    assert "नमस्ते" in first.results_path.read_text(encoding="utf-8")


def test_metadata_holds_the_run_facts(tmp_path):
    run = RunStore.create(base=tmp_path)
    run.write_metadata(models=["a", "b"], prompt_set_hash="h" * 64)
    first = json.loads(run.metadata_path.read_text(encoding="utf-8"))
    assert first["run_id"] == run.run_id
    assert first["timestamp"]
    assert first["prompt_set_hash"] == "h" * 64
    assert first["models"] == ["a", "b"]
    assert first["total_cost_inr"] is None
    assert first["reasoning_effort_fallback_models"] == []

    run.write_metadata(models=["a", "b"], prompt_set_hash="h" * 64,
                       total_cost=0.5, reasoning_fallback=["b", "a", "b"])
    final = json.loads(run.metadata_path.read_text(encoding="utf-8"))
    assert final["total_cost_inr"] == 0.5
    assert final["reasoning_effort_fallback_models"] == ["a", "b"]
    # The metadata file is not rows: rewriting it is allowed.
    assert final["timestamp"] == first["timestamp"]
