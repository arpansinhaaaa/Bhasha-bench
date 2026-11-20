# Bhasha Bench. Python 3.12; see requirements.txt for the three dependencies.
PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: test run

# No network, no API key: the suite runs against fake clients.
test:
	$(PYTHON) -m pytest tests -v

# One full run: every prompt to every model, 72 calls at concurrency 3.
# Needs SARVAM_API_KEY in the environment.
run:
	$(PYTHON) -m bench.cli run --models all --prompts all
