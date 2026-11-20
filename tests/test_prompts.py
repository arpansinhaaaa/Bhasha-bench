"""The prompt set is fixed content (handoff Block B). Pin its shape, never its text."""

from bench import prompts as prompt_set

EXPECTED_IDS = [
    "hi-1", "hi-2", "hi-3",
    "ta-1", "ta-2", "ta-3",
    "bn-1", "bn-2", "bn-3",
    "he-1", "he-2", "he-3",
]
SCRIPTS = {"deva", "taml", "beng", "latin"}
CATEGORIES = {"reasoning", "summarise", "instruction", "script-switch"}


def test_twelve_prompts_with_expected_ids_in_order():
    loaded, _ = prompt_set.load_prompts()
    assert [p["id"] for p in loaded] == EXPECTED_IDS


def test_every_prompt_is_complete():
    loaded, _ = prompt_set.load_prompts()
    for prompt in loaded:
        assert prompt["text"].strip()
        assert prompt["rubric"].strip()
        assert prompt["language"]
        assert prompt["script"] in SCRIPTS
        assert prompt["category"] in CATEGORIES


def test_both_cross_script_probes_are_present():
    loaded, _ = prompt_set.load_prompts()
    by_id = {p["id"]: p for p in loaded}
    # A Devanagari question demanding a Roman-script Hinglish answer...
    assert by_id["hi-3"]["script"] == "latin"
    # ...and a Hinglish question demanding a Devanagari answer.
    assert by_id["he-1"]["script"] == "deva"


def test_prompt_set_hash_is_over_the_raw_file():
    _, first = prompt_set.load_prompts()
    _, second = prompt_set.load_prompts()
    assert first == second
    assert len(first) == 64
