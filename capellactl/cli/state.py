"""Per-invocation application state: global flags, settings, config and API client."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from capellactl.api.client import CapellaClient
from capellactl.cli.console import err_inline, note, warning
from capellactl.cli.exit_codes import CliExit, ExitCode
from capellactl.config.loader import FIX_PROBLEMS, Config, ConfigError, load_config
from capellactl.config.settings import ConfigDiscoveryError, Settings, resolve_settings
from capellactl.engine.clock import get_clock
from capellactl.engine.context import RunContext


def parse_duration(text: str) -> timedelta:
    """'60m', '1h', '90s', '1h30m' or plain seconds."""
    t = text.strip().lower()
    if t.isdigit():
        return timedelta(seconds=int(t))
    parts = re.findall(r"(\d+)([hms])", t)
    if not parts or "".join(n + u for n, u in parts) != t:
        raise ValueError(f"invalid duration '{text}' (use for example 90s, 5m, 1h)")
    secs = sum(int(n) * {"h": 3600, "m": 60, "s": 1}[u] for n, u in parts)
    return timedelta(seconds=secs)


@dataclass
class AppState:
    config_flag: str | None = None
    profile_flag: str | None = None
    output: str = "text"
    log_level: str = "info"
    auto_approve: bool = False
    quiet: bool = False
    no_wait: bool = False
    timeout: timedelta = timedelta(minutes=60)
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    _warned: bool = False

    @property
    def json(self) -> bool:
        return self.output == "json"

    def settings(self, file_org: str | None = None) -> Settings:
        try:
            s = resolve_settings(self.config_flag, self.profile_flag, self.env, file_org)
        except ConfigDiscoveryError as exc:
            raise CliExit(ExitCode.CONFIG_INVALID, str(exc), topic="config",
                                                   action="Pass --config with the file to use, or remove one of the "
                                                          "files.") from None
        if not self._warned:
            for w in s.warnings:
                warning(w)
            self._warned = True
        return s

    def config_path(self) -> Path:
        return Path(str(self.settings().config_file.value))

    def load_config(self, warnings: str = "none") -> Config:
        """`warnings`: "all" prints each config warning (validate), "count" prints one line pointing to validate
        (plan, apply) and "none" prints nothing, so other commands are not buried in them."""
        path = self.config_path()
        try:
            cfg = load_config(path, env=self.env)
        except ConfigError as exc:
            topic = exc.issues[0].topic if exc.issues else "config"
            raise CliExit(ExitCode.CONFIG_INVALID, str(exc), topic=topic, action=FIX_PROBLEMS) from None
        for hint in cfg.hints:
            note(hint)
        if warnings == "all":
            for w in cfg.warnings:
                warning(w)
        elif warnings == "count" and cfg.warnings:
            n = len(cfg.warnings)
            warning(f"capella.yaml has {n} setting{'s' if n != 1 else ''} that may not be intended",
                    "Run 'capellactl validate' to see them.")
        return cfg

    def client(self, file_org: str | None = None, require_org: bool = True) -> CapellaClient:
        s = self.settings(file_org)
        if not s.api_key.value:
            raise CliExit(ExitCode.CONFIG_INVALID,
                          "no API key", topic="environment",
                          action="Set CAPELLA_API_KEY, or save the key with 'capellactl configure'.")
        if require_org and not s.org_id.value:
            raise CliExit(ExitCode.CONFIG_INVALID,
                          "no organization", topic="environment",
                          action="Set CAPELLA_ORG_ID, run 'capellactl configure', or set organizationId in "
                                 "capella.yaml.")
        return CapellaClient(str(s.api_key.value), s.org_id.value, str(s.base_url.value), clock=get_clock())

    def run_context(self, client: CapellaClient, config: Config | None) -> RunContext:
        def progress(msg: str) -> None:
            note(msg)

        return RunContext(client=client, config=config, clock=get_clock(), timeout=self.timeout,
                          no_wait=self.no_wait, progress=progress, progress_inline=err_inline,
                          warn=warning)
