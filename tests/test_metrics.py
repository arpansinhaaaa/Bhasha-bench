"""The script classifier and run statistics. Deterministic; no network, no key.

Every percentage here is hand-counted from the fixture's codepoints, so the
assertions are independent of the implementation being tested.
"""

from bench import metrics


def test_ranges_match_the_handoff():
    # Block G: deva U+0900-U+097F, taml U+0B80-U+0BFF, beng U+0980-U+09FF,
    # latin a-z A-Z.
    assert metrics.SCRIPT_RANGES["deva"] == ((0x0900, 0x097F),)
    assert metrics.SCRIPT_RANGES["taml"] == ((0x0B80, 0x0BFF),)
    assert metrics.SCRIPT_RANGES["beng"] == ((0x0980, 0x09FF),)
    assert metrics.SCRIPT_RANGES["latin"] == ((0x0041, 0x005A), (0x0061, 0x007A))


def test_letter_counts_ignore_everything_but_the_four_scripts():
    assert metrics.letter_counts("कa") == {"deva": 1, "taml": 0, "beng": 0,
                                           "latin": 1}
    assert metrics.letter_counts("172.50 · ₹15%") == {"deva": 0, "taml": 0,
                                                      "beng": 0, "latin": 0}


def test_pure_devanagari_is_native_script():
    assert metrics.classify("राम ने फल खाया।", "deva") == \
        ("native_script", 100.0, 0.0)


def test_english_is_english():
    # 6 of 11 words are English function words, well over the 25% line.
    result = metrics.classify(
        "The answer is that the price of one item is 172.50 rupees.", "deva")
    assert result == ("english", 0.0, 100.0)


def test_romanised_hindi_is_romanized():
    # No English function words at all, so the Latin answer is Hinglish.
    result = metrics.classify(
        "Maine dukaan se teen vastuyen kharidi aur paise vasool kiye", "deva")
    assert result == ("romanized", 0.0, 100.0)


def test_function_word_line_at_exactly_25_percent():
    result = metrics.classify("rate the dukaan se", "deva")
    assert result == ("english", 0.0, 100.0)


def test_hindi_with_english_technical_terms_is_mixed():
    # 5 Devanagari letters, 9 Latin: 35.71% / 64.29% - both over 20%.
    result = metrics.classify("फल fruit दूध milk", "deva")
    assert result == ("mixed", 35.71, 64.29)


def test_a_realistic_mixed_answer():
    result = metrics.classify(
        "विक्रय मूल्य ₹172.50 है, profit margin 15% पर मिलता है।", "deva")
    assert result.label == "mixed"
    assert result.target_pct >= 20.0 and result.latin_pct >= 20.0


def test_target_exactly_at_the_20_percent_line_counts_as_mixed():
    # 1 Devanagari letter, 4 Latin: 20.0% / 80.0%.
    assert metrics.classify("क a b c d", "deva") == ("mixed", 20.0, 80.0)


def test_native_with_a_little_latin_below_the_line():
    # 10 Devanagari letters, 2 Latin: 83.33% / 16.67%.
    assert metrics.classify("कखगघङ चछजझञ ok", "deva") == \
        ("native_script", 83.33, 16.67)


def test_tamil_and_bengali_answers_classify_the_same_way():
    assert metrics.classify("ஒரு கடையில் புதிய புத்தகங்கள் வந்தன", "taml") == \
        ("native_script", 100.0, 0.0)
    assert metrics.classify("একটি দোকান থেকে চল্লিশটি বই", "beng") == \
        ("native_script", 100.0, 0.0)


def test_a_wrong_indic_script_is_other_script():
    # A Devanagari answer to a Tamil prompt: neither Tamil nor Latin.
    assert metrics.classify("यह उत्तर है", "taml") == ("other_script", 0.0, 0.0)


def test_latin_target_prompts_classify_symmetrically():
    # Hinglish reply to a Latin-script prompt: the target is Latin itself.
    assert metrics.classify(
        "Order cancel ho gaya, refund bhi mention kiya", "latin") == \
        ("native_script", 100.0, 100.0)
    # 9 Latin letters, 6 Devanagari: target 60%, contrast 40%.
    assert metrics.classify("Your order रद्द है", "latin") == \
        ("mixed", 60.0, 60.0)
    # A Devanagari answer to a Latin-script prompt.
    assert metrics.classify("यह उत्तर है", "latin") == ("other_script", 0.0, 0.0)


def test_text_with_no_letters_is_empty():
    assert metrics.classify("", "deva") == ("empty", 0.0, 0.0)
    assert metrics.classify("172.50 · 15%", "deva") == ("empty", 0.0, 0.0)


# -- percentiles ---------------------------------------------------------------


def test_percentile_known_values():
    values = list(range(1, 11))           # 1..10
    assert metrics.percentile(values, 50) == 5.5
    assert metrics.percentile(values, 90) == 9.1
    assert metrics.percentile([10, 20, 30, 40], 75) == 32.5


def test_percentile_sorts_and_handles_degenerate_inputs():
    assert metrics.percentile([30, 10, 40, 20], 50) == 25.0
    assert metrics.percentile([], 50) is None
    assert metrics.percentile([7], 90) == 7.0


# -- per-model aggregation -------------------------------------------------------


def _row(model, cost=None, ttft=None, total=None, error=None):
    return {"model": model, "prompt_id": "p", "cost_inr": cost,
            "ttft_ms": ttft, "total_ms": total, "error_code": error}


def test_model_summary_aggregates_cost_and_latency():
    rows = [
        _row("alpha", cost=0.5, ttft=100, total=200),
        _row("alpha", cost=0.25, ttft=300, total=400),
        _row("alpha", error="429 model_rate_limit_exceeded_error", total=5),
        _row("beta", ttft=50, total=60),
        _row("beta", ttft=-1, total=90),
    ]
    summary = metrics.model_summary(rows)
    assert list(summary) == ["alpha", "beta"]

    alpha = summary["alpha"]
    assert alpha["calls"] == 3
    assert alpha["errors"] == 1
    assert alpha["costed_cells"] == 2
    assert alpha["cost_inr_total"] == 0.75
    assert alpha["cost_inr_mean"] == 0.375
    assert alpha["ttft_p50_ms"] == 200.0
    assert alpha["ttft_p90_ms"] == 280.0
    assert alpha["latency_p50_ms"] == 300.0

    beta = summary["beta"]
    assert beta["calls"] == 2
    assert beta["errors"] == 0
    assert beta["costed_cells"] == 0
    assert beta["cost_inr_total"] == 0.0
    assert beta["cost_inr_mean"] is None          # no usage: never an estimate
    assert beta["ttft_p50_ms"] == 50.0
    assert beta["latency_p50_ms"] == 60.0         # the ttft=-1 row never enters
