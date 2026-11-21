"""The deterministic checks (bench/checks.py), offline, on committed fixtures.

The real inputs are tests/fixtures/rows.json: eight rows copied verbatim
(no text touched) from run 2026-11-21T165953 - two models x four prompts
(maths hi-1, summarise hi-2, script-switch hi-3, Hinglish instruction
he-2). No API call, no key, no network; nothing here could spend money.

A few cases the real fixtures cannot reach - a Devanagari-digit answer, an
empty answer, and one isolated failure per constraint the real rows happen
to pass - are authored as synthetic rows inside this file and marked as
such. They are typed by hand, never copied from a run.
"""

import json
from pathlib import Path

from bench import checks, prompts as prompt_set

FIXTURES = Path(__file__).parent / "fixtures" / "rows.json"

# What the real runs recorded before the expectation keys existed: adding
# machine-check keys must not have changed the experiment hash.
RECORDED_RUN_HASH = "d8d8b56640a1803f1f101cdfe31dfe831b830623443519361618b0b9c38be12b"

EXPECTED_FIELDS = {
    "hi-1": {"expected_value": 172.50},
    "ta-1": {"expected_value": 172.50},
    "bn-1": {"expected_value": 172.50},
    "he-3": {"expected_value": 172.50},
    "hi-2": {"exact_sentences": 4},
    "ta-2": {"exact_sentences": 4},
    "bn-2": {"exact_sentences": 4},
    "hi-3": {"exactly_three_points": True, "forbid_deva": True},
    "ta-3": {"exact_sentences": 3, "forbid_latin": True},
    "bn-3": {"exact_sentences": 3, "forbid_latin": True},
    "he-1": {"forbid_latin": True},
    "he-2": {"exact_lines": 3, "must_mention_any": ["refund", "wapas", "paise wapas"]},
}


def _rows():
    return json.loads(FIXTURES.read_text(encoding="utf-8"))


def _row(model, prompt_id):
    matches = [r for r in _rows()
               if r["model"] == model and r["prompt_id"] == prompt_id]
    assert len(matches) == 1, f"fixture row {model}/{prompt_id} missing"
    return matches[0]


def _prompt(prompt_id):
    prompts, _ = prompt_set.load_prompts()
    return {p["id"]: p for p in prompts}[prompt_id]


def _synthetic(prompt_id, text):
    """An authored row, marked as such - never a copy of a real answer."""
    return {"model": "synthetic", "prompt_id": prompt_id, "text": text,
            "error_code": None}


# -- the expectations are exactly the specified ones, nothing inferred --------


def test_every_prompt_carries_exactly_the_specified_expectations():
    content_keys = {"id", "language", "script", "category", "text", "rubric"}
    prompts, _ = prompt_set.load_prompts()
    for prompt in prompts:
        expected = EXPECTED_FIELDS[prompt["id"]]
        for key, value in expected.items():
            assert prompt[key] == value, (prompt["id"], key)
        extra = {k for k in prompt if k not in content_keys} - set(expected)
        assert extra == set(), (prompt["id"], extra)


def test_adding_expectations_keeps_the_runs_experiment_hash():
    """Runs recorded before the expectations exist must still build."""
    _, prompt_hash = prompt_set.load_prompts()
    assert prompt_hash == RECORDED_RUN_HASH


# -- fixtures that pass -------------------------------------------------------


def test_both_models_answer_hi_1_with_the_172_50_value():
    for model in ("sarvam-105b", "glm5.3"):
        row = _row(model, "hi-1")
        assert checks.answer_correct(row, _prompt("hi-1")) is True
        # hi-1 declares no instruction constraints: nothing to violate.
        assert checks.constraints_met(row, _prompt("hi-1")) is True


def test_both_models_summarise_in_exactly_four_sentences():
    for model in ("sarvam-105b", "glm5.3"):
        row = _row(model, "hi-2")
        assert checks.constraints_met(row, _prompt("hi-2")) is True


def test_sarvam_keeps_three_points_and_roman_script_on_hi_3():
    row = _row("sarvam-105b", "hi-3")
    assert checks.constraints_met(row, _prompt("hi-3")) is True


def test_sarvam_he_2_is_three_lines_and_mentions_refund():
    row = _row("sarvam-105b", "he-2")
    assert checks.constraints_met(row, _prompt("he-2")) is True


# -- fixtures that fail, one per constraint -----------------------------------


def test_glm_hi_3_extra_sentences_fail_the_three_points_rule():
    row = _row("glm5.3", "hi-3")
    # the markdown headings survive the two-character floor, so the count
    # runs past three - the rule is dumb on purpose and the test says so
    assert checks.count_sentences(row["text"]) > 3
    assert checks.constraints_met(row, _prompt("hi-3")) is False


def test_glm_he_2_five_lines_fail_the_exact_lines_rule():
    row = _row("glm5.3", "he-2")
    assert checks.count_lines(row["text"]) == 5
    assert checks.constraints_met(row, _prompt("he-2")) is False


def test_a_summarise_answer_with_extra_sentences_fails_exact_sentences():
    # synthetic: neither real fixture row fails this constraint
    text = "एक। दो। तीन। चार। पाँच।"
    row = _synthetic("hi-2", text)
    assert checks.count_sentences(text) == 5
    assert checks.constraints_met(row, _prompt("hi-2")) is False


def test_one_devanagari_character_fails_forbid_deva():
    # synthetic: three clean points, one Devanagari word slipped in
    row = _synthetic("hi-3", "1. Hisab rakho\n2. Nuksan bacho\n3. Loss रोको")
    assert checks.constraints_met(row, _prompt("hi-3")) is False


def test_one_latin_word_fails_forbid_latin():
    # synthetic: a Devanagari answer to he-1 with a single English word
    mixed = "यूपीआई से पैसे भेजते समय सबसे common गलती रिसीवर का नाम गलत होना है।"
    assert checks.constraints_met(_synthetic("he-1", mixed), _prompt("he-1")) is False
    clean = "यूपीआई से पैसे भेजते समय सबसे आम गलती रिसीवर का नाम गलत होना है।"
    assert checks.constraints_met(_synthetic("he-1", clean), _prompt("he-1")) is True


def test_a_reply_without_any_listed_phrase_fails_must_mention_any():
    # synthetic: three polite lines that never offer the refund
    text = ("Sir, sorry for the delay.\nWe are checking the issue.\n"
            "We will update you soon.")
    row = _synthetic("he-2", text)
    assert checks.count_lines(text) == 3
    assert checks.constraints_met(row, _prompt("he-2")) is False


# -- the specified edges ------------------------------------------------------


def test_devanagari_digits_still_match_172_50():
    # synthetic: the answer in Devanagari digits, as the rule requires it to
    row = _synthetic("hi-1", "एक वस्तु का विक्रय मूल्य १७२.५० रुपये है।")
    assert checks.answer_correct(row, _prompt("hi-1")) is True


def test_a_differently_written_value_does_not_match():
    # synthetic: "172.5" is numerically equal but not the two-decimal form.
    # The docstring owns this judgement call; the test pins it.
    row = _synthetic("hi-1", "विक्रय मूल्य ₹172.5 है।")
    assert checks.answer_correct(row, _prompt("hi-1")) is False


def test_a_summarise_row_returns_none_never_false():
    for model in ("sarvam-105b", "glm5.3"):
        row = _row(model, "hi-2")
        assert checks.answer_correct(row, _prompt("hi-2")) is None


def test_an_empty_text_row_fails_constraints_without_raising():
    for prompt_id in ("hi-1", "hi-2", "hi-3", "he-2"):
        row = _synthetic(prompt_id, "")
        assert checks.constraints_met(row, _prompt(prompt_id)) is False


def test_an_empty_text_row_is_false_where_checkable_none_where_not():
    assert checks.answer_correct(_synthetic("hi-1", ""), _prompt("hi-1")) is False
    assert checks.answer_correct(_synthetic("hi-2", ""), _prompt("hi-2")) is None


def test_an_errored_row_behaves_like_an_empty_one():
    row = _synthetic("hi-1", "पूरा जवाब आया ही नहीं")
    row["error_code"] = "429 model_rate_limit_exceeded_error"
    assert checks.answer_correct(row, _prompt("hi-1")) is False
    assert checks.constraints_met(row, _prompt("hi-1")) is False


def test_the_decimal_split_edge_is_counted_not_hidden():
    # The sentence rule splits at every full stop: "172.50" becomes "172"
    # and "50 ...", both above the two-character floor, so one decimal
    # number inflates the count. A judgement call that lives in the module
    # docstring; pinned here so it changes loudly.
    assert checks.count_sentences("कुल कीमत 172.50 रुपये थी।") == 2
    assert checks.count_sentences("कुल कीमत 17250 रुपये थी।") == 1
