"""CAP-038: deploy and change clusters from the CLI; capella.yaml is written by the tool."""
from __future__ import annotations

import pytest

from capellactl.cli import console
from tests.conftest import file_clusters, seed_healthy


@pytest.fixture
def imported(fake, run, tmp_path):
    seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.reset_calls()
    return tmp_path / "capella.yaml"


def _clusters(path):
    return {c["name"]: c for c in file_clusters(path)}


@pytest.mark.story("CAP-038", "AC1")
def test_cluster_create_ac1_interactive_deploys(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "create", "nova-dev-02", input="\n\n\n\n\n\ny\n")  # first Enter: cluster type
    assert r.exit_code == 0, r.output
    for prompt in ("Cluster type (free, provisioned) [provisioned]", "Cloud provider", "Size", "Region [us-east-1]", "Network CIDR", "Support plan",
                   "Add nova-dev-02 to capella.yaml and deploy it now? [y/N]"):
        assert prompt in r.output, prompt
    assert "+ cluster nova-dev-02  aws us-east-1 · multi-AZ · 3 × 4 vCPU/16 GB" in r.output
    assert "cluster nova-dev-02: healthy" in r.output and "connectionString (nova-dev-02)" in r.output
    assert len(fake.calls("POST", "*/clusters")) == 1
    c = _clusters(imported)["nova-dev-02"]
    assert c["cloudProvider"] == {"type": "aws", "region": "us-east-1", "cidr": "10.0.0.0/24"}
    assert c["serviceGroups"][0]["numOfNodes"] == 3 and c["couchbaseServer"]["version"] == "8.0.1"


@pytest.mark.story("CAP-038", "AC2")
def test_cluster_create_ac2_flags_and_defaults(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "nova-qa-01", "--provider", "gcp", "--size", "medium",
            "--support-plan", "enterprise")
    assert r.exit_code == 0, r.output
    c = _clusters(imported)["nova-qa-01"]
    assert c["cloudProvider"]["region"] == "us-east1"
    assert c["serviceGroups"][0]["node"] == {"compute": {"cpu": 8, "ram": 32}, "disk": {"type": "pd-ssd", "storage": 50}}
    assert c["support"]["plan"] == "enterprise"
    r = run("--auto-approve", "cluster", "create", "nova-ci-01", "--size", "dev")
    assert r.exit_code == 0, r.output
    c = _clusters(imported)["nova-ci-01"]
    assert c["configurationType"] == "singleNode" and c["availability"] == {"type": "single"}


@pytest.mark.story("CAP-038", "AC2")
def test_cluster_create_ac2_non_interactive_needs_auto_approve(fake, run, imported):
    before = imported.read_text(encoding="utf-8")
    r = run("cluster", "create", "nova-qa-01")
    assert r.exit_code == 1 and "[ERROR]: refusing to change capella.yaml and Capella without approval: there is no terminal to ask" in r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-038", "AC4")
@pytest.mark.parametrize("args,msg", [
    (["--provider", "gcp", "--disk-type", "gp3"], "disk type gp3 is not valid for gcp"),
    (["--nodes", "2"], "must be between 3 and 27"),
    (["--size", "dev", "--availability", "multi"], "singleNode clusters must use availability: single"),
    (["--cidr", "10.10.0.5/24"], "is not a network address"),
    (["--provider", "azure", "--region", "us-east-1"],
     "us-east-1 is not an azure region name; it looks like an aws region (azure regions look like eastus"),
    (["--provider", "gcp", "--region", "eastus"], "eastus is not a gcp region name; it looks like an azure region"),
    (["--cidr", "10.10.0.0/24"], "overlaps the network of cluster 'nova-dev-01'"),
])
def test_cluster_create_ac4_invalid_input_writes_nothing(fake, run, imported, args, msg):
    before = imported.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "create", "bad-01", *args)
    assert r.exit_code == 3 and msg in r.output, r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-038", "AC4")
def test_cluster_create_ac4_interactive_reasks(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    # first round: CIDR with host bits → re-asked; second round: defaults → deployed
    r = run("cluster", "create", "nova-dev-03", input="\n\n\n\n10.0.0.5/23\n\n\n\n\n\n\ny\n")
    assert "is not a network address" in r.output and "[ACTION]: Please try again" in r.output
    assert r.exit_code == 0, r.output
    assert "nova-dev-03" in _clusters(imported)


@pytest.mark.story("CAP-038", "AC4")
def test_cluster_create_ac4_existing_problems_stop_before_questions(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    text = imported.read_text(encoding="utf-8")
    at = text.index("serviceGroups:")
    imported.write_text(text[:at] + "databaseCredentials:\n          - name: app\n            access:\n"
                        "              - privileges: [read]\n                resources:\n                  buckets:\n"
                        "                    - name: ordrs\n        " + text[at:], encoding="utf-8")
    before = imported.read_text(encoding="utf-8")
    r = run("cluster", "create", "bad-01", input="\n" * 20)
    assert r.exit_code == 3 and "already had 1 problem before this command, so nothing was changed" in r.output, r.output
    assert "cluster nova-dev-01 › credential app" in r.output
    assert "Cloud provider" not in r.output and "Please try again" not in r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-038", "AC4")
def test_cluster_create_ac4_interactive_flag_conflict_not_reasked(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    before = imported.read_text(encoding="utf-8")
    # --size dev --availability multi conflict: only the CIDR is asked, then the command exits instead of re-asking
    r = run("cluster", "create", "bad-01", "--provider", "azure", "--region", "eastus", "--size", "dev",
            "--availability", "multi", "--support-plan", "developer pro", input="\n")
    assert r.exit_code == 3 and "singleNode clusters must use availability: single" in r.output, r.output
    assert "Please try again" not in r.output and "Cloud provider" not in r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-038", "AC5")
def test_cluster_create_ac5_existing_name(fake, run, imported):
    r = run("--auto-approve", "cluster", "create", "nova-dev-01")
    assert r.exit_code == 4 and "[ERROR]: cluster nova-dev-01 already exists\n[ACTION]: Change it with 'capellactl cluster update'" in r.output
    pid = next(iter(fake.projects))
    fake.seed_cluster(pid, "made-in-ui")
    r = run("--auto-approve", "cluster", "create", "made-in-ui")
    assert r.exit_code == 4 and "'capellactl sync' to bring it into capella.yaml" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-038", "AC6")
def test_cluster_scale_ac6_updates_file(fake, run, imported):
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "5")
    assert r.exit_code == 0, r.output
    assert _clusters(imported)["nova-dev-01"]["serviceGroups"][0]["numOfNodes"] == 5
    fake.reset_calls()
    assert run("plan", "--detailed-exitcode").exit_code == 0 and fake.writes() == []


@pytest.mark.story("CAP-038", "AC7")
def test_cluster_update_ac7_changes_file_and_applies(fake, run, imported):
    r = run("--auto-approve", "cluster", "update", "nova-dev-01", "--support-plan", "enterprise",
            "--description", "now enterprise", "--cpu", "8", "--ram", "32")
    assert r.exit_code == 0, r.output
    assert 'support.plan:  "developer pro" → "enterprise"' in r.output
    c = _clusters(imported)["nova-dev-01"]
    assert c["support"]["plan"] == "enterprise" and c["description"] == "now enterprise"
    assert c["serviceGroups"][0]["node"]["compute"] == {"cpu": 8, "ram": 32}
    assert len(fake.calls("PUT", "*/clusters/*")) == 1


@pytest.mark.story("CAP-038", "AC7")
def test_cluster_update_ac7_no_immutable_options(run):
    text = run("cluster", "update", "--help").output
    for opt in ("--provider", "--region", "--cidr", "--availability"):
        assert opt not in text


@pytest.mark.story("CAP-038", "AC7")
def test_cluster_update_ac7_interactive_asks(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("cluster", "update", "nova-dev-01", input="\nenterprise\n\n\n\n\ny\n")
    assert r.exit_code == 0, r.output
    assert "Press Enter to keep the current value" in r.output
    assert _clusters(imported)["nova-dev-01"]["support"]["plan"] == "enterprise"


@pytest.mark.story("CAP-038", "AC8")
def test_cluster_cli_ac8_decline_writes_nothing(fake, run, imported, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    before = imported.read_text(encoding="utf-8")
    r = run("cluster", "scale", "nova-dev-01", "--nodes", "4", input="n\n")
    assert "Cancelled; capella.yaml and Capella are unchanged." in r.output
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-038", "AC8")
def test_cluster_cli_ac8_no_apply_and_comments_kept(fake, run, imported):
    imported.write_text(imported.read_text(encoding="utf-8").replace("projects:\n", "# my note about projects\nprojects:\n"), encoding="utf-8")
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "4", "--no-apply")
    assert r.exit_code == 0 and "Not applied (--no-apply)" in r.output
    text = imported.read_text(encoding="utf-8")
    assert "# my note about projects" in text and "# Imported by capellactl" in text and "numOfNodes: 4" in text
    assert (imported.parent / "capella.yaml.bak").exists()
    assert fake.writes() == []


@pytest.mark.story("CAP-038", "AC8")
def test_cluster_cli_blocked_change_writes_nothing(fake, run, imported):
    before = imported.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "scale", "nova-dev-01", "--nodes", "2")
    assert r.exit_code in (3, 4)  # below the limit (3) or scale-in (4): never written
    assert imported.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-038", "AC11")
def test_cluster_cli_ac11_create_then_in_sync(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "nova-dev-02").exit_code == 0
    fake.reset_calls()
    assert "No changes" in run("--auto-approve", "apply").output
    r = run("sync", "--dry-run")
    assert r.exit_code == 0 and "already in sync" in r.output
    assert fake.writes() == []


def test_cluster_create_needs_capella_yaml(fake, run):
    r = run("--auto-approve", "cluster", "create", "x")
    assert r.exit_code == 3 and "[ACTION]: Run 'capellactl sync'" in r.output


@pytest.mark.story("CAP-038", "AC8")
def test_cluster_cli_ac8_rejected_create_restores_file(fake, run, imported):
    before = imported.read_text(encoding="utf-8")
    fake.fail_next("POST", "*/clusters", 500)
    r = run("--auto-approve", "cluster", "create", "nova-qa-01", "--provider", "azure", "--region", "eastus")
    assert r.exit_code == 1, r.output
    assert "Capella did not accept the change, so capella.yaml was restored" in r.output
    assert "re-run apply" not in r.output
    assert imported.read_text(encoding="utf-8") == before


@pytest.mark.story("CAP-038", "AC8")
def test_cluster_cli_ac8_accepted_create_keeps_file(fake, run, imported):
    # POST accepted, then status polling fails: the cluster exists in Capella, so the file keeps it
    fake.fail_next("GET", "*/clusters/*", 500, times=50)
    r = run("--auto-approve", "cluster", "create", "nova-qa-01")
    assert r.exit_code == 1, r.output
    assert "was restored" not in r.output
    assert "nova-qa-01" in _clusters(imported)


@pytest.mark.story("CAP-038", "AC8")
def test_cluster_cli_ac8_rerun_replaces_undeployed_entry(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "nova-qa-01", "--provider", "gcp", "--no-apply").exit_code == 0
    from capellactl.config.editor import ConfigEditor
    ed = ConfigEditor(imported)
    ed.find_cluster("nova-qa-01")[1]["buckets"] = [{"name": "events"}]
    ed.save()
    r = run("--auto-approve", "cluster", "create", "nova-qa-01", "--provider", "azure", "--region", "eastus")
    assert r.exit_code == 0, r.output
    assert "nova-qa-01 is in capella.yaml but was never deployed to Capella; replacing it" in r.output
    c = _clusters(imported)["nova-qa-01"]
    assert c["cloudProvider"]["type"] == "azure" and c["cloudProvider"]["region"] == "eastus"
    assert [b["name"] for b in c["buckets"]] == ["events"] and "id" in c
    assert [x["name"] for x in file_clusters(imported)].count("nova-qa-01") == 1


@pytest.mark.story("CAP-038", "AC8")
def test_cluster_cli_ac8_deployed_entry_still_blocked(fake, run, imported):
    assert run("--auto-approve", "cluster", "create", "nova-qa-01").exit_code == 0
    cid = next(k for k, v in fake.clusters.items() if v["body"]["name"] == "nova-qa-01")
    del fake.clusters[cid]  # deleted outside capellactl; the file still has its id
    r = run("--auto-approve", "cluster", "create", "nova-qa-01")
    assert r.exit_code == 4 and "cluster nova-qa-01 already exists" in r.output


@pytest.mark.story("CAP-038", "AC7")
def test_cluster_update_ac7_azure_premium_disk_not_resized(fake, run, tmp_path, monkeypatch):
    """Capella refuses storage/iops for Azure P6…P60 disks, but returns them on GET (2026-10-07)."""
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    fake.seed_project("nova-demo")
    assert run("import").exit_code == 0
    r = run("--auto-approve", "cluster", "create", "nova-demo-01", "--project", "nova-demo", "--provider", "azure",
            "--region", "eastus", "--size", "dev")
    assert r.exit_code == 0, r.output
    disk = fake.clusters[next(iter(fake.clusters))]["body"]["serviceGroups"][0]["node"]["disk"]
    assert disk["type"] == "P6" and disk["storage"] == 64  # Capella reports the fixed size
    assert run("sync").exit_code == 0  # the file now holds storage: 64, iops: 240, as for a real cluster
    r = run("--auto-approve", "cluster", "update", "nova-demo-01", "--description", "Nova demo cluster")
    assert r.exit_code == 0, r.output
    put = [c for c in fake.writes() if c.method == "PUT" and "/clusters/" in c.path][-1]
    assert "storage" not in put.body["serviceGroups"][0]["node"]["disk"]
    assert "No changes" in run("--auto-approve", "apply").output
    r = run("--auto-approve", "cluster", "update", "nova-demo-01", "--disk-size", "128")
    assert r.exit_code == 3 and "size and IOPS are set by the type" in r.output


@pytest.mark.story("CAP-038", "AC8")
def test_cluster_cli_ac8_new_keys_in_import_order(fake, run, tmp_path, monkeypatch):
    """A key added by a command lands where import writes it, not after the buckets and credentials (2026-10-07)."""
    monkeypatch.setattr(console, "is_interactive", lambda: False)
    _, cid = seed_healthy(fake, description="")
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=1024)
    assert run("import").exit_code == 0
    assert run("--auto-approve", "credential", "create", "nova-dev-01", "app", "--bucket", "orders",
               "--password-env", "APP_PW", extra_env={"APP_PW": "S3cure-Passw0rd!"}).exit_code == 0
    r = run("--auto-approve", "cluster", "update", "nova-dev-01", "--description", "Nova demo cluster",
            extra_env={"APP_PW": "S3cure-Passw0rd!"})
    assert r.exit_code == 0, r.output
    assert run("cluster", "protect", "nova-dev-01", "--on", extra_env={"APP_PW": "S3cure-Passw0rd!"}).exit_code == 0
    keys = [ln.strip().split(":")[0] for ln in (tmp_path / "capella.yaml").read_text(encoding="utf-8").splitlines()
            if ln.startswith("        ") and not ln.startswith("         ") and ":" in ln]
    keys = [k.lstrip("- ") for k in keys]
    assert keys.index("description") == keys.index("name") + 1
    assert keys.index("deletionProtection") < keys.index("buckets") < keys.index("databaseCredentials")
    r = run("sync", extra_env={"APP_PW": "S3cure-Passw0rd!"})
    assert "already in sync" in r.output, r.output


@pytest.fixture
def ui_made(fake, run, tmp_path):
    """nova-dev-01 is in capella.yaml; ui-made (10.0.0.0/24) was created in the Capella UI after the import."""
    pid, _ = seed_healthy(fake)
    assert run("import").exit_code == 0
    fake.seed_cluster(pid, "ui-made", cloudProvider={"type": "aws", "region": "us-east-1", "cidr": "10.0.0.0/24"})
    fake.reset_calls()
    return tmp_path / "capella.yaml"


OVERLAP = ("[ERROR]: 10.0.0.0/24 overlaps the network of cluster ui-made (10.0.0.0/24), which is in this project in "
           "Capella but not in capella.yaml\n[ACTION]: Use a range that overlaps no other cluster, for example "
           "--cidr 10.0.1.0/24")


@pytest.mark.story("CAP-038", "AC15")
@pytest.mark.parametrize("extra", [[], ["--no-apply"], ["--free-tier"]], ids=["apply", "no-apply", "free-tier"])
def test_cluster_create_ac15_overlap_with_capella_only_cluster_refused(fake, run, ui_made, extra):
    before = ui_made.read_text(encoding="utf-8")
    r = run("--auto-approve", "cluster", "create", "test-01", "--cidr", "10.0.0.0/24", *extra)
    assert r.exit_code == 3 and OVERLAP in r.output, r.output
    assert ui_made.read_text(encoding="utf-8") == before and fake.writes() == []


@pytest.mark.story("CAP-038", "AC15")
def test_cluster_create_ac15_overlap_typed_is_reasked(fake, run, ui_made, monkeypatch):
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    # type, provider, size, region, then the overlapping range, then the suggested one, then plan, y
    r = run("cluster", "create", "test-01", input="\n\n\n\n10.0.0.0/24\n\n\ny\n")
    assert r.exit_code == 0, r.output
    assert "[ERROR]: 10.0.0.0/24 overlaps the network of cluster ui-made" in r.output
    assert "[ACTION]: Please try again with a range that overlaps no other cluster." in r.output
    assert r.output.count("Network CIDR") == 2 and r.output.count("Cloud provider") == 1
    assert _clusters(ui_made)["test-01"]["cloudProvider"]["cidr"] == "10.0.1.0/24"


@pytest.mark.story("CAP-038", "AC15")
def test_cluster_create_ac15_other_project_warns(fake, run, ui_made):
    other = fake.seed_project("non-prod")
    fake.seed_cluster(other, "np-01", cloudProvider={"type": "aws", "region": "us-east-1", "cidr": "10.20.0.0/24"})
    r = run("--auto-approve", "cluster", "create", "test-01", "--cidr", "10.20.0.0/24")
    assert r.exit_code == 0, r.output
    assert ("[WARNING]: 10.20.0.0/24 overlaps the network of cluster np-01 (10.20.0.0/24) in project non-prod\n"
            "[ACTION]: None needed unless you will connect the two networks") in r.output
    assert _clusters(ui_made)["test-01"]["cloudProvider"]["cidr"] == "10.20.0.0/24"
