"""Profiles, API key storage and settings precedence (CAP-037).

Precedence (highest first): command-line flags → environment variables → selected profile →
organizationId in the config file. The API key is read from CAPELLA_API_KEY or the OS keychain and is
never written to any file.
"""

from __future__ import annotations

import contextlib
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from capellactl import DEFAULT_BASE_URL

KEYRING_SERVICE = "capellactl"
DEFAULT_PROFILE = "default"


# ------------------------------------------------------------------ locations
def home_dir(env: dict[str, str] | None = None) -> Path:
    e: dict[str, str] = dict(os.environ) if env is None else env
    if e.get("CAPELLACTL_HOME"):
        return Path(e["CAPELLACTL_HOME"])
    if sys.platform == "win32" and e.get("APPDATA"):
        return Path(e["APPDATA"]) / "capellactl"
    base = e.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "capellactl"


def profiles_path(env: dict[str, str] | None = None) -> Path:
    return home_dir(env) / "profiles.yaml"


# ------------------------------------------------------------------- profiles
def load_profiles(env: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    p = profiles_path(env)
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return dict(data.get("profiles") or {})


def save_profiles(profiles: dict[str, dict[str, Any]], env: dict[str, str] | None = None) -> Path:
    p = profiles_path(env)
    p.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        os.chmod(p.parent, 0o700)
    text = yaml.safe_dump({"profiles": profiles}, sort_keys=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    with contextlib.suppress(OSError):
        os.chmod(p, 0o600)
    return p


# ------------------------------------------------------------------- keychain
def keychain_available() -> bool:
    try:
        import keyring
        from keyring.backends import fail
    except Exception:  # noqa: BLE001
        return False
    kr = keyring.get_keyring()
    if isinstance(kr, fail.Keyring):
        return False
    try:
        return float(getattr(kr, "priority", 1)) > 0
    except Exception:  # noqa: BLE001
        return True


def keychain_get(profile: str) -> str | None:
    if not keychain_available():
        return None
    import keyring

    try:
        return keyring.get_password(KEYRING_SERVICE, profile)
    except Exception:  # noqa: BLE001 - a broken keychain must not break the command
        return None


def keychain_set(profile: str, api_key: str) -> None:
    import keyring

    keyring.set_password(KEYRING_SERVICE, profile, api_key)


def keychain_delete(profile: str) -> bool:
    if not keychain_available():
        return False
    import keyring
    from keyring.errors import PasswordDeleteError

    try:
        keyring.delete_password(KEYRING_SERVICE, profile)
        return True
    except PasswordDeleteError:
        return False


# ------------------------------------------------------------------- settings
@dataclass
class Value:
    value: str | None
    source: str

    def __bool__(self) -> bool:
        return bool(self.value)


@dataclass
class Settings:
    profile: str
    api_key: Value
    org_id: Value
    base_url: Value
    config_file: Value
    warnings: list[str] = field(default_factory=list)

    def rows(self) -> list[tuple[str, str, str]]:
        def mask(v: str | None) -> str:
            return f"••••{v[-4:]}" if v else "(not set)"

        return [
            ("profile", self.profile, "--profile / CAPELLACTL_PROFILE / default"),
            ("api key", mask(self.api_key.value), self.api_key.source),
            ("organization", self.org_id.value or "(not set)", self.org_id.source),
            ("API base URL", self.base_url.value or DEFAULT_BASE_URL, self.base_url.source),
            ("config file", self.config_file.value or "(not found)", self.config_file.source),
        ]


class ConfigDiscoveryError(Exception):
    pass


def discover_config_file(
    flag: str | None, env: dict[str, str], profile: dict[str, Any], cwd: Path | None = None
) -> Value:
    """--config → CAPELLACTL_CONFIG → profile configFile → ./capella.yaml → ./capella.yml (CAP-037 AC5)."""
    if flag:
        return Value(flag, "--config")
    if env.get("CAPELLACTL_CONFIG"):
        return Value(env["CAPELLACTL_CONFIG"], "CAPELLACTL_CONFIG")
    if profile.get("configFile"):
        return Value(str(profile["configFile"]), "profile")
    cwd = cwd or Path.cwd()
    yaml_p, yml_p = cwd / "capella.yaml", cwd / "capella.yml"
    if yaml_p.exists() and yml_p.exists():
        raise ConfigDiscoveryError("both capella.yaml and capella.yml found; pass --config")
    if yml_p.exists():
        return Value("capella.yml", "./capella.yml")
    return Value("capella.yaml", "default")


def resolve_settings(
    config_flag: str | None = None,
    profile_flag: str | None = None,
    env: dict[str, str] | None = None,
    file_org_id: str | None = None,
    cwd: Path | None = None,
) -> Settings:
    env = dict(os.environ) if env is None else env
    warnings: list[str] = []
    profile_name = profile_flag or env.get("CAPELLACTL_PROFILE") or DEFAULT_PROFILE
    profiles = load_profiles(env)
    profile = profiles.get(profile_name, {})
    if profile_flag and profile_name not in profiles:
        warnings.append(f"profile '{profile_name}' not found; run 'capellactl configure --profile {profile_name}'")

    # API key
    if env.get("CAPELLA_API_KEY"):
        api_key = Value(env["CAPELLA_API_KEY"], "CAPELLA_API_KEY")
    elif env.get("BEARER_TOKEN"):
        api_key = Value(env["BEARER_TOKEN"], "BEARER_TOKEN (deprecated)")
        warnings.append("BEARER_TOKEN is deprecated; use CAPELLA_API_KEY or 'capellactl configure'")
    else:
        key = keychain_get(profile_name) if profile_name in profiles else None
        api_key = Value(key, f"keychain (profile {profile_name})") if key else Value(None, "not set")

    # Organization
    if env.get("CAPELLA_ORG_ID"):
        org = Value(env["CAPELLA_ORG_ID"], "CAPELLA_ORG_ID")
    elif env.get("ORG_ID"):
        org = Value(env["ORG_ID"], "ORG_ID (deprecated)")
        warnings.append("ORG_ID is deprecated; use CAPELLA_ORG_ID or 'capellactl configure'")
    elif profile.get("organizationId"):
        org = Value(str(profile["organizationId"]), f"profile {profile_name}")
    elif file_org_id:
        org = Value(file_org_id, "config file")
    else:
        org = Value(None, "not set")

    # Base URL
    if env.get("CAPELLA_API_BASE_URL"):
        base = Value(env["CAPELLA_API_BASE_URL"], "CAPELLA_API_BASE_URL")
    elif env.get("API_BASE_URL"):
        base = Value(env["API_BASE_URL"], "API_BASE_URL (deprecated)")
        warnings.append("API_BASE_URL is deprecated; use CAPELLA_API_BASE_URL")
    elif profile.get("apiBaseUrl"):
        base = Value(str(profile["apiBaseUrl"]), f"profile {profile_name}")
    else:
        base = Value(DEFAULT_BASE_URL, "default")

    cfg = discover_config_file(config_flag, env, profile, cwd)
    return Settings(profile_name, api_key, org, base, cfg, warnings)
