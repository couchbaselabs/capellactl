PY ?= .venv/bin/python
RELEASE ?= docs/release-1.0.0

.PHONY: lint typecheck test test-integration test-integration-fake janitor ac-coverage index index-check coverage coverage-check notices notices-check docs docs-check dist build image binary downloads downloads-check rulesets rulesets-check check

lint:
	$(PY) -m ruff check capellactl tests scripts

typecheck:
	$(PY) -m mypy capellactl

test:
	PYTHONWARNDEFAULTENCODING=1 $(PY) -m pytest

test-integration:  # against the Capella sandbox: needs CAPELLA_SANDBOX_API_KEY and CAPELLA_SANDBOX_ORG_ID (CAP-032)
	CAPELLACTL_IT_TARGET=sandbox $(PY) -m pytest -m integration -rA

test-integration-fake:  # the same suite against the in-memory fake: checks the suite itself, offline
	CAPELLACTL_IT_TARGET=fake PYTHONWARNDEFAULTENCODING=1 $(PY) -m pytest -m integration -p no:cacheprovider

janitor:  # delete capellactl-ci-* sandbox projects older than 24 hours (CAP-032 AC3)
	$(PY) scripts/ci-janitor.py

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

binary:          # standalone executable for this machine in dist/binary/, then its smoke tests (CAP-045)
	$(PY) scripts/build-binary.py

downloads:       # downloads/ and the README Download section from downloads/manifest.json (CAP-045)
	$(PY) scripts/update-downloads.py

downloads-check:
	$(PY) scripts/update-downloads.py --check

rulesets:        # create or update the main and v* tag rulesets on GitHub; needs repository admin (CAP-050)
	$(PY) scripts/github-rulesets.py apply

rulesets-check:  # fail when the live rulesets or repository settings differ from .github/rulesets (CAP-050)
	$(PY) scripts/github-rulesets.py --check

dist:            # source archive, wheel and SHA256SUMS in dist/ (CAP-043)
	$(PY) scripts/build-dist.py

build: dist

image: dist      # the image installs the wheel built by `make dist`
	docker build -t capellactl:$$($(PY) scripts/version.py | tr '+' '-') .

check: lint typecheck test test-integration-fake ac-coverage index-check coverage-check notices-check docs-check downloads-check
