"""CAP-051 AC2: `--group SERVICES:NODESxCPU/RAM[:DISK]` parsing."""
from __future__ import annotations

import pytest

from capellactl.cli.cluster_ops import parse_group_spec
from capellactl.cli.exit_codes import CliExit, ExitCode

NO_DISK = {"type": None, "size": None, "iops": None, "auto-expansion": None}


@pytest.mark.story("CAP-051", "AC2")
@pytest.mark.parametrize("spec,expected", [
    ("data:3x8/32", {"node": {"compute": {"cpu": 8, "ram": 32}, "disk": {"type": "gp3", "storage": 50, "iops": 3000}},
                     "numOfNodes": 3, "services": ["data"]}),
    ("query,data,index:3x8/32:size=100,iops=5000",
     {"node": {"compute": {"cpu": 8, "ram": 32}, "disk": {"type": "gp3", "storage": 100, "iops": 5000}},
      "numOfNodes": 3, "services": ["data", "index", "query"]}),
    ("search:2 x 4 / 16:type=io2", {"node": {"compute": {"cpu": 4, "ram": 16},
                                             "disk": {"type": "io2", "storage": 50, "iops": 3000}},
                                    "numOfNodes": 2, "services": ["search"]}),
])
def test_cluster_mds_ac2_parse_group_spec(spec, expected):
    assert parse_group_spec(spec, "aws", NO_DISK) == expected


@pytest.mark.story("CAP-051", "AC2")
@pytest.mark.parametrize("spec,msg", [
    ("data:3x8", "expected NODESxCPU/RAM, e.g. 3x8/32"),
    ("data:three x8/32", "expected NODESxCPU/RAM"),
    ("data:3x8/32x", "expected NODESxCPU/RAM"),
    ("data:3*8/32", "expected NODESxCPU/RAM"),
    ("data:3x8/32:size=abc", "size must be a whole number (got 'abc')"),
    ("data:3x8/32:speed=1", "unknown disk option 'speed'"),
    ("data:3x8/32:auto-expansion=maybe", "auto-expansion is true or false"),
    ("cache:3x8/32", "unknown service 'cache'"),
    ("dat:3x8/32", "unknown service 'dat'; did you mean data?"),
    (":3x8/32", "no services"),
    ("data", "expected SERVICES:NODESxCPU/RAM[:DISK]"),
    ("data:3x8/32:size=1:x", "expected SERVICES:NODESxCPU/RAM[:DISK]"),
])
def test_cluster_mds_ac2_parse_errors(spec, msg):
    with pytest.raises(CliExit) as exc:
        parse_group_spec(spec, "aws", NO_DISK)
    assert exc.value.code is ExitCode.CONFIG_INVALID and msg in exc.value.message
    assert exc.value.message.startswith(f"--group {spec}")


@pytest.mark.story("CAP-051", "AC5")
def test_cluster_mds_ac5_disk_defaults_per_provider():
    assert parse_group_spec("data:3x8/32", "gcp", NO_DISK)["node"]["disk"] == {"type": "pd-ssd", "storage": 50}
    assert parse_group_spec("data:3x8/32", "azure", NO_DISK)["node"]["disk"] == {"type": "P6"}
    azure = parse_group_spec("data:3x8/32:auto-expansion=true", "azure", NO_DISK)
    assert azure["node"]["disk"] == {"type": "P6", "autoExpansion": True}
    base = {**NO_DISK, "size": 100}
    assert parse_group_spec("data:3x8/32", "aws", base)["node"]["disk"]["storage"] == 100
    assert parse_group_spec("data:3x8/32:size=200", "aws", base)["node"]["disk"]["storage"] == 200


@pytest.mark.story("CAP-051", "AC6")
@pytest.mark.parametrize("answer,expected", [
    ("multiple", "multiple groups"), ("m", "multiple groups"), ("ONE", "one group"),
    ("multiple groups", "multiple groups"), ("developer", "developer pro"), ("e", "enterprise"),
])
def test_cluster_mds_ac6_choice_accepts_start_of_answer(answer, expected):
    from capellactl.cli.cluster_ops import PrefixChoice

    choices = PrefixChoice(["one group", "multiple groups", "basic", "developer pro", "enterprise"])
    assert choices.convert(answer, None, None) == expected


@pytest.mark.story("CAP-051", "AC6")
def test_cluster_mds_ac6_choice_refuses_ambiguous_or_unknown():
    import click

    from capellactl.cli.cluster_ops import PrefixChoice

    for answer in ("", "many", "s"):  # "s" starts both "small" and "single"
        with pytest.raises(click.BadParameter):
            PrefixChoice(["small", "single", "multiple groups"]).convert(answer, None, None)
