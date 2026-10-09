PY ?= .venv/bin/python
RELEASE ?= docs/release-1.0.0

.PHONY: lint typecheck test test-integration ac-coverage index index-check coverage coverage-check notices notices-check docs docs-check dist build image check

lint:
	$(PY) -m ruff check capellactl tests scripts

typecheck:
	$(PY) -m mypy capellactl

test:
	$(PY) -m pytest

test-integration:
	$(PY) -m pytest -m integration

ac-coverage:
	$(PY) scripts/check-ac-coverage.py --docs $(RELEASE)

index:
	$(PY) scripts/update-story-index.py $(RELEASE)

index-check:
	$(PY) scripts/update-story-index.py --check $(RELEASE)

coverage:
	$(PY) scripts/update-api-coverage.py

coverage-check:
	$(PY) scripts/update-api-coverage.py --check

notices:
	$(PY) scripts/third-party-notices.py

notices-check:
	$(PY) scripts/third-party-notices.py --check

docs:            # docs/reference.md from the config schema (CAP-033)
	$(PY) scripts/update-reference.py

docs-check:
	$(PY) scripts/update-reference.py --check

dist:            # source archive, wheel and SHA256SUMS in dist/ (CAP-043)
	$(PY) scripts/build-dist.py

build: dist

image: dist      # the image installs the wheel built by `make dist`
	docker build -t capellactl:$$($(PY) scripts/version.py | tr '+' '-') .

check: lint typecheck test ac-coverage index-check coverage-check notices-check docs-check
