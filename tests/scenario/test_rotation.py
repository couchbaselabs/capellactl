"""CAP-028: password rotation, only when asked."""
from __future__ import annotations

import json
import os
import stat

import pytest

from capellactl.cli import console
from capellactl.output.password_gen import meets_rules
from tests.conftest import MINIMAL, assert_no_secret, seed_healthy
from tests.scenario.helpers import ORDERS_APP, ORDERS_BUCKET, ORDERS_PW, USERS, header, seed_user

PW_ENV = {"ORDERS_APP_PASSWORD": ORDERS_PW}
ACCESS = [{"privileges": ["data_reader", "data_writer"],
           "resources": {"buckets": [{"name": "orders", "scopes": [{"name": "inventory",
                                                                     "collections": ["items", "suppliers"]}]}]}}]
NO_PW = ORDERS_APP.replace("        password: ${ORDERS_APP_PASSWORD}\n", "")


@pytest.fixture
def cluster(fake):
    pid, cid = seed_healthy(fake)
    fake.seed_bucket(cid, "orders", memoryAllocationInMb=100)
    fake.seed_scope(cid, "orders", "inventory", {"items": 0, "suppliers": 0})  # as ORDERS_BUCKET declares
    return pid, cid


def _user_writes(fake):
    return [c for c in fake.writes() if "/users" in c.path]


@pytest.mark.story("CAP-028", "AC1")
def test_rotation_ac1_from_configured_secret(fake, run, write_config, cluster):
    pid, cid = cluster
    uid = seed_user(fake, cid, "orders_app", ACCESS)
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP)
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app", "--rotate-password", extra_env=PW_ENV)
    assert r.exit_code == 0, r.output
    (put,) = _user_writes(fake)
    assert (put.method, put.path) == ("PUT", USERS.format(pid=pid, cid=cid) + f"/{uid}")
    assert put.body["password"] == ORDERS_PW and put.body["access"]  # access always sent: Capella clears it otherwise
    assert header(put, "If-Match") == "1"
    assert "password rotated for orders_app" in r.output
    assert fake.users[uid]["_password"] == ORDERS_PW
    assert_no_secret(r.output, ORDERS_PW)


@pytest.mark.story("CAP-028", "AC2")
def test_rotation_ac2_generated_saved_with_backup(fake, run, write_config, cluster, tmp_path):
    _, cid = cluster
    uid = seed_user(fake, cid, "orders_app", ACCESS)
    d = tmp_path / ".capellactl" / "credentials"
    d.mkdir(parents=True)
    old = d / "nova-dev-01.orders_app.json"
    old.write_text(json.dumps({"password": "Old!Passw0rd-xyz"}))
    write_config(MINIMAL + ORDERS_BUCKET + NO_PW)
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app", "--rotate-password")
    assert r.exit_code == 0, r.output
    new = fake.users[uid]["_password"]
    assert new != "Old!Passw0rd-xyz" and len(new) == 32 and meets_rules(new)
    assert json.loads(old.read_text())["password"] == new
    bak = d / "nova-dev-01.orders_app.json.bak"
    assert json.loads(bak.read_text()) == {"password": "Old!Passw0rd-xyz"}
    if os.name == "posix":
        assert stat.S_IMODE(bak.stat().st_mode) == 0o600 and stat.S_IMODE(old.stat().st_mode) == 0o600
    assert "password rotated for orders_app" in r.output and "password saved to" in r.output
    assert_no_secret(r.output, new)


@pytest.mark.story("CAP-028", "AC2")
def test_rotation_ac2_failed_send_restores_file(fake, run, write_config, cluster, tmp_path):
    _, cid = cluster
    seed_user(fake, cid, "orders_app", ACCESS)
    d = tmp_path / ".capellactl" / "credentials"
    d.mkdir(parents=True)
    old = d / "nova-dev-01.orders_app.json"
    old.write_text('{"password": "Old!Passw0rd-xyz"}')
    write_config(MINIMAL + ORDERS_BUCKET + NO_PW)
    fake.fail_next("PUT", "*/users/*", status=400)
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app", "--rotate-password")
    assert r.exit_code == 1, r.output
    assert old.read_text() == '{"password": "Old!Passw0rd-xyz"}'
    assert not (d / "nova-dev-01.orders_app.json.bak").exists()


@pytest.mark.story("CAP-028", "AC4")
def test_rotation_ac4_no_implicit_rotation(fake, run, write_config, cluster):
    _, cid = cluster
    seed_user(fake, cid, "orders_app", ACCESS)
    seed_user(fake, cid, "reporting", ACCESS)
    second = ORDERS_APP.split("\n", 1)[1].replace("orders_app", "reporting").replace("ORDERS_APP", "REPORTING")
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP + second)
    env = {**PW_ENV, "REPORTING_PASSWORD": "Rep0rting!Passw0rd"}
    assert run("--auto-approve", "apply", extra_env=env).exit_code == 0
    r = run("--auto-approve", "apply", extra_env={"ORDERS_APP_PASSWORD": "Changed!Pw-123456",
                                                  "REPORTING_PASSWORD": "Changed!Pw-654321"})
    assert r.exit_code == 0, r.output
    assert fake.writes() == []
    assert r.output.count("note: passwords are not compared; use --rotate-password to change them") == 1


@pytest.mark.story("CAP-028", "AC5")
def test_rotation_ac5_bulk_with_target(fake, run, write_config, cluster, monkeypatch):
    _, cid = cluster
    names = ["app_a", "app_b", "app_c"]
    for n in names:
        seed_user(fake, cid, n, ACCESS)
    creds = "".join(ORDERS_APP.split("\n", 1)[1].replace("orders_app", n).replace("ORDERS_APP", n.upper())
                    for n in names)
    write_config(MINIMAL + ORDERS_BUCKET + "    databaseCredentials:\n" + creds)
    env = {f"{n.upper()}_PASSWORD": f"Rotated!{n}-Pw1" for n in names}
    monkeypatch.setattr(console, "is_interactive", lambda: True)
    r = run("apply", "--rotate-passwords", input="y\n", extra_env=env)
    assert r.exit_code == 0, r.output
    listed = r.output.split("Passwords to rotate:\n", 1)[1].splitlines()[:3]
    assert listed == [f"  nova-dev-01/{n}" for n in names]
    assert [c.body["password"] for c in _user_writes(fake)] == [env[f"{n.upper()}_PASSWORD"] for n in names]
    assert all(c.body["access"] for c in _user_writes(fake))
    fake.reset_calls()
    r = run("--auto-approve", "apply", "--rotate-passwords", "--target", "credential/nova-dev-01/app_b", extra_env=env)
    assert r.exit_code == 0, r.output
    assert [c.body["password"] for c in _user_writes(fake)] == ["Rotated!app_b-Pw1"]


@pytest.mark.story("CAP-028", "AC6")
def test_rotation_ac6_missing_credential_created(fake, run, write_config, cluster):
    write_config(MINIMAL + ORDERS_BUCKET + ORDERS_APP)
    r = run("--auto-approve", "credential", "update", "nova-dev-01", "orders_app", "--rotate-password", extra_env=PW_ENV)
    assert r.exit_code == 0, r.output
    assert [c.method for c in _user_writes(fake)] == ["POST"]
    assert _user_writes(fake)[0].body["password"] == ORDERS_PW
