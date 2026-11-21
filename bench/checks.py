"""Deterministic answer checks. No model judges another model here.

Two pure entry points over rows that already exist:

    answer_correct(row, prompt)  -> True | False | None
    constraints_met(row, prompt) -> bool

`prompt` is the prompt dict from bench.prompts.load_prompts(); the
expectation keys it reads (expected_value, exact_sentences,
exactly_three_points, forbid_deva, forbid_latin, exact_lines,
must_mention_any) live in prompts/prompts.yaml and nowhere else. Nothing
here reads files, calls the network, or estimates.

The rules and their judgement calls, visible on purpose:

Sentences. Split on danda (।), full stop (.), question mark (?),
exclamation (!) and newline; drop empty fragments and any fragment shorter
than two characters. This is a judgement call and it has a sharp edge kept
deliberately: a decimal number such as 172.50 splits at the full stop into
"172" and "50", both of which survive the length floor, so an answer full
of decimal numbers counts extra "sentences". The prompts that carry
sentence constraints (hi-2, ta-2, bn-2, ta-3, bn-3) do not involve decimal
arithmetic, so the edge does not bite there.

"Three points" (hi-3). Counted with the same sentence rule: a numbered
list "1. ...\n2. ...\n3. ..." yields exactly three kept fragments (the
bare digits are dropped by the two-character floor), and three prose
sentences do too. An intro line, a heading or any extra sentence counts
higher and fails. A judgement call, stated as one.

Numbers. Devanagari digits (०-९) are normalised to ASCII - the only Indic
digit range normalised, exactly as specified; Bengali digits (০-৯) are not.
The rupee sign, commas and spaces are stripped, then the expected value
formatted to two decimals ("172.50") is searched for as a substring. A
numerically equal but differently written value ("172.5", "172") does not
match. A judgement call, stated as one.

Lines (he-2). Non-empty lines after stripping.

Mentions (he-2). Case-insensitive substring match on any listed phrase.

Empty or errored answers. An answer that was never produced followed no
instruction, so constraints fail outright - and correctness on a
checkable prompt is False for the same reason. Correctness on a
non-checkable prompt is None, and None never becomes False.
"""

from __future__ import annotations

import re

from bench import metrics

DEVA_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
VALUE_STRIP = "₹,"                       # currency symbol and grouping commas

_SENTENCE_SPLIT = re.compile(r"[।.!?\n]")


def answer_correct(row: dict, prompt: dict) -> bool | None:
    """Is the answer's correctness checkable, and does the value appear in it?

    None where correctness is not machine-checkable: every prompt without an
    expected_value (the three summarise prompts, and he-2's tone). True where
    the normalised answer contains the value to two decimals, False otherwise
    - including when the call errored or produced no text, because an answer
    that does not exist is not correct. None never becomes False.
    """
    if "expected_value" not in prompt:
        return None
    if row.get("error_code") or not (row.get("text") or "").strip():
        return False
    return value_present(row["text"], prompt["expected_value"])


def constraints_met(row: dict, prompt: dict) -> bool:
    """Did the answer meet every constraint the prompt declares?

    True only if every declared constraint passes (a prompt declaring none is
    vacuously met). An errored or empty answer fails outright: it followed no
    instruction, and it fails without raising.
    """
    text = row.get("text") or ""
    if row.get("error_code") or not text.strip():
        return False

    if "exact_sentences" in prompt and count_sentences(text) != prompt["exact_sentences"]:
        return False
    if prompt.get("exactly_three_points") and count_sentences(text) != 3:
        return False
    if "exact_lines" in prompt and count_lines(text) != prompt["exact_lines"]:
        return False
    if prompt.get("forbid_deva") and metrics.letter_counts(text)["deva"]:
        return False
    if prompt.get("forbid_latin") and metrics.letter_counts(text)["latin"]:
        return False
    if "must_mention_any" in prompt and not mentions_any(text, prompt["must_mention_any"]):
        return False
    return True


# -- the counting rules, each one visible and dumb on purpose -----------------


def count_sentences(text: str) -> int:
    """Fragments split on danda/full stop/?/!/newline; each is stripped, and
    fragments that come out empty or under two characters are dropped."""
    flattened = text.replace("\r\n", "\n").replace("\r", "\n")
    return len([f for f in _SENTENCE_SPLIT.split(flattened)
                if len(f.strip()) >= 2])


def count_lines(text: str) -> int:
    """Non-empty lines after stripping."""
    return len([line for line in text.splitlines() if line.strip()])


def value_present(text: str, value: float) -> bool:
    """The value, to two decimals, as a substring after normalisation.

    Devanagari digits become ASCII; the rupee sign, commas and spaces are
    stripped. "172.5" or "172" do not match 172.50 - the two-decimal form is
    the contract.
    """
    needle = f"{float(value):.2f}"
    flattened = text.translate(DEVA_DIGITS)
    for ch in VALUE_STRIP:
        flattened = flattened.replace(ch, "")
    return needle in "".join(flattened.split())


def mentions_any(text: str, phrases: list[str]) -> bool:
    """Case-insensitive: does the text contain at least one listed phrase?"""
    lowered = text.lower()
    return any(phrase.lower() in lowered for phrase in phrases)
