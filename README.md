# Bhasha Bench

An Indic-language harness for Sarvam Token Factory's six serverless models:
the same 12 Hindi / Tamil / Bengali / Hinglish prompts to every model, with
time-to-first-token, real token counts and rupee cost recorded per call.

Status: Day 1 - the harness. The leaderboard site, the human scorer and the
local demo server are Day 2 and are not built yet.

## Quickstart

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    export SARVAM_API_KEY=...        # read from the env only; .env is gitignored
    python3 -m bench.cli run --models all --prompts all

A full run is 72 calls at concurrency 3, inside Pay-as-you-go rate limits
(50-60 req/min, enforced per account). One prompt to one model:

    python3 -m bench.cli run --models sarvam-105b --prompts hi-1

Model IDs and prices live only in `bench/registry.py`, dated and sourced
there. The prompt set is `prompts/prompts.yaml`, fixed content; if a prompt
looks wrong, report it - do not edit it in place.

## Test

    make test

No network, no API key: the suite runs against fake clients.

## What a run writes

    data/runs/<YYYY-MM-DD>/results.jsonl   one JSON object per line, append-only
    data/runs/<YYYY-MM-DD>/run.json        run_id, timestamp, prompt-set hash,
                                            model list, total cost

Each row: run_id, model, prompt_id, reasoning_effort, ttft_ms, total_ms,
prompt_tokens, completion_tokens, cached_tokens, cost_inr, text,
finish_reason, error_code, retried, attempts. A failed call is a row carrying
its error code, never a dropped line. A missing usage block means nulls,
never estimates from character counts. Rows are never rewritten or reordered;
the run's cost total is the sum of the row costs the API made possible.

`run.json` is written when the run opens (total unknown) and again when it
closes. A 402 (credits) or 403 (key) stops the run and keeps every row
written so far.

## Honest labels

- Prices are dated 2026-11-20 from https://www.sarvam.ai/token-factory/pricing,
  excluding GST. `sarvam-105b`, `sarvam-105b-conversations` and
  `deepseekv4.1-flash-1017` are on introductory rates through the end of
  2026, so every rupee figure changes then - and the price ranking may flip.
  (The generated index at docs.sarvam.ai/api/token-factory/llms.txt
  disagrees on two models' rates; this project pins the pricing page.)
- n=1 per cell: directional, not definitive.
- Latency is measured from one machine on one connection. It compares models
  under identical conditions; it is not a promise about production timing.

## Day 1 probe (to be recorded here after the first live run)

Which `reasoning_effort` values each model accepts (`none` / `low` /
`medium` / `high` / `max`) - two doc pages currently disagree about `none`
on `sarvam-105b`. Run one prompt per model per value and read the rows; a
model that rejects a value is probed once without the field and records
`reasoning_effort: null`.

## Layout

    bench/registry.py    the six models, prices dated and sourced (Block C)
    bench/prompts.py     loads prompts.yaml, hashes the raw bytes
    bench/runner.py      one_call: Block D's request + retry policy; the fan-out
    bench/store.py        append-only results.jsonl + run.json
    bench/cli.py         run --models <ids|all> --prompts <ids|all>
    prompts/prompts.yaml the 12 prompts (Block B) - fixed experimental content
    tests/               registry, prompts, runner, store, CLI; fakes, no network
