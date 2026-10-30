"""CAP-060: choose the disk type, and see what each type means."""
from __future__ import annotations

import json

import pytest

from capellactl.cli import console
from tests.conftest import file_clusters, seed_healthy


@pytest.fixture
def imported(fake, run, tmp_path):
    _, cid = seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml", cid


def _cluster(path, name):
    return next(c for c in file_clusters(path) if c["name"] == name)


def _create(run, name, answers):
    return run("cluster", "create", name, input="\n".join(answers) + "\n")


@pytest.mark.story("CAP-060", "AC1")
def test_disk_types_ac1_list(run):
    r = run("cluster", "disk-types")
    assert r.exit_code == 0, r.output
    lines = r.output.splitlines()
    assert lines[0].split() == ["S.NO", "PROVIDER", "TYPE", "SIZE", "(GB)", "IOPS", "FOR"]
    assert lines[1].split()[:5] == ["1", "aws", "gp3", "50–16000", "3000–16000"] and "general-purpose" in lines[1]
    assert "io2" in lines[2] and "3000–64000" in lines[2]
    assert "pd-ssd" in r.output and "60 per GB" in r.output and "Ultra" in r.output
    r = run("cluster", "disk-types", "--provider", "azure")
    rows = [line.split()[2] for line in r.output.splitlines()[1:] if line[:1].isdigit()]
    assert rows == ["P6", "P10", "P15", "P20", "P30", "P40", "P50", "P60", "Ultra"]
    data = json.loads(run("-o", "json", "cluster", "disk-types", "--provider", "aws").output)
    assert list(data) == ["aws"] and data["aws"]["io2"]["iops"] == [3000, 64000]


@pytest.mark.story("CAP-060", "AC1")
def test_disk_types_ac1_options_points_to_list(fake, run, imported):
    r = run("cluster", "options")
    assert r.exit_code == 0, r.output
    assert "disk types       aws gp3, io2 · gcp pd-ssd · azure P6" in r.output
    assert "capellactl cluster disk-types" in r.output
    data = json.loads(run("-o", "json", "cluster", "options").output)
    assert data["provisioned"]["diskTypes"]["gcp"] == ["pd-ssd"]


@pytest.mark.story("CAP-060", "AC2")
@pytest.mark.parametrize("provider,disk_answers,disk,shown", [
    ("aws", ["2", "200", ""], {"type": "io2", "storage": 200, "iops": 5740}, "IOPS (3000–64000; recommended 5740"),
    ("azure", ["3"], {"type": "P15"}, "P15: 256 GB, 1100 IOPS (set by the type)"),
    ("gcp", ["1", "100"], {"type": "pd-ssd", "storage": 100}, "up to 3000 read and 3000 write IOPS"),
])
def test_disk_types_ac2_create_picker(fake, run, imported, monkeypatch, provider, disk_answers, disk, shown):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    answers = ["provisioned", provider, "custom", "one group", "3", "8", "32", *disk_answers, "", "", "", "y"]
    r = _create(run, "nova-qa-01", answers)
    assert r.exit_code == 0, r.output
    assert "Disk type:" in r.output and shown in r.output
    assert r.output.index("Disk type:") > r.output.index("RAM GB per node")  # asked after the node size
    body = fake.calls("POST", "*/clusters")[0].body
    assert body["serviceGroups"][0]["node"]["disk"] == disk


@pytest.mark.story("CAP-060", "AC2")
def test_disk_types_ac2_group_add_picker(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "group", "add", "nova-dev-01", "--services", "search", input="2\n2\n100\n\ny\n")
    assert r.exit_code == 0, r.output
    assert "Disk type:" in r.output and "Choose [1]" in r.output  # the data group's gp3 is the default
    groups = fake.calls("PUT", "*/clusters/*")[0].body["serviceGroups"]
    assert groups[1]["node"]["disk"] == {"type": "io2", "storage": 100, "iops": 4370}


@pytest.mark.story("CAP-060", "AC5")
def test_disk_types_ac5_update_type(fake, run, imported):
    path, _ = imported
    r = run("--auto-approve", "cluster", "update", "nova-dev-01", "--disk-type", "io2")
    assert r.exit_code == 0, r.output
    assert 'serviceGroups[data,index,query].node.disk.type:  "gp3" → "io2"' in r.output
    assert "disk type io2: provisioned-IOPS SSD" in r.output and "rebalances the nodes" in r.output
    puts = fake.calls("PUT", "*/clusters/*")
    assert len(puts) == 1
    assert puts[0].body["serviceGroups"][0]["node"]["disk"] == {"type": "io2", "storage": 50, "iops": 3000}
    assert _cluster(path, "nova-dev-01")["serviceGroups"][0]["node"]["disk"]["type"] == "io2"


@pytest.mark.story("CAP-060", "AC5")
def test_disk_types_ac5_rerun_noop_and_wrong_provider(fake, run, imported):
    assert run("--auto-approve", "cluster", "update", "nova-dev-01", "--disk-type", "io2", "--disk-iops",
               "20000").exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "cluster", "update", "nova-dev-01", "--disk-type", "io2", "--disk-iops", "20000")
    assert r.exit_code == 0 and "No changes" in r.output
    assert fake.writes() == []
    r = run("--auto-approve", "cluster", "update", "nova-dev-01", "--disk-type", "P6")
    assert r.exit_code == 3 and "disk type P6 is not valid for aws" in r.output
    r = run("--auto-approve", "cluster", "update", "nova-dev-01", "--disk-iops", "90000")
    assert r.exit_code == 3 and "io2 disks take 3000–64000 IOPS" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-060", "AC6")
def test_disk_types_ac6_help(run):
    for args in (("cluster", "create", "--help"), ("cluster", "update", "--help"), ("cluster", "group", "add", "--help")):
        r = run(*args)
        assert "capellactl cluster disk-types" in " ".join(r.output.split()), args
    r = run("help", "scaling")
    assert "Disk types" in r.output and "capellactl cluster disk-types" in r.output
