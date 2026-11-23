"""Verify the newest run's last row against the live smoke criteria.

The smoke test is run by a human with the key exported (the harness never
runs it itself):

    export SARVAM_API_KEY=...
    python -m bench.cli run --models sarvam-105b --prompts hi-1
    python -m bench.smoke            # or: make smoke-check

The smoke passes when the newest row shows: ttft_ms > 0, total_ms >= ttft_ms,
non-empty Devanagari text containing the Rs 172.50 amount, finish_reason
"stop", and a cost_inr that recomputes from the token counts and
bench/registry.py. The amount check is a string heuristic ("172" or its
Devanagari digits), not a judge: no model scores another model here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bench import registry
from bench.store import RUNS_DIR

DEVA_START = 0x0900  # Devanagari block, as in the PRD's script classifier spec
DEVA_END = 0x097F


def newest_run_dir(base: Path | str | None = None) -> Path | None:
    """The newest run directory under base (default: the real data/runs)."""
    root = Path(base) if base is not None else RUNS_DIR
    if not root.is_dir():
        return None
    days = sorted(p for p in root.iterdir() if p.is_dir())
    if not days:
        return None
    runs = sorted(p for p in days[-1].iterdir() if p.is_dir())
    return runs[-1] if runs else None


def check_row(row: dict) -> list[str]:
    """The smoke criteria as failure messages; an empty list means pass."""
    failures = []
    if not row.get("ttft_ms") or row["ttft_ms"] <= 0:
        failures.append(f'ttft_ms {row.get("ttft_ms")} is not > 0')
    if row.get("total_ms") is None or row.get("ttft_ms") is None:
        failures.append("total_ms/ttft_ms missing")
    elif row["total_ms"] < row["ttft_ms"]:
        failures.append(f'total_ms {row["total_ms"]} < ttft_ms {row["ttft_ms"]}')

    text = row.get("text") or ""
    if not text.strip():
        failures.append("text is empty")
    else:
        if not any(DEVA_START <= ord(ch) <= DEVA_END for ch in text):
            failures.append("text contains no Devanagari (U+0900-U+097F)")
        if "172" not in text and "१७२" not in text:
            failures.append("text does not show the Rs 172.50 amount (heuristic)")

    if row.get("finish_reason") != "stop":
        failures.append(f'finish_reason {row.get("finish_reason")!r} is not "stop"')
    if row.get("error_code"):
        failures.append(f'row carries error_code {row["error_code"]!r}')

    if row.get("prompt_tokens") is None or row.get("completion_tokens") is None:
        failures.append("usage block missing: token counts are null")
    elif row["prompt_tokens"] <= 0 or row["completion_tokens"] <= 0:
        failures.append(
            f'tokens {row["prompt_tokens"]}/{row["completion_tokens"]} are not positive')
    else:
        expected = registry.cost_inr(row["model"], row["prompt_tokens"],
                                     row["completion_tokens"], row.get("cached_tokens") or 0)
        if row.get("cost_inr") != expected:
            failures.append(f'cost_inr {row.get("cost_inr")} != recomputed {expected}')
    return failures


def main(argv: list[str] | None = None) -> int:
    base = argv[0] if argv else None
    run_dir = newest_run_dir(base)
    if run_dir is None:
        print(f"no runs found under {base or RUNS_DIR}", file=sys.stderr)
        return 2
    results = run_dir / "results.jsonl"
    if not results.exists():
        print(f"no results.jsonl in {run_dir}", file=sys.stderr)
        return 2
    lines = results.read_text(encoding="utf-8").splitlines()
    if not lines:
        print(f"no rows in {results}", file=sys.stderr)
        return 2
    row = json.loads(lines[-1])
    print(f"run dir: {run_dir}")
    print(f"row: {json.dumps(row, ensure_ascii=False)}")
    if len(lines) > 1:
        print(f"note: run has {len(lines)} rows; checked the last one")
    failures = check_row(row)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    print("PASS: ttft_ms > 0, total_ms >= ttft_ms, Devanagari text with the "
          'Rs 172.50 amount, finish_reason "stop", cost_inr recomputed from '
          "bench/registry.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
