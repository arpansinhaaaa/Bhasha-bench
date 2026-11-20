# Bhasha Bench. Python 3.12; see requirements.txt for the three dependencies.
PYTHON := $(shell [ -x .venv/bin/python ] && echo .venv/bin/python || echo python3)

.PHONY: test run smoke smoke-check

# No network, no API key: the suite runs against fake clients.
test:
	$(PYTHON) -m pytest tests -v

# One full run: every prompt to every model, 72 calls at concurrency 3.
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
