"""Append-only run storage.

Layout, per the handoff:

    data/runs/<YYYY-MM-DD>/results.jsonl   one JSON object per line, append-only
    data/runs/<YYYY-MM-DD>/run.json        run_id, timestamp, prompt-set hash,
                                           model list, total cost

Rows are never rewritten, reordered or dropped - a run that dies halfway
leaves every row it managed to write, each stamped with its run_id. The
metadata file is not rows, so it may be (re)written as a run progresses:
once when the run opens, with the total unknown, and once when it closes.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parents[1] / "data" / "runs"
RESULTS_NAME = "results.jsonl"
METADATA_NAME = "run.json"


class RunStore:
    """One run's results file (opened for appending) and its metadata."""

    def __init__(self, run_id: str, directory: Path):
        self.run_id = run_id
        self.directory = Path(directory)
        self.results_path = self.directory / RESULTS_NAME
        self.metadata_path = self.directory / METADATA_NAME
        self.created_at = datetime.now().astimezone()
        self._handle = None

    @classmethod
    def create(cls, base: Path | None = None) -> "RunStore":
        """A new run under data/runs/<YYYY-MM-DD>, run_id <YYYY-MM-DD>T<HHMMSS>."""
        now = datetime.now()
        directory = (Path(base) if base is not None else RUNS_DIR) / now.strftime("%Y-%m-%d")
        directory.mkdir(parents=True, exist_ok=True)
        return cls(run_id=now.strftime("%Y-%m-%dT%H%M%S"), directory=directory)

    # -- rows ------------------------------------------------------------------

    def append_row(self, row: dict) -> None:
        """Append one row as one JSON object on one line. Nothing else is touched."""
        handle = self._open_for_append()
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()

    def read_rows(self) -> list[dict]:
        """Every row written so far, in written order."""
        with open(self.results_path, encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]

    # -- metadata ----------------------------------------------------------------

    def write_metadata(self, *, models, prompt_set_hash, total_cost=None,
                       reasoning_fallback=()) -> None:
        """(Re)write run.json. This file is metadata, not rows."""
        payload = {
            "run_id": self.run_id,
            "timestamp": self.created_at.isoformat(timespec="seconds"),
            "prompt_set_hash": prompt_set_hash,
            "models": list(models),
            "total_cost_inr": total_cost,
            "reasoning_effort_fallback_models": sorted(set(reasoning_fallback)),
        }
        self.metadata_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    # -- lifecycle ----------------------------------------------------------------

    def _open_for_append(self):
        if self._handle is None:
            self._handle = open(self.results_path, "a", encoding="utf-8")
        return self._handle

    def close(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> "RunStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
