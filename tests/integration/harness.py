"""CAP-032: what every integration test uses, against the real sandbox or the in-memory fake.

CAPELLACTL_IT_TARGET=sandbox   real Capella, with CAPELLA_SANDBOX_API_KEY and CAPELLA_SANDBOX_ORG_ID (the nightly job)
CAPELLACTL_IT_TARGET=fake      the fake of CAP-004 with a fake clock: proves the suite's own logic on every push
unset                          sandbox when both variables are set; otherwise the integration tests are skipped

The plain CAPELLA_API_KEY/CAPELLA_ORG_ID are cleared by tests/conftest.py, so a developer's own key never reaches
the suite by accident. Each run creates its own projects, named capellactl-ci-<run id>-<purpose>, and deletes them
in `Target.cleanup` whatever happens; scripts/ci-janitor.py removes what a killed run left behind.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import time
import traceback
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "capellactl-ci-"
FAKE_KEY = "fake-it-api-key-0123456789"
FAKE_ORG = "org-it"
# The request lines `--log-level debug` prints (capellactl/api/client.py): "DEBUG: POST /v4/... 202 35ms"
REQUEST = re.compile(r"^DEBUG: (GET|POST|PUT|PATCH|DELETE) (/v4/\S+) (\d{3})\b", re.M)
WRITES = {"POST", "PUT", "PATCH", "DELETE"}


def load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


janitor = load_script("ci-janitor")


def target_kind() -> str | None:
    kind = os.environ.get("CAPELLACTL_IT_TARGET", "").strip().lower()
    if kind in ("fake", "sandbox"):
        return kind
    if os.environ.get("CAPELLA_SANDBOX_API_KEY") and os.environ.get("CAPELLA_SANDBOX_ORG_ID"):
        return "sandbox"
    return None


def run_id() -> str:
    """Unique per CI run and attempt, so a re-run never trips over the projects of the run before."""
    gh = os.environ.get("GITHUB_RUN_ID")
    return f"{gh}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}" if gh else f"local{int(time.time())}"


@dataclass
class Result:
    exit_code: int
    output: str

    @property
    def requests(self) -> list[tuple[str, str, int]]:
        return [(m, p, int(s)) for m, p, s in REQUEST.findall(self.output)]

    @property
    def writes(self) -> list[tuple[str, str, int]]:
        return [r for r in self.requests if r[0] in WRITES]


@dataclass
class Target:
    kind: str
    api_key: str
    org_id: str
    log_path: Path
    fake: Any = None
    run: str = field(default_factory=run_id)
    report: list[dict[str, Any]] = field(default_factory=list)
    timeout: timedelta = timedelta(minutes=60)

    @property
    def env(self) -> dict[str, str]:
        return {"CAPELLA_API_KEY": self.api_key, "CAPELLA_ORG_ID": self.org_id}

    def project_name(self, purpose: str) -> str:
        return f"{PREFIX}{self.run}-{purpose}"

    def cli(self, *args: str, cfg: Path | None = None, approve: bool = True,
            extra_env: dict[str, str] | None = None, debug: bool = True) -> Result:
        """Run capellactl with debug logging; the output, request lines included, is appended to the run log.
        debug=False keeps the output parseable (-o json); Result.writes is then empty."""
        from capellactl.cli.main import cli

        argv = [*(["--log-level", "debug"] if debug else []), *(["-c", str(cfg)] if cfg else []),
                *(["--auto-approve"] if approve else []), *args]
        r = CliRunner().invoke(cli, argv, env={**self.env, **(extra_env or {})}, prog_name="capellactl")
        output = r.output
        if r.exception is not None and not isinstance(r.exception, SystemExit):
            output += "".join(traceback.format_exception(r.exception))
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"$ capellactl {' '.join(argv)}\n{output}[exit {r.exit_code}]\n\n")
        return Result(r.exit_code, output)

    def client(self) -> Any:
        from capellactl.api.client import CapellaClient
        from capellactl.engine.clock import get_clock

        return CapellaClient(self.api_key, self.org_id, clock=get_clock())

    @contextmanager
    def cleanup(self, project: str) -> Iterator[dict[str, Any]]:
        """Delete every project called `project`, and all it holds, when the block ends, passed or failed (AC3).

        The report entry records both outcomes. A failed teardown fails a block that had passed; after a failure
        the original error is the one raised, and the teardown result is still in the report."""
        entry: dict[str, Any] = {"project": project, "failure": None, "teardown": None}
        self.report.append(entry)
        try:
            yield entry
        except BaseException as exc:
            entry["failure"] = (f"{type(exc).__name__}: {exc}".splitlines() or ["?"])[0][:300]
            raise
        finally:
            try:
                steps = janitor.delete_projects_named(self.client(), project, self.timeout)
                entry["teardown"] = "ok: " + ("; ".join(steps) if steps else "nothing left to delete")
            except Exception as exc:  # noqa: BLE001 - recorded, then raised unless a failure is already in flight
                entry["teardown"] = f"FAILED: {type(exc).__name__}: {exc}"[:300]
                if entry["failure"] is None:
                    raise

    def write_report(self, path: Path) -> None:
        path.write_text(json.dumps({"target": self.kind, "run": self.run, "projects": self.report}, indent=2) + "\n",
                        encoding="utf-8")

    def summary(self) -> list[str]:
        lines = [f"integration target: {self.kind}, run {self.run}"]
        for e in self.report:
            lines.append(f"  {e['project']}: {'FAILED: ' + e['failure'] if e['failure'] else 'passed'}; "
                         f"teardown {e['teardown']}")
        return lines


@dataclass
class Shared:
    """The project every per-feature test works in: one 3-node AWS cluster, deployed once per run."""
    cfg: Path
    project: str
    cluster: str
    bucket: str

    def import_into(self, target: Target, cfg: Path, cluster: bool = False) -> None:
        args = ["import", "--project", self.project, *(["--cluster", self.cluster] if cluster else []),
                "--file", str(cfg)]
        r = target.cli(*args, approve=False)
        assert r.exit_code == 0, r.output


def single_node(project: str, cluster: str, cidr: str, extra: str = "") -> str:
    """capella.yaml for one single-node AWS cluster: the cheapest layout (AC1)."""
    return f"""\
apiVersion: capellactl/v1
organizationId: ${{CAPELLA_ORG_ID}}
project:
  name: {project}
  description: capellactl nightly integration suite (CAP-032)
clusters:
  - name: {cluster}
    description: capellactl nightly
    configurationType: singleNode
    cloudProvider: {{ type: aws, region: us-east-1, cidr: {cidr} }}
    availability: {{ type: single }}
    support: {{ plan: basic }}
    serviceGroups:
      - node:
          compute: {{ cpu: 4, ram: 16 }}
          disk: {{ type: gp3, storage: 50, iops: 3000 }}
        numOfNodes: 1
        services: [data, index, query]
{extra}"""


def multi_node(project: str, cluster: str, bucket: str, client_cidr: str | None) -> str:
    """capella.yaml for the shared project: the smallest 3-node AWS layout the scaling tests need (AC2)."""
    cidrs = (f"    allowedCidrs:\n      - cidr: {client_cidr}\n        comment: this CI runner (CAP-032)\n"
             if client_cidr else "")
    return f"""\
apiVersion: capellactl/v1
organizationId: ${{CAPELLA_ORG_ID}}
project:
  name: {project}
  description: capellactl nightly integration suite (CAP-032)
clusters:
  - name: {cluster}
    description: capellactl nightly, shared by the per-feature tests
    configurationType: multiNode
    cloudProvider: {{ type: aws, region: us-east-1, cidr: 10.20.0.0/24 }}
    availability: {{ type: multi }}
    support: {{ plan: developer pro, timezone: PT }}
    serviceGroups:
      - node:
          compute: {{ cpu: 4, ram: 16 }}
          disk: {{ type: gp3, storage: 50, iops: 3000 }}
        numOfNodes: 3
        services: [data, index, query]
{cidrs}    buckets:
      - name: {bucket}
        memoryAllocationInMb: 256
"""
