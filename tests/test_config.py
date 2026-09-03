from pathlib import Path

import pytest

from odoocli.config import (
    config_path,
    load_profiles,
    remove_profile,
    resolve_profile,
    save_profile,
)
from odoocli.errors import OdooConnectionError

ENV_FULL = {"ODOO_URL": "https://a.b", "ODOO_DB": "db", "ODOO_LOGIN": "u", "ODOO_API_KEY": "k"}


def test_config_path_precedence(tmp_path: Path) -> None:
    assert config_path({"ODOO_CONFIG": "/x/y.toml"}) == Path("/x/y.toml")
    assert config_path({"XDG_CONFIG_HOME": str(tmp_path)}) == tmp_path / "odoo-cli" / "config.toml"
    assert config_path({}).name == "config.toml"


def test_save_load_remove_roundtrip_with_permissions(tmp_path: Path) -> None:
    path = tmp_path / "cfg" / "config.toml"
    save_profile(path, "acme", {"url": "https://a", "database": "d", "login": "l", "api_key": "k"})
    save_profile(
        path,
        "other",
        {"url": "https://o", "database": "d", "login": "l", "api_key_env": "OTHER_KEY"},
    )
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    profiles = load_profiles(path)
    assert set(profiles) == {"acme", "other"}
    assert remove_profile(path, "acme") is True
    assert remove_profile(path, "acme") is False
    assert set(load_profiles(path)) == {"other"}


def test_resolve_env_when_no_profile_requested(tmp_path: Path) -> None:
    p = resolve_profile(None, ENV_FULL, tmp_path / "none.toml")
    assert (p.url, p.database, p.login, p.api_key, p.source) == (
        "https://a.b",
        "db",
        "u",
        "k",
        "env",
    )
    assert p.allow_writes is False
    p2 = resolve_profile(None, {**ENV_FULL, "ODOO_ALLOW_WRITES": "yes"}, tmp_path / "none.toml")
    assert p2.allow_writes is True


def test_resolve_partial_env_lists_missing(tmp_path: Path) -> None:
    env = {"ODOO_URL": "https://a.b", "ODOO_DB": "db", "ODOO_LOGIN": "u"}
    with pytest.raises(OdooConnectionError, match="ODOO_API_KEY"):
        resolve_profile(None, env, tmp_path / "n.toml")


def test_resolve_explicit_profile_beats_env(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_profile(
        path,
        "acme",
        {
            "url": "https://acme",
            "database": "d",
            "login": "l",
            "api_key_env": "ACME_KEY",
            "allow_writes": True,
        },
    )
    p = resolve_profile("acme", {**ENV_FULL, "ACME_KEY": "from-env"}, path)
    assert (p.url, p.api_key, p.allow_writes, p.source) == (
        "https://acme",
        "from-env",
        True,
        "profile:acme",
    )


def test_resolve_odoo_profile_env_var(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_profile(
        path, "acme", {"url": "https://acme", "database": "d", "login": "l", "api_key": "k"}
    )
    assert resolve_profile(None, {"ODOO_PROFILE": "acme"}, path).source == "profile:acme"


def test_resolve_default_profile_last(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_profile(
        path, "default", {"url": "https://d", "database": "d", "login": "l", "api_key": "k"}
    )
    assert resolve_profile(None, {}, path).url == "https://d"


def test_resolve_nothing_explains(tmp_path: Path) -> None:
    with pytest.raises(OdooConnectionError) as ei:
        resolve_profile(None, {}, tmp_path / "config.toml")
    assert ei.value.code == "no_connection"
    assert "--profile" in ei.value.message and "ODOO_URL" in ei.value.message


def test_unknown_profile(tmp_path: Path) -> None:
    with pytest.raises(OdooConnectionError, match="acme"):
        resolve_profile("acme", {}, tmp_path / "config.toml")


def test_profile_missing_api_key_env(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    save_profile(
        path, "acme", {"url": "https://acme", "database": "d", "login": "l", "api_key_env": "NOPE"}
    )
    with pytest.raises(OdooConnectionError, match="NOPE"):
        resolve_profile("acme", {}, path)
