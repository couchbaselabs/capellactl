"""Shared helpers for scenario tests."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from tests.conftest import MINIMAL

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"

CHILDREN = """\
    allowedCidrs:
      - cidr: 203.0.113.10/32
        comment: Office VPN
    buckets:
      - name: events
        memoryAllocationInMb: 512
        scopes:
          - name: inventory
      - name: orders
        memoryAllocationInMb: 1024
        scopes:
          - name: billing
            collections:
              - name: invoices
    databaseCredentials:
      - name: orders_app
        access:
          - privileges: [data_reader, data_writer]
            resources: { buckets: [ { name: orders } ] }
"""
FULL = MINIMAL + CHILDREN


def validate_json(name: str, text: str) -> dict[str, Any]:
    data = json.loads(text)
    registry: Registry = Registry()
    for f in SCHEMAS.glob("*.json"):
        registry = registry.with_resource(f.name, Resource.from_contents(json.loads(f.read_text())))
    schema = json.loads((SCHEMAS / name).read_text())
    Draft202012Validator(schema, registry=registry).validate(data)
    return data  # type: ignore[no-any-return]


# ------------------------------------------------------------ database credentials (CAP-027/028/029/046)
ORDERS_BUCKET = """\
    buckets:
      - name: orders
        memoryAllocationInMb: 100
        scopes:
          - name: inventory
            collections:
              - name: items
              - name: suppliers
"""
ORDERS_APP = """\
    databaseCredentials:
      - name: orders_app
        password: ${ORDERS_APP_PASSWORD}
        access:
          - privileges: [data_reader, data_writer]
            resources:
              buckets:
                - name: orders
                  scopes:
                    - name: inventory
                      collections: [items, suppliers]
"""
ORDERS_PW = "S3cret!Orders-app-pw"
USERS = "/v4/organizations/org-1/projects/{pid}/clusters/{cid}/users"


def seed_user(fake: Any, cluster_id: str, name: str, access: list[dict[str, Any]] | None = None,
              password: str = "Old!Passw0rd-xyz", **extra: Any) -> str:
    """A database credential as Capella stores it (the password is kept only for assertions)."""
    i = f"u-seed-{len(fake.users) + 1}"
    fake.users[i] = {"id": i, "_cluster": cluster_id, "name": name, "access": access or [], "userRoles": None,
                     "_password": password, **extra}
    fake.versions[f"user:{i}"] = 1
    return i


def header(call: Any, name: str) -> str | None:
    return next((v for k, v in call.headers.items() if k.lower() == name.lower()), None)
