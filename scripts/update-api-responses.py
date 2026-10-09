#!/usr/bin/env python3
"""Snapshot the documented success responses of every endpoint capellactl calls (CAP-004 AC6).

Usage: python3 scripts/update-api-responses.py [--spec FILE_OR_URL]

Reads the Capella Management API v4.0 OpenAPI spec (default: the published one) and writes
docs/api/management-api-v4.0-responses.json: for each operation in capellactl.api.endpoints.INVENTORY, the 2xx
status codes and their JSON schemas with every $ref resolved. tests/unit/fakes/test_fake_parity.py checks the fake
Capella's responses against it, offline: no Capella organization is ever called.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from capellactl.api.endpoints import INVENTORY  # noqa: E402

SPEC_URL = "https://docs.couchbase.com/cloud/management-api-reference/_attachments/openapi.external.generated.yaml"
OUT = ROOT / "docs" / "api" / "management-api-v4.0-responses.json"
KEEP = {"type", "properties", "required", "items", "enum", "allOf", "oneOf", "anyOf", "additionalProperties",
        "nullable", "format"}


def _norm(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def _resolve(node: Any, spec: dict[str, Any], seen: tuple[str, ...] = ()) -> Any:
    if isinstance(node, list):
        return [_resolve(n, spec, seen) for n in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if ref:
        if ref in seen:  # recursive schema: stop here
            return {}
        target: Any = spec
        for part in ref.lstrip("#/").split("/"):
            target = target[part]
        return _resolve(target, spec, (*seen, ref))
    out = {}
    for k, v in node.items():
        if k == "properties":
            out[k] = {name: _resolve(s, spec, seen) for name, s in v.items()}
        elif k in KEEP:
            out[k] = _resolve(v, spec, seen)
    return out


def load_spec(source: str) -> dict[str, Any]:
    if re.match(r"https?://", source):
        with urllib.request.urlopen(source, timeout=60) as r:  # noqa: S310 - the published spec
            text = r.read().decode("utf-8")
    else:
        text = Path(source).read_text(encoding="utf-8")
    return dict(yaml.safe_load(text))


def build(spec: dict[str, Any], source: str) -> dict[str, Any]:
    by_path = {_norm(p): ops for p, ops in spec["paths"].items()}
    operations = []
    for method, template in INVENTORY:
        ops = by_path.get(_norm(template)) or {}
        op = ops.get(method.lower())
        if op is None:
            operations.append({"method": method, "path": template, "documented": False})
            continue
        responses = {}
        for code, resp in (op.get("responses") or {}).items():
            if not str(code).startswith("2"):
                continue
            while "$ref" in resp:  # a shared response object
                target: Any = spec
                for part in resp["$ref"].lstrip("#/").split("/"):
                    target = target[part]
                resp = target
            media = (resp.get("content") or {}).get("application/json") or {}
            responses[str(code)] = _resolve(media["schema"], spec) if media.get("schema") else None
        operations.append({"method": method, "path": template, "documented": True,
                           "summary": op.get("summary", ""), "responses": responses})
    return {"source": source, "apiVersion": spec.get("info", {}).get("version"), "retrieved": date.today().isoformat(),
            "operations": operations}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--spec", default=SPEC_URL, help="OpenAPI spec file or URL (default: the published spec)")
    args = ap.parse_args()
    data = build(load_spec(args.spec), SPEC_URL if args.spec == SPEC_URL else args.spec)
    missing = [f"{o['method']} {o['path']}" for o in data["operations"] if not o["documented"]]
    OUT.write_text(json.dumps(data, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"written: {OUT.relative_to(ROOT)} ({len(data['operations'])} operations)")
    if missing:
        print("not in the spec:\n  " + "\n  ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
