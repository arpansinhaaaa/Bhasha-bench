# Bhasha Bench

An Indic-language harness for Sarvam Token Factory's six serverless models:
the same 12 Hindi / Tamil / Bengali / Hinglish prompts to every model, with
time-to-first-token, real token counts and rupee cost recorded per call.

Status: Day 2 built - the 72-call full run of 2026-11-21 is recorded,
metrics, the leaderboard builder, the deterministic checks and the static
site all work. The leaderboard grades instructions and answers
mechanically (bench/checks.py) and publishes no human quality number;
`make score` remains, unpublished, as a human's blind spot-check.

## Quickstart

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    export SARVAM_API_KEY=...        # read from the env only; .env is gitignored
    python3 -m bench.cli run --models all --prompts all

A full run is 72 calls at concurrency 3, inside Pay-as-you-go rate limits
(50-60 req/min, enforced per account). One prompt to one model:

    python3 -m bench.cli run --models sarvam-105b --prompts hi-1

Python 3.12 or newer (`pyproject.toml` pins `requires-python = ">=3.12"`).
This build was executed on Python 3.14.7 and uses nothing 3.13+-specific,
so 3.12 runs it unchanged.

Model IDs and prices live only in `bench/registry.py`, dated and sourced
there. The prompt set is `prompts/prompts.yaml`, fixed content; if a prompt
looks wrong, report it - do not edit it in place.

## Test

    make test

No network, no API key: the suite runs against fake clients.

## Live smoke test (run it yourself, with SARVAM_API_KEY exported)

    make smoke            # python -m bench.cli run --prompts hi-1
                          # (the registry's default model, sarvam-105b)
    make smoke-check      # verifies the newest row and prints it verbatim

The row must show: ttft_ms > 0, total_ms >= ttft_ms, non-empty Devanagari
text answering the Rs 172.50 question, finish_reason "stop", and a cost_inr
that recomputes from the token counts and `bench/registry.py`. smoke-check
prints PASS/FAIL per criterion. If anything fails, report what you see and
stop; the harness never runs the live call itself.

## Cost projection and confirmation

`run` prints a projected cost ceiling before it spends anything - from the
registry's prices and the prompt set: completions capped at
max_tokens=1500, input over-estimated at one token per prompt character.
It then asks y/N; `--dry-run` prints the same projection and exits without
sending or writing anything, and `--yes` skips the prompt. Every call line
carries the running rupee total, so a runaway is visible in the first ten
calls. A 402 (credits) or 403 (key) stops the run and keeps what exists.

## Scoring (yours, by hand - a blind spot-check, not the leaderboard)

    make score                      # python -m bench.cli score
    python3 -m bench.cli score --run <run_id> [--force]

Walks the answers that carry no score yet, shows each with its prompt and
its rubric line, and records the 0, 1 or 2 you type into
data/scores.csv, keyed by run_id + model + prompt_id. The score comes only
from what you type: this command never invents, defaults or estimates one,
and it never overwrites an existing score without --force. Errored and
empty cells are skipped - they carry their error codes in the table
instead. Stop with q; the walk picks up where it left off.

Scores stay in data/scores.csv and are deliberately never published: the
leaderboard's Instruction and Correct columns are deterministic checks
(bench/checks.py), and scoring is how a human spot-checks those checks,
blind to what the automation concluded.

## Publish the leaderboard

    make build                        # python -m bench.cli build
    python3 -m bench.cli build --run <run_id> [--out PATH]

Aggregates a finished run into site/data/leaderboard.json - the only file
the static page ever fetches - including two deterministic checks per
answer: instructions followed (the constraints prompts.yaml declares,
x/12) and answers correct (the expected value, where a prompt declares
one, x/4 - only four prompts are value-checkable, so the denominator is
printed, never implied). No model scored another model, and no quality
opinion is published at all; scores.csv stays offline as the human's
blind spot-check.
It defaults to the newest run, so if a deliberate side run (the
max-effort cell, say) is newer than your main run, pass `--run` for the
main one. The builder refuses a run whose recorded prompt-set hash no
longer matches prompts/prompts.yaml (the hash covers the experiment
content; machine-check expectation keys are excluded, so adding those
does not invalidate runs): the drill-down would show prompt text that did
not produce those answers, and a complete-looking wrong table is worse
than a refusal. Errored cells stay in the table with their error codes,
missing cells are marked n/a, and `finish_reason: "length"` shows as
"hit token budget" rather than as an error.

    python3 -m http.server --directory site    # then open the page locally

The page is one static file with no build step: `site/index.html` fetches
`data/leaderboard.json` and renders the sortable table plus the
per-prompt drill-down (all six answers, each with latency, tokens, cost
and the script it actually arrived in). No framework, no webfont, no
other URL; GitHub Pages serves it as-is.

## Metrics

bench/metrics.py classifies script fidelity from the Unicode ranges in
handoff Block G - deva U+0900-U+097F, taml U+0B80-U+0BFF, beng
U+0980-U+09FF, latin a-z A-Z - with labels native_script, romanized,
english, mixed at the 20% lines, and computes p50/p90 latency percentiles
and per-model cost aggregates. The blocks alone cannot tell romanised
Hindi from English, so a small deterministic lexicon of English function
words draws that line (>= 25% function words means English). No model ever
judges another model here.

## Deterministic checks

bench/checks.py grades what can be graded mechanically, from the
expectation keys each prompt declares in prompts.yaml, and nothing else.
The full rules - including every judgement call - live in that module's
docstring on purpose. The ones worth knowing before reading the table:

- Instructions (x/12): exact sentence counts (split on danda, full stop,
  ?/! and newline, with a two-character floor), exactly three points on
  hi-3, exactly three lines on he-2, Devanagari forbidden on hi-3, Latin
  forbidden on ta-3/bn-3/he-1, and a refund mention on he-2. A decimal
  number such as 172.50 splits at its full stop and inflates the sentence
  count - the constrained prompts contain no decimals, so the edge is
  documented rather than smoothed over.
- Correct (x/4): only hi-1, ta-1, bn-1 and he-3 declare the value
  172.50, so the denominator is 4, printed as such everywhere. Devanagari
  digits are normalised; Bengali digits are NOT (the rule is exactly that
  narrow), so an answer that writes ১৭২.৫০ counts as incorrect even when
  the maths is right - and "172.5" fails the two-decimal form too. Both
  behaviours show up in the recorded run and are findings, not bugs.
- The three summarise prompts and he-2's tone are not machine-checkable:
  those cells render as an em dash with a "not checkable" tooltip, and
  None never becomes False.

## What a run writes

    data/runs/<YYYY-MM-DD>/<run_id>/results.jsonl   one JSON object per line, append-only
    data/runs/<YYYY-MM-DD>/<run_id>/run.json        run_id, timestamp, prompt-set hash,
                                                    model list, total cost

Each row: run_id, model, prompt_id, reasoning_effort, ttft_ms, total_ms,
prompt_tokens, completion_tokens, cached_tokens, cost_inr, text,
finish_reason, error_code, retried, attempts. A failed call is a row carrying
its error code, never a dropped line. A missing usage block means nulls,
never estimates from character counts. Rows are never rewritten or reordered;
the run's cost total is the sum of the row costs the API made possible.

Each run owns its directory under data/runs/<YYYY-MM-DD>/<run_id>, so no two
runs ever share or overwrite a run.json; if two runs start in the same
second, the second run_id gets a -2 suffix. A deliberate extra run - one
model, one prompt, a chosen --reasoning-effort - is just another run
directory, so a max-effort cell never mixes into a main run's table.
`run.json` is written when the
run opens (total unknown) and again when it closes. A 402 (credits) or 403
(key) stops the run and keeps every row written so far.

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

## Known issues

- The PRD's P2 line "3 Hinglish (Latin script)" is imprecise. In
  prompts.yaml, `script` is the requested OUTPUT script (Block B's header is
  authoritative), so he-1 - Hinglish input demanding a Devanagari answer -
  declares `script: deva`. This project treats script as the requested
  output script everywhere.
- The generated index at docs.sarvam.ai/api/token-factory/llms.txt
  disagrees with the pricing page on two models' rates; see Honest labels.

## Day 1 probe (to be recorded here after the first live run)

Which `reasoning_effort` values each model accepts (`none` / `low` /
`medium` / `high` / `max`) - two doc pages currently disagree about `none`
on `sarvam-105b`. Run one prompt per model per value and read the rows; a
model that rejects a value is probed once without the field and records
`reasoning_effort: null`.

## Layout

    bench/registry.py    the six models, prices dated and sourced (Block C)
    bench/prompts.py     loads prompts.yaml; experiment hash (check keys excluded)
    bench/runner.py      one_call: Block D's request + retry policy; the fan-out
    bench/store.py       one directory per run: append-only results.jsonl + run.json
    bench/cli.py         run / score / build
    bench/metrics.py     script classifier (Block G ranges), p50/p90, cost aggregation
    bench/checks.py      deterministic instruction and answer checks, no model judge
    bench/leaderboard.py a run's rows + the checks -> site/data/leaderboard.json (P8)
    bench/smoke.py       verifies the newest row against the smoke criteria
    prompts/prompts.yaml the 12 prompts (Block B) + their machine-check expectations
    site/index.html      the leaderboard and drill-down: one static page, no build step
    site/data/           leaderboard.json, written by `make build`, committed
    tests/fixtures/      rows.json: 8 real rows, verbatim, the tests' only run data
    tests/               registry, prompts, runner, store, smoke, CLI, leaderboard,
                         checks, site; fakes, no network
    pyproject.toml      metadata: requires-python >= 3.12
