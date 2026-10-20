"""CAP-027: database credentials with basic access, through plan/apply."""
from __future__ import annotations

import json
import os
import stat

import pytest

from tests.conftest import MINIMAL, assert_no_secret, seed_healthy
from tests.scenario.helpers import FULL, ORDERS_APP, ORDERS_BUCKET, ORDERS_PW, USERS, header, seed_user

PW_ENV = {"ORDERS_APP_PASSWORD": ORDERS_PW}
ACCESS = [{"privileges": ["data_reader", "data_writer"],
           "resources": {"buckets": [{"name": "orders", "scopes": [{"name": "inventory",
                                                                     "collections": ["items", "suppliers"]}]}]}}]


@pytest.fixture
def cluster(fake):
    pid, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=100)
    fake.seed_scope(cid, "orders", "inventory", {"items": 0, "suppliers": 0})  # as ORDERS_BUCKET declares
    return pid, cid


def _user_writes(fake):
    return [c for c in fake.writes() if "/users" in c.path]


@pytest.mark.story("CAP-027", "AC1")
def test_credential_ac1_create_supplied_password(fake, run, write_config, cluster):
    pid, cid = cluster
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP)
    r = run("plan", extra_env=PW_ENV)
    assert r.exit_code == 0, r.output
    assert "  + credential nova-dev-01/orders_app  read+write · orders/inventory/{items,suppliers}" in r.output
    a = run("--auto-approve", "apply", extra_env=PW_ENV)
    assert a.exit_code == 0, a.output
    writes = _user_writes(fake)
    assert [(c.method, c.path) for c in writes] == [("POST", USERS.format(pid=pid, cid=cid))]
    assert writes[0].body == {"name": "orders_app", "credentialType": "basic", "access": ACCESS, "password": ORDERS_PW}
    assert_no_secret(r.output + a.output, ORDERS_PW)


@pytest.mark.story("CAP-027", "AC2")
def test_credential_ac2_generated_password_saved(fake, run, write_config, cluster, tmp_path):
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP.replace("        password: ${ORDERS_APP_PASSWORD}\n", ""))
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    (post,) = _user_writes(fake)
    assert "password" not in post.body
    saved = tmp_path / ".capellactl" / "credentials" / "nova-dev-01.orders_app.json"
    data = json.loads(saved.read_text(encoding="utf-8"))
    generated = next(iter(fake.users.values()))["_password"]
    assert data["password"] == generated and data["name"] == "orders_app" and data["cluster"] == "nova-dev-01"
    if os.name == "posix":
        assert stat.S_IMODE(saved.stat().st_mode) == 0o600
    line = next(x for x in r.output.splitlines() if x.startswith("password saved to "))
    assert line.endswith(os.path.join(".capellactl", "credentials", "nova-dev-01.orders_app.json"))
    assert_no_secret(r.output, generated)


@pytest.mark.story("CAP-027", "AC2")
def test_credential_ac2_existing_secret_file_blocks_create(fake, run, write_config, cluster, tmp_path):
    """CAP-008 AC3: the file is checked before the POST, so a create never happens when it cannot be saved."""
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP.replace("        password: ${ORDERS_APP_PASSWORD}\n", ""))
    d = tmp_path / ".capellactl" / "credentials"
    d.mkdir(parents=True)
    (d / "nova-dev-01.orders_app.json").write_text("{}", encoding="utf-8")
    r = run("--auto-approve", "apply")
    assert r.exit_code == 1 and "refusing to overwrite" in r.output
    assert _user_writes(fake) == []


@pytest.mark.story("CAP-027", "AC4")
def test_credential_ac4_update_access_without_password(fake, run, write_config, cluster):
    pid, cid = cluster
    uid = seed_user(fake, cid, "orders_app", [{"privileges": ["data_reader"],
                                               "resources": {"buckets": [{"name": "orders",
                                                                          "scopes": [{"name": "inventory"}]}]}}])
    cfg = ORDERS_APP.replace("                      collections: [items, suppliers]\n", "")
    write_config(MINIMAL + ORDERS_BUCKET + cfg)
    r = run("plan", extra_env=PW_ENV)
    assert r.exit_code == 0, r.output
    assert "  ~ credential nova-dev-01/orders_app" in r.output
    assert '      orders/inventory:  "read" → "read+write"' in r.output
    a = run("--auto-approve", "apply", extra_env=PW_ENV)
    assert a.exit_code == 0, a.output
    (put,) = _user_writes(fake)
    assert (put.method, put.path) == ("PUT", USERS.format(pid=pid, cid=cid) + f"/{uid}")
    assert put.body == {"access": [{"privileges": ["data_reader", "data_writer"],
                                    "resources": {"buckets": [{"name": "orders", "scopes": [{"name": "inventory"}]}]}}]}
    assert header(put, "If-Match") == "1"
    assert fake.users[uid]["_password"] == "Old!Passw0rd-xyz"


@pytest.mark.story("CAP-027", "AC5")
def test_credential_ac5_all_buckets_warning(fake, run, write_config, cluster):
    write_config(MINIMAL + ORDERS_BUCKET + "    databaseCredentials:\n      - name: ops_ro\n"
                 "        access:\n          - privileges: [read]\n")
    v = run("validate")
    assert v.exit_code == 0, v.output
    assert "warning: clusters[0].databaseCredentials[0].access[0]: grants access to ALL buckets" in v.output
    r = run("plan")
    plan_line = next(line for line in r.output.splitlines() if "credential nova-dev-01/ops_ro" in line)
    assert plan_line.endswith("(all buckets)")


@pytest.mark.story("CAP-027", "AC6")
def test_credential_ac6_existing_advanced_blocked(fake, run, write_config, cluster):
    _, cid = cluster
    seed_user(fake, cid, "orders_app", [], userRoles=[{"name": "admin"}])
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP)
    r = run("plan", extra_env=PW_ENV)
    assert r.exit_code == 4, r.output
    assert "  ! credential nova-dev-01/orders_app  an advanced credential with this name exists in Capella" in r.output
    a = run("--auto-approve", "apply", extra_env=PW_ENV)
    assert a.exit_code == 4 and _user_writes(fake) == []


@pytest.mark.story("CAP-027", "AC7")
def test_credential_ac7_created_last(fake, run, write_config, stub_tree):
    seed_healthy(fake)
    write_config(FULL)
    r = run("--auto-approve", "apply")
    assert r.exit_code == 0, r.output
    paths = [c.path for c in fake.writes()]
    kinds = ["users" if p.endswith("/users") else p.rsplit("/", 1)[-1] for p in paths]
    assert "buckets" in kinds and "scopes" in kinds and "collections" in kinds
    assert kinds[-1] == "users" and kinds.count("users") == 1


@pytest.mark.story("CAP-027", "AC7")
def test_credential_ac7_after_bucket_in_real_tree(fake, run, write_config):
    seed_healthy(fake)
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP)
    r = run("--auto-approve", "apply", extra_env=PW_ENV)
    assert r.exit_code == 0, r.output
    assert [c.path.rsplit("/", 1)[-1] for c in fake.writes()] == ["buckets", "scopes", "collections", "collections",
                                                                   "users"]


@pytest.mark.story("CAP-027", "AC8")
def test_credential_ac8_rerun_zero_writes(fake, run, write_config, cluster):
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP)
    assert run("--auto-approve", "apply", extra_env=PW_ENV).exit_code == 0
    fake.reset_calls()
    r = run("--auto-approve", "apply", extra_env={"ORDERS_APP_PASSWORD": "Changed!Pw-123456"})
    assert r.exit_code == 0, r.output
    assert "No changes. Capella matches capella.yaml." in r.output
    assert fake.writes() == []
    assert run("plan", "--detailed-exitcode", extra_env=PW_ENV).exit_code == 0
