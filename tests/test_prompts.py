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


def test_prompt_set_hash_is_stable():
    _, first = prompt_set.load_prompts()
    _, second = prompt_set.load_prompts()
    assert first == second
    assert len(first) == 64


def test_the_hash_covers_the_experiment_not_the_checks(tmp_path):
    """Machine-check expectation keys are metadata: adding one must not
    invalidate runs recorded before it existed; changing prompt text must."""
    import hashlib

    raw = prompt_set.DEFAULT_PATH.read_bytes()
    before = prompt_set.experiment_hash(raw)

    with_check_key = raw + b"    forbid_latin: true\n"
    assert prompt_set.experiment_hash(with_check_key) == before

    with_text_change = raw.replace(b"hi-1", b"hi-X")
    assert prompt_set.experiment_hash(with_text_change) != before

    # a file that never carried check keys hashes to its own raw sha256
    keys = [k.encode() for k in prompt_set.MACHINE_CHECK_KEYS]
    stripped_bytes = b"".join(
        line for line in raw.splitlines(keepends=True)
        if not any(line.strip().startswith(key + b":") for key in keys))
    stripped = tmp_path / "stripped.yaml"
    stripped.write_bytes(stripped_bytes)
    assert prompt_set.experiment_hash(stripped_bytes) == \
        hashlib.sha256(stripped_bytes).hexdigest()
