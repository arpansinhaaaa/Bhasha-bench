"""Append-only JSONL storage and the run metadata file, one directory per run."""

import json
from datetime import datetime

from bench.store import METADATA_NAME, RESULTS_NAME, RunStore


def test_create_layout_and_run_id_format(tmp_path):
    run = RunStore.create(base=tmp_path)
    today = datetime.now().strftime("%Y-%m-%d")
    assert run.run_id.startswith(today + "T")
    assert run.directory == tmp_path / today / run.run_id
    assert run.results_path.name == RESULTS_NAME
    assert run.metadata_path.name == METADATA_NAME
    assert run.directory.is_dir()


def test_two_runs_in_the_same_second_never_share_a_directory(tmp_path):
    first = RunStore.create(base=tmp_path)
    second = RunStore.create(base=tmp_path)
    assert first.run_id != second.run_id
    assert first.directory != second.directory
    assert second.directory.parent == first.directory.parent


def test_rows_round_trip_in_written_order(tmp_path):
    run = RunStore.create(base=tmp_path)
    with run:
        run.append_row({"run_id": run.run_id, "model": "m", "prompt_id": "p",
                        "text": "नमस्ते"})
        run.append_row({"run_id": run.run_id, "model": "m", "prompt_id": "p2", "n": 2})
        run.append_row({"run_id": run.run_id, "model": "m", "prompt_id": "p3", "n": 3})
    rows = run.read_rows()
    assert [r["prompt_id"] for r in rows] == ["p", "p2", "p3"]
    assert rows[0]["text"] == "नमस्ते"
    raw = run.results_path.read_text(encoding="utf-8")
    assert raw.endswith("\n")
    assert len(raw.splitlines()) == 3      # one JSON object per line
    assert "नमस्ते" in raw                  # UTF-8 kept readable, not \u-escaped


def test_a_second_run_never_touches_the_first_run_s_files(tmp_path):
    first = RunStore.create(base=tmp_path)
    with first:
        first.append_row({"prompt_id": "p1", "n": 1})
    first.write_metadata(models=["a"], prompt_set_hash="h" * 64)

    second = RunStore.create(base=tmp_path)
    with second:
        second.append_row({"prompt_id": "p2", "n": 2})
    second.write_metadata(models=["b"], prompt_set_hash="h" * 64)

    assert second.directory != first.directory
    # The first run's row and metadata survived the second run untouched.
    assert first.read_rows() == [{"prompt_id": "p1", "n": 1}]
    assert json.loads(first.metadata_path.read_text(encoding="utf-8"))["models"] == ["a"]
    assert second.read_rows() == [{"prompt_id": "p2", "n": 2}]
    assert json.loads(second.metadata_path.read_text(encoding="utf-8"))["models"] == ["b"]


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
    # The metadata file is not rows: the run itself rewriting it is allowed.
    assert final["timestamp"] == first["timestamp"]
