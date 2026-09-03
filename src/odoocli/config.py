"""Profiles file and connection resolution. The only library module allowed to read env."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

from odoocli.errors import OdooConnectionError

ENV_URL, ENV_DB, ENV_LOGIN, ENV_KEY = "ODOO_URL", "ODOO_DB", "ODOO_LOGIN", "ODOO_API_KEY"
ENV_REQUIRED = (ENV_URL, ENV_DB, ENV_LOGIN, ENV_KEY)
ENV_PROFILE = "ODOO_PROFILE"
ENV_CONFIG = "ODOO_CONFIG"
ENV_ALLOW_WRITES = "ODOO_ALLOW_WRITES"
ENV_ALLOW_SENSITIVE = "ODOO_ALLOW_SENSITIVE"
ENV_ASSUME_YES = "ODOO_ASSUME_YES"
ENV_VERIFY_SSL = "ODOO_VERIFY_SSL"

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}

NO_CONNECTION_HELP = (
    "No Odoo connection configured. Use one of:\n"
    "  1. odoo --profile NAME ... (or ODOO_PROFILE=NAME) after 'odoo profile add NAME ...'\n"
    "  2. environment: ODOO_URL, ODOO_DB, ODOO_LOGIN, ODOO_API_KEY\n"
    "  3. a profile named 'default' in the config file"
)


@dataclass(slots=True)
class Profile:
    name: str
    url: str
    database: str
    login: str
    api_key: str = field(repr=False)
    allow_writes: bool = False
    allow_sensitive: bool = False
    verify_ssl: bool = True
    source: str = "env"


def env_flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in _TRUE


def env_flag_default_true(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() not in _FALSE


def config_path(env: Mapping[str, str]) -> Path:
    if env.get(ENV_CONFIG):
        return Path(env[ENV_CONFIG]).expanduser()
    base = env.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "odoo-cli" / "config.toml"


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        tomli_w.dump(data, fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def load_profiles(path: Path) -> dict[str, dict[str, Any]]:
    profiles = _read(path).get("profiles", {})
    return {str(k): dict(v) for k, v in profiles.items() if isinstance(v, dict)}


def save_profile(path: Path, name: str, data: dict[str, Any]) -> None:
    doc = _read(path)
    profiles = doc.setdefault("profiles", {})
    profiles[name] = {k: v for k, v in data.items() if v is not None}
    _write(path, doc)


def remove_profile(path: Path, name: str) -> bool:
    doc = _read(path)
    profiles = doc.get("profiles", {})
    if name not in profiles:
        return False
    del profiles[name]
    _write(path, doc)
    return True


def profile_from_dict(name: str, data: Mapping[str, Any], env: Mapping[str, str]) -> Profile:
    missing = [k for k in ("url", "database", "login") if not data.get(k)]
    if missing:
        raise OdooConnectionError(
            f"Profile {name!r} is missing {', '.join(missing)}", code="invalid_profile"
        )
    api_key = data.get("api_key")
    key_env = data.get("api_key_env")
    if not api_key and key_env:
        api_key = env.get(str(key_env))
        if not api_key:
            raise OdooConnectionError(
                f"Profile {name!r} reads its key from ${key_env}, which is not set",
                code="invalid_profile",
            )
    if not api_key:
        raise OdooConnectionError(
            f"Profile {name!r} has neither api_key nor api_key_env", code="invalid_profile"
        )
    return Profile(
        name=name,
        url=str(data["url"]),
        database=str(data["database"]),
        login=str(data["login"]),
        api_key=str(api_key),
        allow_writes=bool(data.get("allow_writes", False)),
        allow_sensitive=bool(data.get("allow_sensitive", False)),
        verify_ssl=bool(data.get("verify_ssl", True)),
        source=f"profile:{name}",
    )


def _from_env(env: Mapping[str, str]) -> Profile:
    return Profile(
        name="env",
        url=env[ENV_URL],
        database=env[ENV_DB],
        login=env[ENV_LOGIN],
        api_key=env[ENV_KEY],
        allow_writes=env_flag(env, ENV_ALLOW_WRITES),
        allow_sensitive=env_flag(env, ENV_ALLOW_SENSITIVE),
        verify_ssl=env_flag_default_true(env, ENV_VERIFY_SSL),
        source="env",
    )


def resolve_profile(explicit: str | None, env: Mapping[str, str], path: Path) -> Profile:
    """--profile > ODOO_PROFILE > ODOO_* env > profile 'default'. Never prompts."""
    name = explicit or env.get(ENV_PROFILE) or None
    if name:
        profiles = load_profiles(path)
        if name not in profiles:
            raise OdooConnectionError(
                f"Profile {name!r} not found in {path}. Run 'odoo profile add {name} ...'",
                code="no_connection",
            )
        return profile_from_dict(name, profiles[name], env)

    present = [k for k in ENV_REQUIRED if env.get(k)]
    if present:
        missing = [k for k in ENV_REQUIRED if not env.get(k)]
        if missing:
            raise OdooConnectionError(
                f"Incomplete ODOO_* environment, missing: {', '.join(missing)}",
                code="no_connection",
            )
        return _from_env(env)

    profiles = load_profiles(path)
    if "default" in profiles:
        return profile_from_dict("default", profiles["default"], env)
    raise OdooConnectionError(NO_CONNECTION_HELP, code="no_connection")
