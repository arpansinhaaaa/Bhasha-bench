"""Load the fixed prompt set and its content hash.

prompts/prompts.yaml (handoff Block B) is the experiment itself: twelve
prompts, fixed and versioned. This module only reads it; nothing here may
rewrite, reorder, translate or "fix" its content. The prompt-set hash is
sha256 over the raw file bytes, so any edit to the set changes it and every
run records which version of the experiment produced its rows.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "prompts.yaml"


def load_prompts(path: str | Path | None = None) -> tuple[list[dict], str]:
    """Return (prompts, prompt_set_hash).

    prompts is the list of prompt dicts in file order; the hash is sha256 hex
    over the raw file bytes.
    """
    file = Path(path) if path is not None else DEFAULT_PATH
    raw = file.read_bytes()
    data = yaml.safe_load(raw.decode("utf-8"))
    prompts = data["prompts"]
    ids = [prompt["id"] for prompt in prompts]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate prompt ids in {file}")
    return prompts, hashlib.sha256(raw).hexdigest()
