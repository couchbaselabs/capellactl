#!/usr/bin/env python3
"""Fail when a secret value appears in a CI log (CAP-032 AC4; the canary check of CAP-008 over a whole run).

Usage: python scripts/scan-log-secrets.py FILE... [--env NAME]... [--secrets-dir DIR]... [--value-file FILE]...

The secrets are the values of the named environment variables (the API key), every `password` saved under
--secrets-dir (generated credential passwords, `*.json`) and the contents of each --value-file. A value is also
looked for JSON-escaped and URL-encoded. Only the file, line and secret's source are printed, never the value.
Exit 0 when the files are clean, 1 when a secret was found, 2 when there was nothing to check for (a missing
variable must not turn the check into a silent pass).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote, quote_plus

MIN_LENGTH = 8  # shorter values would match ordinary words


def variants(value: str) -> set[str]:
    return {value, json.dumps(value)[1:-1], quote(value, safe=""), quote_plus(value)}


def secrets_in_dir(d: Path) -> dict[str, str]:
    """`password` fields of the JSON files under d, keyed by where they came from."""
    found: dict[str, str] = {}
    for f in sorted(d.rglob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("password"), str):
            found[f"password in {f.name}"] = data["password"]
    return found


def scan(texts: dict[str, str], secrets: dict[str, str]) -> list[tuple[str, int, str]]:
    """(file, line number, secret source) for each line holding a secret."""
    hits = []
    for name, text in texts.items():
        for n, line in enumerate(text.splitlines(), 1):
            for label, value in secrets.items():
                if any(v in line for v in variants(value)):
                    hits.append((name, n, label))
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--env", action="append", default=[], metavar="NAME", help="environment variable holding a secret")
    ap.add_argument("--secrets-dir", action="append", default=[], type=Path, metavar="DIR")
    ap.add_argument("--value-file", action="append", default=[], type=Path, metavar="FILE")
    a = ap.parse_args(argv)
    secrets: dict[str, str] = {}
    for name in a.env:
        value = os.environ.get(name, "")
        if not value:
            print(f"scan-log-secrets: {name} is not set", file=sys.stderr)
            return 2
        secrets[f"${name}"] = value
    for d in a.secrets_dir:
        if d.is_dir():
            secrets.update(secrets_in_dir(d))
    for f in a.value_file:
        secrets[f"contents of {f.name}"] = f.read_text(encoding="utf-8").strip()
    short = [k for k, v in secrets.items() if len(v) < MIN_LENGTH]
    for k in short:
        print(f"scan-log-secrets: not checking {k}: shorter than {MIN_LENGTH} characters", file=sys.stderr)
        del secrets[k]
    if not secrets:
        print("scan-log-secrets: no secret values to check for", file=sys.stderr)
        return 2
    texts = {str(f): f.read_text(encoding="utf-8", errors="replace") for f in a.files if f.is_file()}
    missing = [str(f) for f in a.files if not f.is_file()]
    if missing:
        print(f"scan-log-secrets: no such file: {', '.join(missing)}", file=sys.stderr)
        return 2
    hits = scan(texts, secrets)
    for name, n, label in hits:
        print(f"{name}:{n}: contains {label}")
    if hits:
        print(f"FAILED: {len(hits)} line(s) contain a secret", file=sys.stderr)
        return 1
    print(f"no secrets in {len(texts)} file(s); {len(secrets)} secret value(s) checked")
    return 0


if __name__ == "__main__":
    sys.exit(main())
