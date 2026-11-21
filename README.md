# Bhasha Bench

An Indic-language benchmark for Sarvam Token Factory's six serverless models.
The same 12 Hindi, Tamil, Bengali and Hinglish prompts go to every model,
and each answer is measured on what actually matters to a developer picking
a model: did it answer in the script that was asked for, how fast did the
first token arrive, what did it cost in rupees, and did it follow the
instructions. A one-page static leaderboard presents it all, and every
number on it is reproducible from a clean clone for the price of one run.

## What it measures

- **Script fidelity** - the share of an answer's letters in the requested
  output script, from Unicode ranges (Devanagari, Tamil, Bengali, Latin),
  with labels for romanised, English and mixed drift. Deterministic, no
  model judges another model.
- **Latency** - time-to-first-token and total time, measured from the
  streaming call, reported as p50/p90 per model.
- **Cost** - computed from the API's own `usage` token counts times the
  dated registry prices. Never estimated from character counts.
- **Instructions** - whether the answer met the machine-checkable
  constraints its prompt declares (sentence counts, line counts, script
  bans, a required mention). x/12.
- **Correct** - whether the answer contains the expected value, on the four
  prompts that declare one. x/4.

## The recorded run

Run `2026-11-21T165953`: 12 prompts x 6 models, 72 calls, 0 errors,
total cost **₹3.717271**. Live version: serve `site/` and open the page.

| model | fidelity | TTFT p50 | ₹ per answer | instructions | correct |
| --- | --- | --- | --- | --- | --- |
| sarvam-105b | 93.7% | 4,804 ms | ₹0.0255 | 12/12 | 4/4 |
| sarvam-105b-conversations | 97.7% | 786 ms | ₹0.0040 | 11/12 | 3/4 |
| glm5.3 | 95.4% | 2,125 ms | ₹0.1769 | 7/12 | 4/4 |
| glm5.3-flash | 94.6% | 3,062 ms | ₹0.0181 | 6/12 | 3/4 |
| gemma4 | 96.4% | 2,245 ms | ₹0.0632 | 6/12 | 2/4 |
| deepseekv4.1-flash-1017 | 96.6% | 2,536 ms | ₹0.0221 | 11/12 | 3/4 |

Reading notes:

- n=1 per cell; directional, not definitive.
- Prices are as of 2026-11-20 from
  https://www.sarvam.ai/token-factory/pricing, excluding GST.
  `sarvam-105b`, `sarvam-105b-conversations` and
  `deepseekv4.1-flash-1017` are on introductory rates through the end of
  2026, so the ranking may flip when those end.
- The "correct" column is strict by design: Devanagari digits are
  normalised to ASCII but Bengali digits are not, and the value must
  appear in its two-decimal form (`172.50`). Four answers that wrote
  ১৭২.৫০ or `172.5` count as incorrect - their arithmetic was right, the
  form was not. These are findings about formatting behaviour, not
  mistakes in the maths.

## Quickstart

    python3 -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    export SARVAM_API_KEY=...        # read from the environment only; .env is gitignored
    make run                          # 72 calls, concurrency 3; prints a cost projection first

Then publish and view the leaderboard:

    make build                        # writes site/data/leaderboard.json
    python3 -m http.server --directory site
    # open http://localhost:8000

A full run stays well inside Pay-as-you-go rate limits (50-60 req/min,
enforced per account). One prompt to one model:

    python3 -m bench.cli run --models sarvam-105b --prompts hi-1

## Commands

| command | what it does |
| --- | --- |
| `make test` | the full test suite - no network, no API key |
| `make run` | every prompt to every model, with a cost gate before spending |
| `make smoke` | one live call to the default model (needs the key) |
| `make smoke-check` | verifies the newest recorded row and prints it |
| `make score` | human 0-2 scoring walk over the answers (optional, offline) |
| `make build` | aggregates the newest run into `site/data/leaderboard.json` |

`build` defaults to the newest run; pass `--run <run_id>` to publish another
one (deliberate side runs, for example).

## How the harness works

    prompts/prompts.yaml  -->  bench/runner (streaming, usage capture)  -->  rows, one JSON object per line
                                    |                                            |
                             bench/registry (prices)                 bench/metrics + bench/checks
                                    |                                            |
                                    '---- cost in INR per call ---->  site/data/leaderboard.json  -->  site/index.html

- Model IDs and prices live only in `bench/registry.py`, dated and sourced
  by URL. Nothing else in the codebase types a model ID or a price.
- The prompt set is fixed content in `prompts/prompts.yaml`, twelve
  prompts with language, script, category, rubric and machine-checkable
  expectations. Every run records the prompt-set hash, and `build` refuses
  a run whose hash does not match the file - the drill-down would
  otherwise show prompt text that did not produce those answers.
- Calls are streamed (`include_usage`), bounded at `max_tokens=1500`, sent
  at `reasoning_effort=low`, three in flight. `429` and `503` retry with
  exponential backoff (max 4 attempts, `Retry-After` honoured); a failed
  call is recorded as a row carrying its error code, never dropped.
  `402`/`403` stop the run and keep what exists.
- A missing usage block stores nulls - the cost column shows n/a, never a
  guess. A model that rejects a `reasoning_effort` value is retried once
  without the field and records `reasoning_effort: null`.
- Rows are append-only, one file per run under
  `data/runs/<date>/<run_id>/`; no run ever rewrites another's rows.
- The site never calls the API. It fetches one committed JSON file; no
  framework, no build step, no external URL. GitHub Pages serves it as-is.

## The deterministic checks

`bench/checks.py` grades what can be graded mechanically, from the
expectation keys each prompt declares, and nothing else: `answer_correct`
(True / False / None) and `constraints_met` (bool). The summarise prompts
and one tone instruction are not machine-checkable - those cells render as
an em dash with a "not checkable" tooltip, and None never becomes False.

Every rule and judgement call lives in the module's docstring, visible on
purpose: sentences split on the danda, full stop, ?/! and newline with a
two-character floor; "three points" uses the same count; lines are
non-empty lines; values are matched after Devanagari-digit normalisation
and currency/comma/space stripping, in two-decimal form. No model ever
scores another model here.

## Scoring: a blind spot-check

`make score` walks the answers with their prompts and rubrics and records
the 0, 1 or 2 you type into `data/scores.csv`. Scores stay offline and are
deliberately never published - the leaderboard's columns are automated
and deterministic, and hand-scoring is how a human spot-checks the
automation without seeing what it concluded.

## Honest labels

- n=1 per cell: directional, not definitive. One call per model per
  prompt measures a sample, not a distribution.
- Introductory pricing (three models) runs through the end of 2026; every
  rupee figure and possibly the ranking change after that. The generated
  index at `docs.sarvam.ai/api/token-factory/llms.txt` disagrees with the
  pricing page on two models' rates; this project pins the pricing page
  and the date it was read.
- Latency is measured from one machine on one connection. It compares
  models under identical conditions; it is not a promise about production
  timing.
- `finish_reason: "length"` renders as "hit token budget" - a budget
  failure, not a model failure, and never hidden.

## Repository layout

    bench/registry.py     the six models; the only place an ID or a price lives
    bench/prompts.py      loads prompts.yaml; experiment hash (check keys excluded)
    bench/runner.py       the streaming call, retry policy, the fan-out
    bench/store.py        one directory per run: append-only results.jsonl + run.json
    bench/metrics.py      script classifier, p50/p90, cost aggregation
    bench/checks.py       deterministic instruction and answer checks
    bench/leaderboard.py  a run's rows -> site/data/leaderboard.json
    bench/cli.py          run / score / build
    bench/smoke.py        verifies the newest row against the smoke criteria
    prompts/prompts.yaml  the 12 prompts and their expectations - fixed content
    site/index.html       the leaderboard and drill-down, one static page
    site/data/            leaderboard.json, written by `make build`
    tests/                the suite: fakes and fixtures, no network, no key
    tests/fixtures/      rows.json - eight real rows, verbatim, for the tests

## Requirements

Python 3.12 or newer (`pyproject.toml` pins `requires-python = ">=3.12"`).
Three dependencies: `openai` (pointed at `https://api.sarvam.ai/v2`),
`pyyaml`, `pytest`. The test suite runs with no network and no API key:
`make test`.
