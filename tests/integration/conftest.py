"""CAP-032: fixtures of the integration suite (target selection and teardown: tests/integration/harness.py)."""
from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.harness import FAKE_KEY, FAKE_ORG, Shared, Target, multi_node, target_kind

_TARGETS: list[Target] = []


@pytest.fixture(scope="session")
def it(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Target]:
    kind = target_kind()
    if kind is None:
        pytest.skip("needs CAPELLA_SANDBOX_API_KEY and CAPELLA_SANDBOX_ORG_ID, or CAPELLACTL_IT_TARGET=fake")
    log = Path(os.environ.get("CAPELLACTL_IT_LOG") or tmp_path_factory.mktemp("it") / "integration.log")
    log.write_text("", encoding="utf-8")
    report = os.environ.get("CAPELLACTL_IT_REPORT")
    if kind == "fake":
        import responses

        from capellactl.engine import clock as clock_mod
        from capellactl.engine.clock import FakeClock, RealClock
        from tests.fakes.capella import FakeCapella

        clock = FakeClock()
        clock_mod.set_clock(clock)
        try:
            with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
                fake = FakeCapella(org_id=FAKE_ORG, clock=clock)
                fake.install(rsps)
                t = Target("fake", FAKE_KEY, FAKE_ORG, log, fake=fake)
                _TARGETS.append(t)
                yield t
        finally:
            clock_mod.set_clock(RealClock())
    else:
        t = Target("sandbox", os.environ["CAPELLA_SANDBOX_API_KEY"], os.environ["CAPELLA_SANDBOX_ORG_ID"], log)
        _TARGETS.append(t)
        yield t
    if report:
        t.write_report(Path(report))


@pytest.fixture(scope="session")
def shared(it: Target, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Shared]:
    """One project with a 3-node cluster and a bucket for the per-feature tests, deleted at the end of the run.

    CAPELLA_SANDBOX_CLIENT_CIDR (the runner's public address, set by the nightly job) is allowed on the cluster
    so the SDK connection test can reach it."""
    d = tmp_path_factory.mktemp("shared")
    s = Shared(d / "capella.yaml", it.project_name("shared"), "ci-shared-01", "it-data")
    s.cfg.write_text(multi_node(s.project, s.cluster, s.bucket, os.environ.get("CAPELLA_SANDBOX_CLIENT_CIDR")),
                     encoding="utf-8")
    with it.cleanup(s.project):
        r = it.cli("apply", cfg=s.cfg)
        assert r.exit_code == 0, r.output
        yield s


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    """Show every project's test result next to its teardown result (AC3)."""
    for t in _TARGETS:
        terminalreporter.section("capellactl integration teardown (CAP-032)")
        for line in t.summary():
            terminalreporter.write_line(line)
