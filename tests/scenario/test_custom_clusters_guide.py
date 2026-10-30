"""CAP-051 AC8: every command in docs/custom-clusters.md runs, in order, against the fake Capella."""
from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "custom-clusters.md"
# Exit codes other than 0 that the guide shows on purpose.
EXPECTED = {"cluster group remove prod-01 search": {4}, "sync --dry-run": {0, 2}}


def _commands() -> list[str]:
    out = []
    for block in re.findall(r"```bash\n(.*?)```", GUIDE.read_text(encoding="utf-8"), flags=re.S):
        for line in block.replace("\\\n", " ").splitlines():
            line = re.sub(r"\s+#.*$", "", line.strip())
            if line.startswith("capellactl "):
                out.append(line.removeprefix("capellactl "))
    return out


def _run_guide(fake, run) -> dict:
    """Every command of the guide, in order, against the fake; the clusters it leaves, by name."""
    fake.seed_project("sandbox")
    assert run("sync").exit_code == 0
    for cmd in _commands():
        if "--skip-project" in cmd:
            continue  # the guide's project non-prod does not exist in the fake organization
        r = run("--auto-approve", *shlex.split(cmd))
        allowed = next((codes for key, codes in EXPECTED.items() if cmd.startswith(key)), {0})
        assert r.exit_code in allowed, f"{cmd}\n{r.output}"
    return {c["body"]["name"]: c["body"] for c in fake.clusters.values()}


@pytest.mark.story("CAP-051", "AC8")
def test_cluster_mds_ac8_guide_steps(fake, run, tmp_path):
    commands = _commands()
    assert any("--group data:3x8/32" in c for c in commands) and any(c.startswith("cluster group add") for c in commands)
    clusters = _run_guide(fake, run)
    assert {"prod-01", "prod-02", "prod-03", "prod-01-weu", "prod-01-copy", "dev-03", "prod-04"} <= set(clusters)
    assert [g["services"] for g in clusters["prod-01"]["serviceGroups"]] == \
        [["data"], ["index", "query"], ["search"], ["eventing"]]


@pytest.mark.story("CAP-061", "AC2")
def test_disk_guide_ac2_steps_run(fake, run, tmp_path):
    """Section 10 (choose the disk type, CAP-060) runs with the rest of the guide."""
    assert any(c.startswith("cluster disk-types") for c in _commands())
    disks = {",".join(g["services"]): g["node"]["disk"] for g in _run_guide(fake, run)["prod-05"]["serviceGroups"]}
    assert disks == {"data,index,query": {"type": "io2", "storage": 200, "iops": 20000},
                     "search": {"type": "io2", "storage": 200, "iops": 5740}}
    first = next(c for c in fake.calls("POST", "*/clusters") if c.body["name"] == "prod-05").body
    assert first["serviceGroups"][0]["node"]["disk"] == {"type": "gp3", "storage": 200, "iops": 5740}
