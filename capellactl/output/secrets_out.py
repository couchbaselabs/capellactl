"""Store passwords that Capella generates, which it returns only once (CAP-008 AC2–AC4)."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from capellactl.output.redact import redactor


class SecretFileExists(Exception):
    def __init__(self, path: Path) -> None:
        super().__init__(f"refusing to overwrite {path}; move it or pass --force-overwrite-secret")
        self.path = path


def secret_path(directory: str | Path, cluster: str, name: str) -> Path:
    return Path(directory) / f"{cluster}.{name}.json"


def preflight(directory: str | Path, cluster: str, name: str, force: bool = False) -> Path:
    """Run before creating the credential, so a create never happens when the secret cannot be saved."""
    p = secret_path(directory, cluster, name)
    if p.exists() and not force:
        raise SecretFileExists(p)
    return p


def write_generated_credential(
    directory: str | Path, cluster: str, name: str, cred_id: str, password: str, force: bool = False
) -> Path:
    redactor.register(password)
    d = Path(directory)
    d.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(d, 0o700)
    p = preflight(d, cluster, name, force)
    payload = {
        "cluster": cluster,
        "name": name,
        "id": cred_id,
        "password": password,
        "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(p, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    with contextlib.suppress(OSError):
        os.chmod(p, 0o600)
    return p


def write_rotated_credential(directory: str | Path, cluster: str, name: str, cred_id: str,
                             password: str) -> tuple[Path, Path | None]:
    """Rotation may replace the credential's own file; the previous one is kept as `.bak` (CAP-028 AC2).

    Returns (file, backup or None). Written before the password is sent, so a failed save never leaves
    Capella with a password nobody has; `restore_rotated_credential` undoes it when the send fails.
    """
    p = secret_path(directory, cluster, name)
    backup = None
    if p.exists():
        backup = p.with_name(p.name + ".bak")
        fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(p.read_text(encoding="utf-8"))
        with contextlib.suppress(OSError):
            os.chmod(backup, 0o600)
    return write_generated_credential(directory, cluster, name, cred_id, password, force=True), backup


def restore_rotated_credential(path: Path, backup: Path | None) -> None:
    if backup is not None and backup.exists():
        os.replace(backup, path)
    else:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def saved_message(path: str | Path) -> str:
    """The only thing printed about a generated password (CAP-008 AC2)."""
    return f"password saved to {path}"


def not_git_ignored(path: str | Path) -> bool:
    """True when `path` is inside a git work tree and not ignored (CAP-008 AC4)."""
    p = Path(path).resolve()
    probe = p if p.is_dir() else p.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    try:
        inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=probe,
                                capture_output=True, text=True, timeout=10, encoding="utf-8")
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        ignored = subprocess.run(["git", "check-ignore", "-q", str(p)], cwd=probe, capture_output=True, timeout=10)
        return ignored.returncode != 0
    except (OSError, subprocess.SubprocessError):
        return False


def git_warning(directory: str | Path) -> tuple[str, str] | None:
    """(what, action) when generated passwords could end up in Git (CAP-063)."""
    if not_git_ignored(directory):
        return f"{directory} is not git-ignored", "Add .capellactl/ to .gitignore so the saved password is never committed."
    return None
