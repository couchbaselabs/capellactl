PY ?= .venv/bin/python
RELEASE ?= docs/release-1.0.0

.PHONY: lint typecheck test test-integration ac-coverage index index-check coverage coverage-check notices notices-check build image check

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

build:
	$(PY) -m pip wheel --no-deps -w dist .

image:
	docker build -t capellactl:$$($(PY) -c 'import capellactl;print(capellactl.__version__)') .

check: lint typecheck test ac-coverage index-check coverage-check notices-check
