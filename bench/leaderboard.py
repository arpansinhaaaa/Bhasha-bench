"""Build the leaderboard JSON the static page publishes (PRD P8, P11).

`python -m bench.cli build` reads one run's results.jsonl and its run.json,
and writes site/data/leaderboard.json - the only file the page ever
fetches. Every number is arithmetic over rows the API produced: no model
judges another model, no cost is estimated from character counts. Quality
is not graded here at all; instead bench.checks computes two deterministic
aggregates per model - instructions followed (constraints declared in
prompts.yaml) and answers correct (the expected value, where the prompt
declares one). data/scores.csv and the `score` command are untouched and
deliberately unpublished: they remain a human's blind spot-check.

Honesty rules the shape: an errored call stays a cell carrying its error
code; a missing usage block stays null and renders n/a; a run that stopped
early keeps every cell it never wrote, marked missing rather than papered
over; the prompt-set hash, run date, n per cell and the dated price line
travel inside the JSON so the page cannot mislabel itself.

The builder refuses a run whose recorded prompt-set hash does not match the
current prompts/prompts.yaml (the hash ignores machine-check expectation
keys, so adding those does not invalidate runs - see bench.prompts). The
drill-down would otherwise show prompt text that did not produce those
answers, and a complete-looking wrong table is worse than a refusal.
"""

from __future__ import annotations

import json
from pathlib import Path

from bench import checks, metrics, registry, store

SITE_DATA_DIR = Path(__file__).resolve().parents[1] / "site" / "data"
LEADERBOARD_PATH = SITE_DATA_DIR / "leaderboard.json"

N_PER_CELL = 1  # the harness sends one call per model x prompt per run
DISCLAIMER = "n=1 per cell; directional, not definitive."


class PromptSetChanged(Exception):
    """prompts.yaml no longer matches the run; the drill-down would mislead."""


def build_leaderboard(run_dir: Path, prompts: list[dict],
                      prompt_set_hash: str) -> dict:
    """Aggregate one run into the page's payload.

    prompts/prompt_set_hash come from bench.prompts.load_prompts(). Raises
    PromptSetChanged when the run was produced by a different prompt set
    than the file on disk, and ValueError for a run with no rows to
    publish.
    """
    run_dir = Path(run_dir)
    metadata = json.loads(
        (run_dir / store.METADATA_NAME).read_text(encoding="utf-8"))
    if metadata.get("prompt_set_hash") != prompt_set_hash:
        raise PromptSetChanged(
            f"prompt set has changed since run {metadata.get('run_id', run_dir.name)} "
            f"(run hash {metadata.get('prompt_set_hash')}, file hash {prompt_set_hash}). "
            "The drill-down would show prompt text that did not produce these "
            "answers; re-run before publishing, or build against a run of the "
            "current prompt set.")

    rows = store.RunStore(run_dir.name, run_dir).read_rows()
    if not rows:
        raise ValueError(f"no rows in {run_dir / store.RESULTS_NAME}")

    by_id = {prompt["id"]: prompt for prompt in prompts}
    models = _run_models(metadata, rows)

    cells_by_prompt: dict[str, dict[str, dict]] = {}
    label_counts: dict[str, dict] = {}
    per_model: dict[str, dict] = {}
    total_cost = 0.0
    for row in rows:
        prompt = by_id[row["prompt_id"]]
        cls = metrics.classify(row.get("text") or "", prompt["script"])
        model = row["model"]
        cost = row.get("cost_inr")
        if cost is not None:
            total_cost += cost
        cell = {
            "model": model,
            "reasoning_effort": row.get("reasoning_effort"),
            "ttft_ms": row.get("ttft_ms"),
            "total_ms": row.get("total_ms"),
            "prompt_tokens": row.get("prompt_tokens"),
            "completion_tokens": row.get("completion_tokens"),
            "cost_inr": cost,
            "finish_reason": row.get("finish_reason"),
            "error_code": row.get("error_code"),
            "retried": row.get("retried"),
            "attempts": row.get("attempts"),
            "fidelity_label": cls.label,
            "fidelity_pct": cls.target_pct,
            "answer_correct": checks.answer_correct(row, prompt),
            "constraints_met": checks.constraints_met(row, prompt),
            "text": row.get("text") or "",
        }
        cells_by_prompt.setdefault(row["prompt_id"], {})[model] = cell

        tally = label_counts.setdefault(model, {})
        tally[cls.label] = tally.get(cls.label, 0) + 1
        agg = per_model.setdefault(model, {
            "pcts": [], "truncated": 0,
            "instructions": 0, "cells": 0,
            "correct": 0, "checkable": 0,
        })
        if cls.label != "empty":  # a blank or errored cell measures no script
            agg["pcts"].append(cls.target_pct)
        if cell["constraints_met"]:
            agg["instructions"] += 1
        agg["cells"] += 1                       # every cell is checked
        if cell["answer_correct"] is not None:   # only prompts with a value
            agg["checkable"] += 1
            if cell["answer_correct"]:
                agg["correct"] += 1
        if row.get("finish_reason") == "length":
            agg["truncated"] += 1

    run_prompt_ids = [prompt["id"] for prompt in prompts
                      if prompt["id"] in cells_by_prompt]
    prompts_payload = []
    for prompt_id in run_prompt_ids:
        prompt = by_id[prompt_id]
        model_cells = cells_by_prompt[prompt_id]
        prompts_payload.append({
            "id": prompt_id,
            "language": prompt["language"],
            "script": prompt["script"],
            "category": prompt["category"],
            "text": prompt["text"].strip(),
            "rubric": prompt["rubric"].strip(),
            "cells": [model_cells[model] for model in models if model in model_cells],
        })

    summary = metrics.model_summary(rows)
    for model, agg in summary.items():
        mine = per_model[model]
        summary[model].update({
            "fidelity_mean_pct": _mean(mine["pcts"]),
            "fidelity_labels": dict(sorted(label_counts[model].items())),
            "instructions_followed": {"passed": mine["instructions"],
                                      "total": mine["cells"]},
            "answers_correct": {"passed": mine["correct"],
                                "checkable": mine["checkable"]},
            "truncated_cells": mine["truncated"],
        })

    written = sum(len(prompt["cells"]) for prompt in prompts_payload)
    return {
        "run_id": metadata.get("run_id", run_dir.name),
        "run_timestamp": metadata.get("timestamp"),
        "run_date": (metadata.get("timestamp") or run_dir.name)[:10],
        "prompt_set_hash": prompt_set_hash,
        "models": models,
        "n_per_cell": N_PER_CELL,
        "disclaimer": DISCLAIMER,
        "prices_read_on": registry.PRICES_READ_ON,
        "pricing_url": registry.PRICING_URL,
        "introductory_models": [model for model in models
                                if (registry.MODELS.get(model) or {}).get("introductory")],
        "total_cost_inr": round(total_cost, 6),
        "missing_cells": max(len(models) * len(run_prompt_ids) - written, 0),
        "models_summary": summary,
        "prompts": prompts_payload,
    }


def write_leaderboard(payload: dict, path: Path | None = None) -> Path:
    """Write the payload as the page's data file; return the path written."""
    target = Path(path) if path is not None else LEADERBOARD_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _run_models(metadata: dict, rows: list[dict]) -> list[str]:
    """The run's model order: run.json's list, then any stragglers from rows."""
    models = list(metadata.get("models") or [])
    for row in rows:
        if row["model"] not in models:
            models.append(row["model"])
    return models


def _mean(values: list) -> float | None:
    """Mean rounded to 2, or None for an empty list - never an invented value."""
    return round(sum(values) / len(values), 2) if values else None
