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


@pytest.mark.story("CAP-051", "AC8")
def test_cluster_mds_ac8_guide_steps(fake, run, tmp_path):
    fake.seed_project("sandbox")
    assert run("sync").exit_code == 0
    commands = _commands()
    assert any("--group data:3x8/32" in c for c in commands) and any(c.startswith("cluster group add") for c in commands)
    for cmd in commands:
        if "--skip-project" in cmd:
            continue  # the guide's project non-prod does not exist in the fake organization
        r = run("--auto-approve", *shlex.split(cmd))
        allowed = next((codes for key, codes in EXPECTED.items() if cmd.startswith(key)), {0})
        assert r.exit_code in allowed, f"{cmd}\n{r.output}"
    clusters = {c["body"]["name"]: c["body"] for c in fake.clusters.values()}
    assert {"prod-01", "prod-02", "prod-03", "prod-01-weu", "prod-01-copy", "dev-03", "prod-04"} <= set(clusters)
    assert [g["services"] for g in clusters["prod-01"]["serviceGroups"]] == \
        [["data"], ["index", "query"], ["search"], ["eventing"]]
