# Statcast Roto -- common tasks
# Usage: make <target>

PYTHON ?= python3
export PYTHONPATH := src

.PHONY: help install demo run run-pitch raw enrich bat site test clean

help:
	@echo "Targets:"
	@echo "  install    Install the package (editable) + dev/live extras"
	@echo "  demo       Run the full demo on bundled real-2020 data -> outputs/"
	@echo "  run        Score the bundled league (CLI, precomputed source)"
	@echo "  run-pitch  Aggregate the raw pitch SAMPLE from scratch, then score"
	@echo "  raw        Download the raw Statcast seasons (~1.6 GB, needs pybaseball)"
	@echo "  enrich     Fetch official MLB season lines and merge them (needs internet)"
	@echo "  bat        Fetch the Swing Lab's Savant bat-tracking leaderboards (optional)"
	@echo "  site       Rebuild the five-season page -> site/never_lucky_five_seasons.html"
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

# Convert a raw pitch CSV into precomputed files. Override PITCHES and TAG:
#   make precompute PITCHES=data/raw_sample/Statcast_2021.csv TAG=2021
PITCHES ?= data/raw_sample/statcast_2020_sample.csv
TAG ?= sample
precompute:
	$(PYTHON) scripts/build_precomputed.py --pitches $(PITCHES) --tag $(TAG)

raw:
	$(PYTHON) scripts/fetch_raw_statcast.py

enrich:
	$(PYTHON) scripts/enrich_precomputed.py --tags 2017 2018 2019 2020 2021 --fetch

bat:
	$(PYTHON) scripts/fetch_bat_tracking.py

site: enrich
	$(PYTHON) site/build_payload.py
	$(PYTHON) site/build_site.py

test:
	$(PYTHON) -m pytest

clean:
	rm -rf outputs outputs_pitch .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
