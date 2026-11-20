"""Bhasha Bench command line.

    python -m bench.cli run --models <ids|all> --prompts <ids|all>

Prints one line per call (model, ttft, tokens, cost - or the error the call
carried) and a total at the end. Rows are appended to
data/runs/<YYYY-MM-DD>/results.jsonl, one JSON object per line, never
rewritten. SARVAM_API_KEY is read from the environment only.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from bench import prompts as prompt_set
from bench import registry
from bench import runner
from bench import store as store_mod

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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    return 2  # unreachable: subparsers are required


def cmd_run(args, client=None, runs_base=None) -> int:
    """Run the fan-out and record it. `client` and `runs_base` are test seams."""
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

    if client is None and not os.environ.get("SARVAM_API_KEY"):
        # The key is read from the environment only; never echoed.
        print("SARVAM_API_KEY is not set. Export it and re-run.", file=sys.stderr)
        return 2

    run = store_mod.RunStore.create(base=runs_base)
    planned = len(models) * len(selected)
    print(f"run {run.run_id} · {len(models)} model(s) × {len(selected)} prompt(s) "
          f"· effort {args.reasoning_effort} · {planned} call(s) planned")
    # Metadata first, so a run that dies mid-flight is still identified.
    run.write_metadata(models=models, prompt_set_hash=prompt_hash)

    tally = {"calls": 0, "errors": 0}

    def on_row(row: dict) -> None:
        stamped = {"run_id": run.run_id, **row}
        row.clear()
        row.update(stamped)
        run.append_row(row)
        print(_format_line(row))
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


def _format_line(row: dict) -> str:
    """One line per call: model, ttft, tokens, cost - or the error it carried."""
    head = f'{row["model"]}  {row["prompt_id"]}'
    if row["error_code"]:
        return f'{head}  ERROR {row["error_code"]}  attempts {row["attempts"]}'
    ttft = f'{row["ttft_ms"]}ms' if row["ttft_ms"] and row["ttft_ms"] > 0 else "n/a"
    if row["prompt_tokens"] is None:
        tokens = "n/a"
    else:
        tokens = f'{row["prompt_tokens"]}/{row["completion_tokens"]}'
    note = "  (retried)" if row["retried"] else ""
    return f"{head}  ttft {ttft}  tokens {tokens}  {_rupees(row['cost_inr'])}{note}"


def _rupees(amount) -> str:
    """Rupees for display: two decimals once it is a rupee, four below that."""
    if amount is None:
        return "n/a"
    return f"₹{amount:.2f}" if amount >= 1 else f"₹{amount:.4f}"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'s' if count != 1 else ''}"


if __name__ == "__main__":
    sys.exit(main())
