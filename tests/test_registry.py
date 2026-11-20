"""Registry integrity and cost arithmetic. No network, no API key.

The registry is the only place a model id or a price lives, so these tests
assert its shape and its arithmetic rather than restating its facts. The one
deliberate exception is the PRD's own prescribed hand-check (section 12):
1000 prompt / 500 completion tokens on `glm5.3` must cost exactly Rs 0.321 -
an independent number, so a wrong price in the registry fails here.
"""

import pytest

from bench import registry

ALL_IDS = list(registry.MODELS)


def test_registry_has_six_models():
    assert len(ALL_IDS) == 6


@pytest.mark.parametrize("model_id", ALL_IDS)
def test_entries_are_complete_and_positive(model_id):
    entry = registry.MODELS[model_id]
    assert entry["context"] > 0
    assert entry["input_modalities"]
    assert entry["reasoning_default"] in (None, "none", "low", "medium", "high", "max")
    assert isinstance(entry["introductory"], bool)
    assert entry["in"] > 0
    assert entry["out"] > 0
    assert 0 < entry["cached"] <= entry["in"]


def test_prices_are_dated_and_sourced():
    assert registry.PRICES_READ_ON == "2026-11-20"
    assert registry.PRICING_URL.startswith("https://")


def test_prd_cost_handcheck():
    # PRD section 12: glm5.3, 1000 prompt / 500 completion == Rs 0.321.
    assert registry.cost_inr("glm5.3", 1000, 500) == 0.321


@pytest.mark.parametrize("model_id", ALL_IDS)
def test_a_million_tokens_cost_the_listed_rate(model_id):
    entry = registry.MODELS[model_id]
    assert registry.cost_inr(model_id, 1_000_000, 0) == entry["in"]
    assert registry.cost_inr(model_id, 0, 1_000_000) == entry["out"]
    assert registry.cost_inr(model_id, 0, 0, cached_tokens=1_000_000) == entry["cached"]


def test_cost_splits_billable_and_cached_input():
    entry = registry.MODELS[ALL_IDS[0]]
    expected = round(600 / 1e6 * entry["in"]
                     + 400 / 1e6 * entry["cached"]
                     + 500 / 1e6 * entry["out"], 6)
    assert registry.cost_inr(ALL_IDS[0], 1000, 500, cached_tokens=400) == expected


def test_cached_over_prompt_never_goes_negative():
    entry = registry.MODELS[ALL_IDS[0]]
    expected = round(200 / 1e6 * entry["cached"] + 50 / 1e6 * entry["out"], 6)
    assert registry.cost_inr(ALL_IDS[0], 100, 50, cached_tokens=200) == expected


def test_unknown_model_is_rejected():
    with pytest.raises(KeyError):
        registry.cost_inr("no-such-model", 1, 1)
