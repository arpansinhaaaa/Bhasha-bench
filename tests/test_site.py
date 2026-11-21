"""site/index.html - the page as a file, under the rules it must live by.

The page is a deliverable, not decoration: it renders the committed
leaderboard.json, so its constraints are testable without a browser - no
external reference, no model id typed into static HTML (model names arrive
only inside the JSON, from the registry via the builder), the honest states
present, and API answer text rendered as text, never as markup.
"""

import re
from pathlib import Path

from bench import registry

SITE = Path(__file__).resolve().parents[1] / "site" / "index.html"


def _html():
    assert SITE.exists(), f"{SITE} is missing: the page ships with the repo"
    return SITE.read_text(encoding="utf-8")


def test_the_page_reads_only_its_own_committed_json():
    html = _html()
    assert "<!doctype html>" in html.lower()
    assert 'const DATA_URL = "data/leaderboard.json"' in html
    # Nothing else loads: no CDN, no framework, no webfont, no image.
    assert not re.search(r'(src|href)="https?://', html)
    assert "<script src=" not in html
    assert "@import" not in html
    assert "fonts.googleapis" not in html


def test_no_model_id_is_ever_typed_into_the_page():
    html = _html()
    for model in registry.MODELS:
        assert model not in html, f"{model} hardcodes a registry fact in the page"


def test_the_honesty_states_are_all_present():
    html = _html()
    for needle in [
        "n=1 per cell; directional, not definitive",  # P11: in the header, not a footnote
        "Instruction and answer checks are automated and deterministic",
        "no model scored another model",             # the checks' honesty line
        "No runs yet",                               # the empty state (PRD section 9)
        "hit token budget",        # finish_reason "length" is a budget note, not an error
        "introductory",            # dated prices, labelled where they are shown
        "Instructions", "Correct",  # the two deterministic-check columns
        "not checkable",           # the tooltip on an unchecked answer's em dash
        "not followed", "incorrect",  # a failed check says so, plainly
        "no row in this run",      # a missing cell is n/a, never hidden or averaged
        "Script fidelity", "TTFT p50",  # the sortable columns
    ]:
        assert needle in html, f"the page lost its '{needle}' state"


def test_api_text_is_rendered_as_text_never_as_markup():
    html = _html()
    assert "innerHTML" not in html
    assert "document.write" not in html
