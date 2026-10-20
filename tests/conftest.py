"""Shared fixtures. See docs/release-1.0.0/00-architecture.md section 12."""

from __future__ import annotations

import os
import subprocess
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import keyring
import pytest
import responses
from click.testing import CliRunner, Result
from keyring.backend import KeyringBackend

from capellactl.cli import console
from capellactl.engine import clock as clock_mod
from capellactl.engine.clock import FakeClock, RealClock
from capellactl.output.redact import redactor
from tests.fakes.capella import FakeCapella

API_KEY = "test-api-key-0123456789"
ORG = "org-1"

MINIMAL = """\
apiVersion: capellactl/v1
organizationId: ${CAPELLA_ORG_ID}
project:
  name: nova-dev
  description: Nova development environment
clusters:
  - name: nova-dev-01
    description: Nova development cluster
    cloudProvider: { type: aws, region: us-east-1, cidr: 10.10.0.0/24 }
    availability: { type: multi }
    support: { plan: developer pro, timezone: PT }
    serviceGroups:
      - node:
          compute: { cpu: 4, ram: 16 }
          disk: { type: gp3, storage: 50, iops: 3000 }
        numOfNodes: 3
        services: [data, index, query]
"""

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "release-1.0.0" / "examples" / "capella.yaml"


class MemoryKeyring(KeyringBackend):
    priority = 1  # type: ignore[assignment]

    def __init__(self) -> None:
        super().__init__()
        self.store: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.store.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.store[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        from keyring.errors import PasswordDeleteError

        if (service, username) not in self.store:
            raise PasswordDeleteError("not found")
        del self.store[(service, username)]


class ChildEnv(dict[str, str]):
    """A minimal child-process environment that still starts on Windows: built by child_env()."""


def child_env(**env: str) -> ChildEnv:
    # Windows' interpreter cannot start without SYSTEMROOT (empty stdout, no traceback); USERPROFILE is its HOME
    keep = {k: os.environ[k] for k in ("SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
    if "HOME" in env:
        keep["USERPROFILE"] = env["HOME"]
    return ChildEnv(keep | env)


def _guard_child_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail on every OS, not only on the Windows runners, when a child gets a hand-built env."""
    init = subprocess.Popen.__init__

    def checked(self: subprocess.Popen[Any], *args: Any, **kwargs: Any) -> None:
        env = kwargs.get("env")
        if env is not None and not isinstance(env, ChildEnv) and not set(os.environ) <= set(env):
            raise AssertionError("pass env={**os.environ, ...} or tests.conftest.child_env(...) to a subprocess: "
                                 "a hand-built env cannot start Python on Windows")
        init(self, *args, **kwargs)

    monkeypatch.setattr(subprocess.Popen, "__init__", checked)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "story(id, ac): links a test to a story acceptance criterion")
    config.addinivalue_line("markers", "integration: runs against a real Capella sandbox organization")


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[MemoryKeyring]:
    # CI is set by GitHub Actions and most other CI services; it changes refusal messages (CAP-042 AC3).
    for var in ("CAPELLA_API_KEY", "CAPELLA_ORG_ID", "CAPELLA_API_BASE_URL", "CAPELLACTL_CONFIG",
                "CAPELLACTL_PROFILE", "CAPELLACTL_QUIET", "CAPELLACTL_AUTO_APPROVE", "BEARER_TOKEN", "ORG_ID",
                "API_BASE_URL", "CI"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CAPELLACTL_HOME", str(tmp_path / ".capellactl-home"))
    monkeypatch.chdir(tmp_path)
    _guard_child_env(monkeypatch)
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    redactor.clear()
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    yield kr
    redactor.clear()


@pytest.fixture
def keychain(_isolate: MemoryKeyring) -> MemoryKeyring:
    return _isolate


@pytest.fixture
def clock() -> Iterator[FakeClock]:
    c = FakeClock()
    clock_mod.set_clock(c)
    yield c
    clock_mod.set_clock(RealClock())


@pytest.fixture
def fake(clock: FakeClock) -> Iterator[FakeCapella]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        f = FakeCapella(org_id=ORG, clock=clock)
        f.install(rsps)
        yield f


@pytest.fixture
def write_config(tmp_path: Path) -> Any:
    def _write(text: str = MINIMAL, name: str = "capella.yaml") -> Path:
        p = tmp_path / name
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        return p

    return _write


@pytest.fixture
def env() -> dict[str, str]:
    return {"CAPELLA_API_KEY": API_KEY, "CAPELLA_ORG_ID": ORG}


@pytest.fixture
def run(env: dict[str, str]) -> Any:
    from capellactl.cli.main import cli

    def _run(*args: str, input: str | None = None, extra_env: dict[str, str] | None = None,
             no_env: bool = False) -> Result:
        e = {} if no_env else dict(env)
        e.update(extra_env or {})
        return CliRunner().invoke(cli, list(args), input=input, env=e, catch_exceptions=False,
                                  prog_name="capellactl")

    return _run


def assert_no_secret(text: str, *values: str) -> None:
    for v in values:
        assert v not in text, "secret value leaked into output"


def seed_healthy(fake: FakeCapella, nodes: int = 3, **cluster_fields: Any) -> tuple[str, str]:
    pid = fake.seed_project("nova-dev", description="Nova development environment")
    groups = [{"node": {"compute": {"cpu": 4, "ram": 16}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
               "numOfNodes": nodes, "services": ["data", "index", "query"]}]
    fields = {"description": "Nova development cluster", "serviceGroups": groups, **cluster_fields}
    cid = fake.seed_cluster(pid, "nova-dev-01", **fields)
    return pid, cid


@pytest.fixture
def stub_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use the test-only reconcilers for buckets, scopes, collections, CIDRs and credentials."""
    from capellactl.cli import env as env_mod
    from tests.fakes.stub_reconcilers import stub_tree as factory

    monkeypatch.setattr(env_mod, "TREE_FACTORY", factory)


def file_projects(path: Path) -> list[dict[str, Any]]:
    """Projects of a capella.yaml in either form, each with its clusters."""
    import yaml

    from capellactl.importer import to_projects_form

    return list(to_projects_form(yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("projects") or [])


def file_clusters(path: Path, project: str | None = None) -> list[dict[str, Any]]:
    return [c for p in file_projects(path) if project is None or p.get("name") == project
            for c in p.get("clusters") or []]
