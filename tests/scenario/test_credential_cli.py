"""CAP-046: credential list | get | create | update from the CLI."""
from __future__ import annotations

import json

import pytest

from tests.conftest import MINIMAL, assert_no_secret, file_clusters, seed_healthy
from tests.scenario.helpers import ORDERS_APP, ORDERS_BUCKET, ORDERS_PW, USERS, seed_user

PW_ENV = {"ORDERS_APP_PASSWORD": ORDERS_PW}
RW_ORDERS = [{"privileges": ["data_reader", "data_writer"], "resources": {"buckets": [{"name": "orders"}]}}]


@pytest.fixture
def cluster(fake):
    pid, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=100)
    fake.seed_scope(cid, "orders", "inventory", {"items": 0, "suppliers": 0})  # as ORDERS_BUCKET declares
    return pid, cid


def _file_creds(tmp_path):
    return file_clusters(tmp_path / "capella.yaml")[0].get("databaseCredentials")


@pytest.mark.story("CAP-046", "AC1")
def test_credential_cli_ac1_list(fake, run, write_config, cluster):
    _, cid = cluster
    seed_user(fake, cid, "orders_app", RW_ORDERS)
    seed_user(fake, cid, "dba", [], userRoles=[{"name": "admin"}])
    write_config(MINIMAL + ORDERS_BUCKET + "    databaseCredentials:\n      - name: orders_app\n        access:\n"
                 "          - privileges: [read, write]\n            resources: { buckets: [ { name: orders } ] }\n")
    r = run("credential", "list", "nova-dev-01")
    assert r.exit_code == 0, r.output
    lines = [" ".join(x.split()) for x in r.output.splitlines()]
    assert "NAME TYPE ACCESS IN FILE" in lines
    assert "orders_app basic read+write · orders yes" in lines and "dba advanced userRoles -" in lines
    j = run("-o", "json", "credential", "list", "nova-dev-01")
    assert sorted(u["name"] for u in json.loads(j.output)) == ["dba", "orders_app"]
    assert_no_secret(r.output + j.output, "Old!Passw0rd-xyz")


@pytest.mark.story("CAP-046", "AC2")
def test_credential_cli_ac2_get(fake, run, write_config, cluster, tmp_path):
    _, cid = cluster
    uid = seed_user(fake, cid, "orders_app", RW_ORDERS)
    write_config(MINIMAL + ORDERS_BUCKET)
    secret = tmp_path / ".capellactl" / "credentials" / "nova-dev-01.orders_app.json"
    secret.parent.mkdir(parents=True)
    secret.write_text('{"password": "Gen3rated!Pw-local"}')
    r = run("credential", "get", "nova-dev-01", "orders_app")
    assert r.exit_code == 0, r.output
    lines = [" ".join(x.split()) for x in r.output.splitlines()]
    assert f"id {uid}" in lines and "type basic" in lines and "access read+write · orders" in lines
    assert any(x.startswith("generated password saved in ") for x in lines)
    assert_no_secret(r.output, "Gen3rated!Pw-local", "Old!Passw0rd-xyz")
    r = run("credential", "get", "nova-dev-01", "nope")
    assert r.exit_code == 1 and "credential nova-dev-01/nope not found" in r.output


@pytest.mark.story("CAP-046", "AC3")
def test_credential_cli_ac3_create_records_and_applies(fake, run, write_config, cluster, tmp_path):
    pid, cid = cluster
    write_config(MINIMAL + ORDERS_BUCKET)
    r = run("--auto-approve", "credential", "create", "nova-dev-01", "orders_app", "--privileges", "read+write",
            "--bucket", "orders", "--scope", "inventory", "--password-env", "ORDERS_APP_PASSWORD", extra_env=PW_ENV)
    assert r.exit_code == 0, r.output
    access = [{"privileges": ["data_reader", "data_writer"],
               "resources": {"buckets": [{"name": "orders", "scopes": [{"name": "inventory"}]}]}}]
    assert _file_creds(tmp_path) == [{"name": "orders_app", "password": "${ORDERS_APP_PASSWORD}", "access": access}]
    assert [(c.method, c.path, c.body) for c in fake.writes()] == [
        ("POST", USERS.format(pid=pid, cid=cid), {"name": "orders_app", "credentialType": "basic", "access": access,
                                                 "password": ORDERS_PW})]
    assert_no_secret(r.output, ORDERS_PW)


@pytest.mark.story("CAP-046", "AC3")
def test_credential_cli_ac3_create_guards(fake, run, write_config, cluster, tmp_path):
    _, cid = cluster
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP)
    r = run("--auto-approve", "credential", "create", "nova-dev-01", "orders_app", "--bucket", "orders",
            extra_env=PW_ENV)
    assert r.exit_code == 4 and "already in capella.yaml" in r.output
    r = run("--auto-approve", "credential", "create", "nova-dev-01", "other", "--privileges", "read", extra_env=PW_ENV)
    assert r.exit_code == 3 and "pass --bucket NAME (least privilege) or --all-buckets" in r.output
    # exists in Capella with the same access: adopted, zero writes
    seed_user(fake, cid, "adopted", [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}])
    r = run("--auto-approve", "credential", "create", "nova-dev-01", "adopted", "--bucket", "orders", extra_env=PW_ENV)
    assert r.exit_code == 0, r.output
    assert "already exists in Capella with this access" in r.output
    assert fake.writes() == [] and _file_creds(tmp_path)[-1]["name"] == "adopted"


@pytest.mark.story("CAP-046", "AC4")
def test_credential_cli_ac4_update_access(fake, run, write_config, cluster, tmp_path):
    _, cid = cluster
    uid = seed_user(fake, cid, "orders_app", RW_ORDERS)
    write_config(MINIMAL + ORDERS_BUCKET + "    databaseCredentials:\n      - name: orders_app\n        access:\n"
                 "          - privileges: [read, write]\n            resources: { buckets: [ { name: orders } ] }\n")
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app", "--privileges", "read",
            "--bucket", "orders")
    assert r.exit_code == 0, r.output
    read_only = [{"privileges": ["data_reader"], "resources": {"buckets": [{"name": "orders"}]}}]
    assert _file_creds(tmp_path)[0]["access"] == read_only
    assert [(c.method, c.body) for c in fake.writes()] == [("PUT", {"access": read_only})]
    assert fake.users[uid]["access"] == read_only


@pytest.mark.story("CAP-046", "AC4")
def test_credential_cli_ac4_update_guards(fake, run, write_config, cluster):
    two = ("    databaseCredentials:\n      - name: orders_app\n        access:\n"
           "          - privileges: [read]\n            resources: { buckets: [ { name: orders } ] }\n"
           "          - privileges: [write]\n            resources: { buckets: [ { name: orders } ] }\n")
    write_config(MINIMAL + ORDERS_BUCKET + two)
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app", "--bucket", "orders")
    assert r.exit_code == 3 and "has several access grants" in r.output
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app")
    assert r.exit_code == 3 and "nothing to change" in r.output
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "nope", "--bucket", "orders")
    assert r.exit_code == 3 and "is not in capella.yaml" in r.output
    assert fake.writes() == []


@pytest.mark.story("CAP-046", "AC5")
def test_credential_cli_ac5_no_apply(fake, run, write_config, cluster, tmp_path):
    write_config(MINIMAL + ORDERS_BUCKET)
    r = run("--auto-approve", "credential", "create", "nova-dev-01", "orders_app", "--bucket", "orders", "--no-apply")
    assert r.exit_code == 0, r.output
    assert "Not applied (--no-apply)" in r.output
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app", "--privileges", "write",
            "--bucket", "orders", "--no-apply")
    assert r.exit_code == 0 and "Not applied (--no-apply)" in r.output
    assert _file_creds(tmp_path)[0]["access"][0]["privileges"] == ["data_writer"]
    assert fake.writes() == []


@pytest.mark.story("CAP-046", "AC6")
def test_credential_cli_ac6_rerun_zero_writes(fake, run, write_config, cluster):
    write_config(MINIMAL + ORDERS_BUCKET)
    args = ("--auto-approve", "credential", "create", "nova-dev-01", "orders_app", "--privileges", "read+write",
            "--bucket", "orders", "--password-env", "ORDERS_APP_PASSWORD")
    assert run(*args, extra_env=PW_ENV).exit_code == 0
    fake.reset_calls()
    assert run("plan", "--detailed-exitcode", extra_env=PW_ENV).exit_code == 0
    r = run("--auto-approve", "apply", extra_env=PW_ENV)
    assert r.exit_code == 0 and "No changes" in r.output
    assert fake.writes() == []
