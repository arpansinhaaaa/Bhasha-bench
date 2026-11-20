"""Script fidelity and run statistics. Deterministic, no model judge.

The script classifier is PRD section 12 and handoff Block G: one dict of
Unicode ranges, percentages counted over letters, labels native_script /
romanized / english / mixed. Two labels exist beyond those four because
honesty beats forcing a fit: 'empty' when there are no letters to count (a
blank or errored cell), and 'other_script' when the answer is mostly
neither the requested script nor Latin (say, Tamil to a Devanagari prompt).

The Unicode blocks alone cannot tell romanised Hindi from English, so a
small deterministic lexicon of English function words draws that line. It
is a heuristic, stated as one; no model ever judges another model here.
"""

from __future__ import annotations

import math
import re
from collections import namedtuple

# Block G: one dict. deva U+0900-U+097F, taml U+0B80-U+0BFF, beng
# U+0980-U+09FF, latin a-z A-Z.
SCRIPT_RANGES = {
    "deva": ((0x0900, 0x097F),),
    "taml": ((0x0B80, 0x0BFF),),
    "beng": ((0x0980, 0x09FF),),
    "latin": ((0x0041, 0x005A), (0x0061, 0x007A)),  # A-Z, a-z
}
INDIC_SCRIPTS = ("deva", "taml", "beng")

MIXED_THRESHOLD_PCT = 20.0

Classification = namedtuple("Classification", "label target_pct latin_pct")

# Common English function words. When enough of a Latin-script answer's
# words are these, the answer is English rather than romanised Hindi.
ENGLISH_FUNCTION_WORDS = frozenset("""
a about above after again all also an and any are as at be because been
before being below between both but by can could did do does down during
each even every for from further had has have having he her here hers
him his how i if in into is it its itself just me more most my no nor
not now of off on once only or other our out over own same she should
so some such than that the their them then there these they this those
through to too under until up very was we were what when where which
while who why will with would you your
""".split())

_WORD_RE = re.compile(r"[A-Za-z]+")


def letter_counts(text: str) -> dict:
    """How many letters of each script the text holds. All else is ignored."""
    counts = dict.fromkeys(SCRIPT_RANGES, 0)
    for ch in text:
        code = ord(ch)
        for script, ranges in SCRIPT_RANGES.items():
            if any(lo <= code <= hi for lo, hi in ranges):
                counts[script] += 1
                break
    return counts


def classify(text: str, script: str) -> Classification:
    """An answer's script fidelity against its requested output script.

    mixed: the target is >= 20% of letters and so is the contrast script -
    Latin for an Indic target, the Indic scripts for a Latin target.
    native_script: target >= 20% with the contrast below that. Below 20%
    target, a Latin-dominant answer is romanized or english; anything else
    is other_script. Percentages are rounded to 2 decimals.
    """
    counts = letter_counts(text)
    letters = sum(counts.values())
    if letters == 0:
        return Classification("empty", 0.0, 0.0)
    target_pct = 100.0 * counts.get(script, 0) / letters
    latin_pct = 100.0 * counts["latin"] / letters
    if script == "latin":
        contrast_pct = 100.0 * sum(counts[name] for name in INDIC_SCRIPTS) / letters
    else:
        contrast_pct = latin_pct
    if target_pct >= MIXED_THRESHOLD_PCT and contrast_pct >= MIXED_THRESHOLD_PCT:
        label = "mixed"
    elif target_pct >= MIXED_THRESHOLD_PCT:
        label = "native_script"
    elif latin_pct >= MIXED_THRESHOLD_PCT:
        label = _latin_answer_label(text)
    else:
        label = "other_script"
    return Classification(label, round(target_pct, 2), round(latin_pct, 2))


def _latin_answer_label(text: str) -> str:
    """English when enough of the Latin words are function words, else romanized."""
    words = _WORD_RE.findall(text)
    if not words:
        return "other_script"
    english = sum(1 for word in words if word.lower() in ENGLISH_FUNCTION_WORDS)
    return "english" if english / len(words) >= 0.25 else "romanized"


def percentile(values, p: float):
    """Linear-interpolation percentile; None for no values.

    percentile([1..10], 50) == 5.5 and percentile([1..10], 90) == 9.1:
    rank = (n - 1) * p / 100, interpolated between the neighbours.
    """
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * p / 100.0
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    return float(ordered[low] + (ordered[high] - ordered[low]) * (rank - low))


def model_summary(rows: list) -> dict:
    """Per-model aggregates over result rows.

    Latency percentiles consider successful rows only (error rows carry no
    measurement, and ttft_ms of -1 means a 200 that produced no content).
    Cost means consider the cells the API made costable - a missing usage
    block leaves them out, it never drags an average down.
    """
    tallies: dict = {}
    for row in rows:
        model = row["model"]
        tallies.setdefault(model, {
            "calls": 0, "errors": 0, "costed": 0,
            "cost_inr_total": 0.0, "ttft_ms": [], "total_ms": [],
        })
        tally = tallies[model]
        tally["calls"] += 1
        if row.get("error_code"):
            tally["errors"] += 1
            continue
        cost = row.get("cost_inr")
        if cost is not None:
            tally["costed"] += 1
            tally["cost_inr_total"] += cost
        ttft = row.get("ttft_ms")
        if ttft is not None and ttft > 0:
            tally["ttft_ms"].append(ttft)
            tally["total_ms"].append(row["total_ms"])

    summary = {}
    for model, tally in tallies.items():
        costed = tally["costed"]
        summary[model] = {
            "calls": tally["calls"],
            "errors": tally["errors"],
            "costed_cells": costed,
            "cost_inr_total": round(tally["cost_inr_total"], 6),
            "cost_inr_mean": round(tally["cost_inr_total"] / costed, 6) if costed else None,
            "ttft_p50_ms": percentile(tally["ttft_ms"], 50),
            "ttft_p90_ms": percentile(tally["ttft_ms"], 90),
            "latency_p50_ms": percentile(tally["total_ms"], 50),
        }
    return summary
