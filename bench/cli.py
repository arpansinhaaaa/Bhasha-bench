"""Bhasha Bench command line.

    python -m bench.cli run [--dry-run] [--yes] --models <ids|all> --prompts <ids|all>
    python -m bench.cli score [--run RUN_ID] [--force]

`run` prints the projected cost ceiling first and asks before it spends
anything. It prints one line per call (model, ttft, tokens, cost, running
total - or the error the call carried) and a total at the end. Rows are
appended to data/runs/<YYYY-MM-DD>/<run_id>/results.jsonl, one JSON object
per line, never rewritten, in a directory this run owns.
`score` shows prompt, rubric and answer and records the 0/1/2 a human
types; it never invents a score. SARVAM_API_KEY is read from the
environment only.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

from bench import prompts as prompt_set
from bench import registry
from bench import runner
from bench import store as store_mod
from bench.smoke import newest_run_dir

DEFAULT_EFFORT = "low"  # Block G: low, and not "none" until the probe settles it


def build_parser() -> argparse.ArgumentParser:
    default_model = next(iter(registry.MODELS))
    parser = argparse.ArgumentParser(
        prog="bench", description="Bhasha Bench: Indic prompts x Token Factory models.")
    commands = parser.add_subparsers(dest="command", required=True)
    run_cmd = commands.add_parser(
        "run", help="send prompts to models and record rows")
    run_cmd.add_argument(
        "--models", metavar="IDS|all", default=default_model,
        help="comma-separated model ids, or 'all' "
             f"[default: {default_model}]")
    run_cmd.add_argument(
        "--prompts", metavar="IDS|all", default="all",
        help="comma-separated prompt ids, or 'all' [default: all]")
    run_cmd.add_argument(
        "--reasoning-effort", metavar="E", default=DEFAULT_EFFORT,
        choices=["none", "low", "medium", "high", "max"],
        help="reasoning_effort sent on every call [default: low]. 'none' is "
             "unverified on some models (two doc pages disagree); a model "
             "that rejects the value is probed once without the field and "
             "records reasoning_effort: null")
    run_cmd.add_argument(
        "--dry-run", action="store_true",
        help="print the projected cost ceiling and exit; nothing is sent or written")
    run_cmd.add_argument(
        "--yes", action="store_true",
        help="skip the cost confirmation (you already decided)")
    score_cmd = commands.add_parser(
        "score", help="score answers by hand, 0-2; this never invents a score")
    score_cmd.add_argument(
        "--run", metavar="RUN_ID", default=None,
        help="the run to score [default: the newest run]")
    score_cmd.add_argument(
        "--force", action="store_true",
        help="ask again for answers that already carry a score")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "score":
        return cmd_score(args)
    return 2  # unreachable: subparsers are required


def cmd_run(args, client=None, runs_base=None, approve=None) -> int:
    """Run the fan-out and record it.

    `client`, `runs_base` and `approve` are test seams; `approve` replaces
    the y/N prompt the real command asks after printing the projection.
    """
    try:
        all_prompts, prompt_hash = prompt_set.load_prompts()
    except FileNotFoundError:
        print(f"prompt set not found at {prompt_set.DEFAULT_PATH}", file=sys.stderr)
        return 2
    try:
        selected = _select_prompts(args.prompts, all_prompts)
        models = _select_models(args.models)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2

    if args.dry_run:
        print(_format_projection(models, selected))
        return 0

    if client is None and not os.environ.get("SARVAM_API_KEY"):
        # The key is read from the environment only; never echoed.
        print("SARVAM_API_KEY is not set. Export it and re-run.", file=sys.stderr)
        return 2

    planned = len(models) * len(selected)
    print(_format_projection(models, selected))
    if not args.yes:
        approver = approve if approve is not None else _confirm_on_stdin
        if not approver(planned):
            print("run cancelled; nothing was sent or written.", file=sys.stderr)
            return 1

    run = store_mod.RunStore.create(base=runs_base)
    print(f"run {run.run_id} · {len(models)} model(s) × {len(selected)} prompt(s) "
          f"· effort {args.reasoning_effort} · {planned} call(s) planned")
    # Metadata first, so a run that dies mid-flight is still identified.
    run.write_metadata(models=models, prompt_set_hash=prompt_hash)

    tally = {"calls": 0, "errors": 0}
    running = {"cost": 0.0}

    def on_row(row: dict) -> None:
        stamped = {"run_id": run.run_id, **row}
        row.clear()
        row.update(stamped)
        run.append_row(row)
        if row["cost_inr"] is not None:
            running["cost"] += row["cost_inr"]
        print(_format_line(row, running["cost"]))
        tally["calls"] += 1
        if row["error_code"]:
            tally["errors"] += 1

    rows, stop_reason = [], None
    try:
        with run:
            rows, stop_reason = asyncio.run(runner.run_all(
                models,
                [(p["id"], p["text"]) for p in selected],
                client=client,
                reasoning_effort=args.reasoning_effort,
                on_row=on_row,
            ))
    finally:
        costed = [row["cost_inr"] for row in rows if row["cost_inr"] is not None]
        total = round(sum(costed), 6) if costed else None
        fallback = sorted({row["model"] for row in rows
                           if row["reasoning_effort"] is None})
        run.write_metadata(models=models, prompt_set_hash=prompt_hash,
                           total_cost=total, reasoning_fallback=fallback)

    print(f"{_plural(tally['calls'], 'call')} · {_rupees(total)} · "
          f"{_plural(tally['errors'], 'error')} · results in {run.directory}/")
    if stop_reason is not None:
        print(f"run stopped early after {len(rows)} of {planned} calls: "
              f"{stop_reason}. Rows so far are kept; top up or fix the key, "
              "then re-run.", file=sys.stderr)
        return 2
    return 0


def _select_prompts(spec: str, all_prompts: list[dict]) -> list[dict]:
    """Resolve --prompts: 'all', or comma-separated ids (order kept, dups dropped)."""
    by_id = {p["id"]: p for p in all_prompts}
    if spec.strip().lower() == "all":
        return list(all_prompts)
    selected, seen = [], set()
    for pid in [part.strip() for part in spec.split(",") if part.strip()]:
        if pid not in by_id:
            raise ValueError(
                f"unknown prompt id '{pid}' - valid: all, " + ", ".join(by_id))
        if pid not in seen:
            seen.add(pid)
            selected.append(by_id[pid])
    if not selected:
        raise ValueError("no prompts selected")
    return selected


def _select_models(spec: str) -> list[str]:
    """Resolve --models: 'all', or comma-separated ids (order kept, dups dropped)."""
    if spec.strip().lower() == "all":
        return list(registry.MODELS)
    models, seen = [], set()
    for mid in [part.strip() for part in spec.split(",") if part.strip()]:
        if mid not in registry.MODELS:
            raise ValueError(
                f"unknown model id '{mid}' - valid: all, " + ", ".join(registry.MODELS))
        if mid not in seen:
            seen.add(mid)
            models.append(mid)
    if not models:
        raise ValueError("no models selected")
    return models


def _format_line(row: dict, running_total=None) -> str:
    """One line per call: model, ttft, tokens, cost, running total - or the error."""
    head = f'{row["model"]}  {row["prompt_id"]}'
    tail = f"  Σ {_rupees(running_total)}" if running_total is not None else ""
    if row["error_code"]:
        return (f'{head}  ERROR {row["error_code"]}  attempts {row["attempts"]}'
                f"{tail}")
    ttft = f'{row["ttft_ms"]}ms' if row["ttft_ms"] and row["ttft_ms"] > 0 else "n/a"
    if row["prompt_tokens"] is None:
        tokens = "n/a"
    else:
        tokens = f'{row["prompt_tokens"]}/{row["completion_tokens"]}'
    note = "  (retried)" if row["retried"] else ""
    return (f"{head}  ttft {ttft}  tokens {tokens}  "
            f"{_rupees(row['cost_inr'])}{note}{tail}")


def _rupees(amount) -> str:
    """Rupees for display: two decimals once it is a rupee, four below that."""
    if amount is None:
        return "n/a"
    return f"₹{amount:.2f}" if amount >= 1 else f"₹{amount:.4f}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


def _format_projection(models, selected, max_tokens=1500) -> str:
    """The cost ceiling, from the registry and the prompt set.

    Completions are bounded by max_tokens per call - an exact ceiling from
    the request itself. Input is over-estimated at one token per character
    of prompt text, so the real bill comes in below this. A projection is
    not a measurement: nothing here is ever stored as a row.
    """
    prompt_chars = sum(len(prompt["text"]) for prompt in selected)
    lines = [
        f"projected cost ceiling, {len(models)} model(s) × {len(selected)} prompt(s):",
        f"  completions capped at max_tokens={max_tokens}; "
        "input over-estimated at one token per prompt character",
    ]
    total = 0.0
    for model in models:
        entry = registry.MODELS[model]
        calls = len(selected)
        ceiling = (calls * max_tokens / 1e6 * entry["out"]
                   + prompt_chars / 1e6 * entry["in"])
        total += ceiling
        lines.append(f"  {model}: {calls} calls, ceiling {_rupees(round(ceiling, 6))}")
    lines.append(f"  total ceiling {_rupees(round(total, 6))}")
    return "\n".join(lines)


def _confirm_on_stdin(planned: int) -> bool:
    reply = input(f"proceed with {planned} real calls? [y/N] ")
    return reply.strip().lower() in ("y", "yes")


# -- scoring: prompt, rubric and answer in; a typed 0/1/2 out ------------------

SCORES_PATH = Path(__file__).resolve().parents[1] / "data" / "scores.csv"


def cmd_score(args, input_fn=input, output=print, scores_path=None,
              runs_base=None) -> int:
    """Walk unscored answers, show each with its prompt and rubric, record 0/1/2.

    The score comes only from what a human types. This command never
    invents, defaults or estimates one, and it never overwrites an existing
    score unless --force was passed.
    """
    run_dir = _find_run_dir(args.run, base=runs_base)
    if run_dir is None:
        print(f"no run found for {args.run or '(newest)'}", file=sys.stderr)
        return 2
    rows = store_mod.RunStore(run_dir.name, run_dir).read_rows()
    scores_path = Path(scores_path) if scores_path else SCORES_PATH
    prompts, _ = prompt_set.load_prompts()
    by_id = {prompt["id"]: prompt for prompt in prompts}

    existing = _read_scores(scores_path)
    pending, scored_count, unscoreable = [], 0, 0
    for row in rows:
        if row.get("error_code") or not (row.get("text") or "").strip():
            unscoreable += 1     # an errored or empty cell has no answer to read
            continue
        key = (row["run_id"], row["model"], row["prompt_id"])
        if key in existing and not args.force:
            scored_count += 1
            continue
        pending.append((key, row))

    if not pending:
        output(f"nothing to score in run {run_dir.name}: "
                f"{scored_count} already scored, {unscoreable} with no answer.")
        return 0

    output(f"scoring {len(pending)} answer(s) from run {run_dir.name}")
    output(f"rubric:\n{prompt_set.load_rubric()}")
    recorded = 0
    for index, (key, row) in enumerate(pending, 1):
        prompt = by_id[row["prompt_id"]]
        output(f"\n[{index}/{len(pending)}] {row['model']} · {row['prompt_id']}")
        output(f"prompt: {prompt['text']}")
        output(f"rubric: {prompt['rubric']}")
        output(f"answer: {row['text']}")
        while True:
            reply = input_fn("score (0/1/2, q to stop): ").strip()
            if reply in ("q", ""):
                output(f"stopped after {recorded} score(s); "
                       f"{scores_path} holds everything recorded so far.")
                return 0
            if reply in ("0", "1", "2"):
                existing[key] = int(reply)
                _write_scores(scores_path, existing)
                recorded += 1
                break
            output("enter 0, 1 or 2 (or q to stop)")
    output(f"recorded {recorded} score(s) in {scores_path}")
    return 0


def _find_run_dir(run_id=None, base=None):
    """A run directory by run_id, or the newest one there is."""
    if run_id is None:
        return newest_run_dir(base)
    root = Path(base) if base is not None else store_mod.RUNS_DIR
    for hit in sorted(root.glob(f"*/{run_id}")):
        return hit
    return None


def _read_scores(path) -> dict:
    """Existing scores keyed (run_id, model, prompt_id)."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {(row["run_id"], row["model"], row["prompt_id"]): int(row["score"])
                for row in csv.DictReader(fh)}


def _write_scores(path, scores: dict) -> None:
    """Rewrite scores.csv in key order after every recorded answer.

    This file is the human record, not the append-only JSONL; a full,
    ordered rewrite after each score is what makes the walk resumable.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["run_id", "model", "prompt_id", "score"])
        for (run_id, model, prompt_id), score in sorted(scores.items()):
            writer.writerow([run_id, model, prompt_id, score])


if __name__ == "__main__":
    sys.exit(main())
