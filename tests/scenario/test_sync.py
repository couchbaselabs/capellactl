"""CAP-038: capellactl sync."""
from __future__ import annotations

import pytest
import yaml

from tests.conftest import file_clusters, seed_healthy


@pytest.fixture
def imported(fake, run, tmp_path):
    seed_healthy(fake)
    assert run("import").exit_code == 0
    return tmp_path / "capella.yaml"


@pytest.mark.story("CAP-038", "AC9")
def test_sync_ac9_refreshes_with_diff(fake, run, imported):
    pid, cid = next(iter(fake.projects)), next(iter(fake.clusters))
    fake.clusters[cid]["body"]["description"] = "changed in the Capella UI"
    fake.seed_cluster(pid, "made-in-ui")
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert "-    description: Nova development cluster" in r.output
    assert "+    description: changed in the Capella UI" in r.output and "+    name: made-in-ui" in r.output
    names = [c["name"] for c in file_clusters(imported)]
    assert names == ["nova-dev-01", "made-in-ui"]
    assert (imported.parent / "capella.yaml.bak").exists()


@pytest.mark.story("CAP-038", "AC9")
def test_sync_ac9_keeps_local_only_values(fake, run, imported):
    cid = next(iter(fake.clusters))
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024)
    fake.users["u-1"] = {"id": "u-1", "_cluster": cid, "name": "app", "access": [
        {"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}]}
    assert run("sync").exit_code == 0
    data = yaml.safe_load(imported.read_text(encoding="utf-8"))
    data["organizationId"] = "${CAPELLA_ORG_ID}"
    data["credentialsOutput"] = "./secrets/creds"
    cl0 = data["projects"][0]["clusters"][0]
    cl0["allowAnyIp"] = True
    cl0["databaseCredentials"][0]["password"] = "${APP_PASSWORD}"
    imported.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    fake.clusters[cid]["body"]["description"] = "changed"
    r = run("sync")
    assert r.exit_code == 0, r.output
    new = yaml.safe_load(imported.read_text(encoding="utf-8"))
    assert new["organizationId"] == "${CAPELLA_ORG_ID}" and new["credentialsOutput"] == "./secrets/creds"
    ncl = new["projects"][0]["clusters"][0]
    assert ncl["allowAnyIp"] is True and ncl["databaseCredentials"][0]["password"] == "${APP_PASSWORD}"
    assert "kept password reference for nova-dev-01/app" in r.output
    assert "password reference kept from the previous capella.yaml" in imported.read_text(encoding="utf-8")


@pytest.mark.story("CAP-038", "AC9")
def test_sync_ac9_second_run_in_sync(fake, run, imported):
    fake.clusters[next(iter(fake.clusters))]["body"]["description"] = "changed"
    run("sync")
    r = run("sync")
    assert r.exit_code == 0 and "capella.yaml is already in sync with Capella." in r.output


@pytest.mark.story("CAP-038", "AC10")
def test_sync_ac10_dry_run_exit_codes(fake, run, imported):
    assert run("sync", "--dry-run").exit_code == 0
    before = imported.read_text(encoding="utf-8")
    fake.clusters[next(iter(fake.clusters))]["body"]["description"] = "changed"
    r = run("sync", "--dry-run")
    assert r.exit_code == 2 and "out of sync with Capella (nothing written" in r.output
    assert imported.read_text(encoding="utf-8") == before


@pytest.mark.story("CAP-038", "AC11")
def test_sync_ac11_only_gets(fake, run, imported):
    fake.reset_calls()
    fake.clusters[next(iter(fake.clusters))]["body"]["description"] = "changed"
    assert run("sync").exit_code == 0
    assert fake.calls() and fake.writes() == []


def test_sync_cluster_filter_keeps_others(fake, run, imported):
    pid = next(iter(fake.projects))
    other = fake.seed_cluster(pid, "other")
    run("sync")
    fake.clusters[other]["body"]["description"] = "changed"
    fake.clusters[next(iter(fake.clusters))]["body"]["description"] = "first changed"
    run("sync", "--cluster", "other")
    clusters = {c["name"]: c for c in file_clusters(imported)}
    assert clusters["other"]["description"] == "changed"
    assert clusters["nova-dev-01"]["description"] == "Nova development cluster"


@pytest.mark.story("CAP-038", "AC13")
def test_sync_ac13_removes_project_deleted_in_capella(fake, run, imported):
    keep = fake.seed_project("nova-qa")
    fake.seed_cluster(keep, "qa-01")
    assert run("import", "--project", "nova-qa").exit_code == 0
    gone = next(p for p, v in fake.projects.items() if v["name"] == "nova-dev")
    del fake.projects[gone]
    for cid in [c for c, v in fake.clusters.items() if v["project"] == gone]:
        del fake.clusters[cid]
    r = run("sync")
    assert r.exit_code == 0, r.output
    assert "project nova-dev no longer exists in Capella; removed from capella.yaml with its clusters" in r.output
    names = [p["name"] for p in yaml.safe_load(imported.read_text(encoding="utf-8"))["projects"]]
    assert names == ["nova-qa"]
    assert "already in sync" in run("sync").output


@pytest.mark.story("CAP-038", "AC13")
def test_sync_ac13_last_project_deleted_leaves_valid_file(fake, run, imported):
    fake.projects.clear()
    fake.clusters.clear()
    r = run("sync")
    assert r.exit_code == 0, r.output
    text = imported.read_text(encoding="utf-8")
    assert yaml.safe_load(text)["projects"] == [] and "capellactl project create NAME" in text
    assert run("validate").exit_code == 0
    assert "already in sync" in run("sync").output


@pytest.mark.story("CAP-038", "AC13")
def test_sync_ac13_keeps_project_never_deployed(fake, run, imported):
    data = yaml.safe_load(imported.read_text(encoding="utf-8"))
    data["projects"].append({"name": "nova-new", "clusters": []})
    imported.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    r = run("sync")
    assert "project nova-new is not in Capella yet; kept as it is" in r.output
    names = [p["name"] for p in yaml.safe_load(imported.read_text(encoding="utf-8"))["projects"]]
    assert "nova-new" in names


@pytest.mark.story("CAP-038", "AC13")
@pytest.mark.parametrize("args", [(), ("--cluster", "nova-dev-01")])
def test_sync_ac13_removes_cluster_deleted_in_capella(fake, run, imported, args):
    pid = next(iter(fake.projects))
    fake.seed_cluster(pid, "other")
    cid = next(iter(fake.clusters))
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024)
    assert run("sync").exit_code == 0
    del fake.clusters[cid]
    r = run("sync", *args)
    assert r.exit_code == 0, r.output
    assert "cluster nova-dev-01 no longer exists in Capella; removed from capella.yaml with its buckets" in r.output
    assert [c["name"] for c in file_clusters(imported)] == ["other"]
    assert "orders" not in imported.read_text(encoding="utf-8")


@pytest.mark.story("CAP-038", "AC9")
def test_sync_ac9_whole_bucket_wildcard_not_written(fake, run, imported):
    """Capella returns a whole-bucket grant as scopes: [{name: '*'}]; sync must not write it (it failed validation)."""
    cid = next(iter(fake.clusters))
    fake.seed_bucket(cid, "demo", memoryAllocationInMb=512)
    assert run("sync").exit_code == 0
    assert run("--auto-approve", "scope", "create", "nova-dev-01", "demo", "inventory").exit_code == 0
    assert run("--auto-approve", "collection", "create", "nova-dev-01", "demo", "inventory", "airline").exit_code == 0
    pw = {"RO_PW": "Demo-R3ad-2026!", "AIRLINE_PW": "Demo-A1rline-2026!"}
    assert run("--auto-approve", "credential", "create", "nova-dev-01", "demo_ro", "--bucket", "demo",
               "--password-env", "RO_PW", extra_env=pw).exit_code == 0
    r = run("sync", extra_env=pw)
    assert r.exit_code == 0, r.output
    assert "'*'" not in imported.read_text(encoding="utf-8") and '"*"' not in imported.read_text(encoding="utf-8")
    r = run("--auto-approve", "credential", "create", "nova-dev-01", "airline_app", "--privileges", "read+write",
            "--bucket", "demo", "--scope", "inventory", "--collection", "airline", "--password-env", "AIRLINE_PW",
            extra_env=pw)
    assert r.exit_code == 0, r.output
    assert "No changes" in run("--auto-approve", "apply", extra_env=pw).output


@pytest.mark.story("CAP-038", "AC9")
def test_sync_ac9_file_with_wildcard_still_loads(fake, run, imported):
    cid = next(iter(fake.clusters))
    fake.seed_bucket(cid, "demo", memoryAllocationInMb=512)
    assert run("sync").exit_code == 0
    data = yaml.safe_load(imported.read_text(encoding="utf-8"))
    data["projects"][0]["clusters"][0]["databaseCredentials"] = [{"name": "demo_ro", "access": [
        {"privileges": ["data_reader"], "resources": {"buckets": [{"name": "demo", "scopes": [{"name": "*"}]}]}}]}]
    imported.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    assert run("validate").exit_code == 0
