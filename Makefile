# Bhasha Bench. Python 3.12; see requirements.txt for the three dependencies.
PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: test run smoke smoke-check score build

# No network, no API key: the suite runs against stub clients.
test:
	$(PYTHON) -m pytest tests -v

# One full run: every prompt to every model, 72 calls at concurrency 3.
# Prints the projected cost ceiling and asks before spending.
# Needs SARVAM_API_KEY in the environment.
run:
	$(PYTHON) -m bench.cli run --models all --prompts all

# Live smoke test (needs SARVAM_API_KEY): one prompt to the registry's
# default model, one call, one row. Run it yourself; the harness never does.
smoke:
	$(PYTHON) -m bench.cli run --prompts hi-1

# Verify the newest row against the smoke criteria; prints it verbatim.
smoke-check:
	$(PYTHON) -m bench.smoke

# Score the newest run's answers by hand, 0-2. The score comes only from
# what you type; nothing is invented, and q stops for later resuming.
score:
	$(PYTHON) -m bench.cli score

# Publish a finished run to site/data/leaderboard.json for the static page.
# Defaults to the newest run; --run picks another. Score first: an unscored
# run publishes with quality n/a, never with an invented number.
build:
	$(PYTHON) -m bench.cli build
