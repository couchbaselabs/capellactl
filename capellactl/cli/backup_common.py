"""Helpers shared by `cluster backup` (CAP-056, CAP-057) and `bucket backup` (CAP-058, CAP-059)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from capellactl.cli.console import err_inline, note
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.engine.clock import format_duration
from capellactl.resources.cluster import is_free

# Capella documents these statuses as free text; the values below are the ones it uses for done and failed.
DONE = {"complete", "completed", "succeeded", "success", "done", "ready"}
FAILED = {"failed", "error", "cancelled", "canceled", "expired"}
FREE_NO_BACKUPS = "free-tier clusters have no backups; create a provisioned cluster for data that needs them"


def refuse_free(cluster: dict[str, Any]) -> None:
    if is_free(cluster):
        raise CliExit(ExitCode.BLOCKED, "free-tier clusters have no backups", topic="backup",
                                        action="Create a provisioned cluster for data that needs backups "
                                               "('capellactl cluster create NAME').")


def when(value: Any) -> str:
    """'2026-10-28T02:00:00Z' → '2026-10-28 02:00' (UTC); '' when absent."""
    if not value:
        return ""
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if t.tzinfo is not None:
        t = t.astimezone(timezone.utc)
    return t.strftime("%Y-%m-%d %H:%M")


def size_text(n_bytes: Any) -> str:
    """Bytes → '42 GB', '120 MB'."""
    if n_bytes in (None, ""):
        return ""
    n = float(n_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" or n >= 10 else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def parse_hours(text: str, flag: str) -> int:
    """'168', '168h' or '7d' → hours (exit 3 otherwise)."""
    m = re.fullmatch(r"\s*(\d+)\s*([hd]?)\s*", str(text).lower())
    if not m or int(m.group(1)) == 0:
        raise CliExit(ExitCode.CONFIG_INVALID, f"{flag} takes hours or days, for example 168, 168h or 7d (got "
                                               f"'{text}')", topic="backup",
                                               action="Give a number of hours, or days with d, for example 168, "
                                                      "168h or 7d.")
    return int(m.group(1)) * (24 if m.group(2) == "d" else 1)


def progress(label: str) -> dict[str, Any]:
    """on_state/on_tick for wait_for_status, shown like a cluster wait (console.wait_progress): `  LABEL: STATUS
    (time) ....`, a dot every 30s while it runs, and the final status on a line of its own."""
    def on_state(state: str, elapsed: float) -> None:
        line = f"  {label}: {state} ({format_duration(elapsed)})"
        if state.lower() in DONE | FAILED:
            note(line)
        else:
            err_inline(line + " ", start=True)
    return {"on_state": on_state, "on_tick": lambda: err_inline(".")}
