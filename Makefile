# Statcast Roto -- common tasks
# Usage: make <target>

PYTHON ?= python3
export PYTHONPATH := src

.PHONY: help install demo run run-pitch test clean

help:
	@echo "Targets:"
	@echo "  install    Install the package (editable) + dev/live extras"
	@echo "  demo       Run the full demo on bundled real-2020 data -> outputs/"
	@echo "  run        Score the bundled league (CLI, precomputed source)"
	@echo "  run-pitch  Aggregate the raw pitch SAMPLE from scratch, then score"
	@echo "  test       Run the test suite"
	@echo "  clean      Remove generated outputs and caches"

install:
	$(PYTHON) -m pip install -e ".[dev,live]"

demo:
	$(PYTHON) examples/run_demo.py

run:
	$(PYTHON) -m statcast_roto.cli --source precomputed --outputs outputs

run-pitch:
	$(PYTHON) -m statcast_roto.cli --source pitch \
		--pitches data/raw_sample/statcast_2020_sample.csv \
		--rosters data/precomputed/rosters_2020.csv \
		--outputs outputs_pitch

test:
	$(PYTHON) -m pytest

clean:
	rm -rf outputs outputs_pitch .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
