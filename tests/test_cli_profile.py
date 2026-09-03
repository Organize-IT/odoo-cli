from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from odoocli.cli.app import app
from odoocli.config import load_profiles
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo

runner = CliRunner()


def invoke(cfg: Path, *args: str, env: dict[str, str] | None = None) -> Any:
    return runner.invoke(app, list(args), env={"ODOO_CONFIG": str(cfg), **(env or {})})


def test_profile_add_list_remove(tmp_path: Path) -> None:
    cfg = tmp_path / "c.toml"
    r = invoke(
        cfg,
        "profile",
        "add",
        "acme",
        "--url",
        "https://acme/",
        "--db",
        "d",
        "--login",
        "l",
        "--api-key",
        "k",
        "--allow-writes",
    )
    assert r.exit_code == 0, r.stderr
    assert load_profiles(cfg)["acme"] == {
        "url": "https://acme",
        "database": "d",
        "login": "l",
        "api_key": "k",
        "allow_writes": True,
        "allow_sensitive": False,
    }
    invoke(
        cfg,
        "profile",
        "add",
        "env",
        "--url",
        "https://e",
        "--db",
        "d",
        "--login",
        "l",
        "--api-key-env",
        "E_KEY",
    )
    out = invoke(cfg, "profile", "list").stdout
    listed = json.loads(out)
    assert [p["name"] for p in listed] == ["acme", "env"]
    assert listed[0]["key"] == "***" and listed[1]["key"] == "$E_KEY"
    assert '"k"' not in out
    assert invoke(cfg, "profile", "remove", "acme").exit_code == 0
    assert invoke(cfg, "profile", "remove", "acme").exit_code == 3
    assert list(load_profiles(cfg)) == ["env"]


def test_profile_add_requires_exactly_one_key(tmp_path: Path) -> None:
    cfg = tmp_path / "c.toml"
    base = ["profile", "add", "x", "--url", "u", "--db", "d", "--login", "l"]
    assert invoke(cfg, *base).exit_code == 2
    assert invoke(cfg, *base, "--api-key", "k", "--api-key-env", "E").exit_code == 2


def test_profile_add_with_test_and_profile_test(tmp_path: Path, fake_odoo: FakeOdoo) -> None:
    cfg = tmp_path / "c.toml"
    r = invoke(
        cfg,
        "profile",
        "add",
        "acme",
        "--url",
        BASE_URL,
        "--db",
        DB,
        "--login",
        LOGIN,
        "--api-key",
        KEY,
        "--test",
    )
    assert r.exit_code == 0 and json.loads(r.stdout)["uid"] == 7
    r = invoke(cfg, "profile", "test", "acme")
    assert r.exit_code == 0 and json.loads(r.stdout)["source"] == "profile:acme"


def test_profile_used_by_commands(tmp_path: Path, fake_odoo: FakeOdoo) -> None:
    cfg = tmp_path / "c.toml"
    invoke(
        cfg,
        "profile",
        "add",
        "acme",
        "--url",
        BASE_URL,
        "--db",
        DB,
        "--login",
        LOGIN,
        "--api-key",
        KEY,
    )
    fake_odoo.on("res.partner", "search_count", 3)
    assert invoke(cfg, "-p", "acme", "count", "res.partner").stdout.strip() == "3"
    env = {"ODOO_PROFILE": "acme"}
    assert invoke(cfg, "count", "res.partner", env=env).stdout.strip() == "3"


def test_profile_path(tmp_path: Path) -> None:
    cfg = tmp_path / "c.toml"
    assert invoke(cfg, "profile", "path").stdout.strip() == str(cfg)
