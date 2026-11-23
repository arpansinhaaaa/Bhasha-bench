"""Load the fixed prompt set and its content hash.

prompts/prompts.yaml is the experiment itself: twelve
prompts, fixed and versioned. This module only reads it; nothing here may
rewrite, reorder, translate or "fix" its content.

The prompt-set hash pins the EXPERIMENT - the ids, texts and rubrics that
produced a run's rows - so the leaderboard builder can refuse a run whose
drill-down would show prompt text that did not produce its answers.

Machine-checkable expectation keys (expected_value, exact_sentences,
exactly_three_points, forbid_deva, forbid_latin, exact_lines,
must_mention_any) are evaluator metadata, not experiment content: they were
added after the runs and do not change what was sent or asked. The hash is
therefore sha256 over the raw file bytes with every line that declares one
of those keys removed - which is byte-identical to the pre-expectations
file, so runs recorded before the expectations were added stay valid, while
any edit to an id, text, rubric, script or category still changes the hash
and refuses the build. Adding a new machine-check key means extending
MACHINE_CHECK_KEYS.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "prompts.yaml"

# Expectation keys the experiment hash deliberately ignores (see module doc).
MACHINE_CHECK_KEYS = (
    "expected_value",
    "exact_sentences",
    "exactly_three_points",
    "forbid_deva",
    "forbid_latin",
    "exact_lines",
    "must_mention_any",
)


def experiment_hash(raw: bytes) -> str:
    """sha256 over the raw file with machine-check lines removed.

    Removal is line-granular and byte-exact: a line whose stripped content
    starts with `<key>:` for a listed key is dropped, everything else is
    kept verbatim. A file that never had such lines hashes to its own raw
    sha256; a file that only gained them hashes to the old file's sha256.
    """
    kept = []
    for line in raw.decode("utf-8").splitlines(keepends=True):
        stripped = line.strip()
        if any(stripped.startswith(key + ":") for key in MACHINE_CHECK_KEYS):
            continue
        kept.append(line)
    return hashlib.sha256("".join(kept).encode("utf-8")).hexdigest()


def load_prompts(path: str | Path | None = None) -> tuple[list[dict], str]:
    """Return (prompts, prompt_set_hash).

    prompts is the list of prompt dicts in file order; the hash is sha256 hex
    over the experiment content (see experiment_hash).
    """
    file = Path(path) if path is not None else DEFAULT_PATH
    raw = file.read_bytes()
    data = yaml.safe_load(raw.decode("utf-8"))
    prompts = data["prompts"]
    ids = [prompt["id"] for prompt in prompts]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate prompt ids in {file}")
    return prompts, experiment_hash(raw)


def load_rubric(path: str | Path | None = None) -> str:
    """The top-level 0-2 rubric, shown once before a scoring walk."""
    file = Path(path) if path is not None else DEFAULT_PATH
    data = yaml.safe_load(file.read_bytes().decode("utf-8"))
    return data["rubric"].strip()
