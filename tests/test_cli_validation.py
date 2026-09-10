from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from odoocli.cli.app import app
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo
from tests.test_schema import serve_schema

ENV = {
    "ODOO_URL": BASE_URL,
    "ODOO_DB": DB,
    "ODOO_LOGIN": LOGIN,
    "ODOO_API_KEY": KEY,
    "ODOO_CONFIG": "/nonexistent/c.toml",
}
RW = {**ENV, "ODOO_ALLOW_WRITES": "1"}
runner = CliRunner()


def invoke(*args: str, env: dict[str, str] | None = None) -> Any:
    return runner.invoke(app, list(args), env=env or ENV)


def methods(fake: FakeOdoo) -> list[str]:
    return [call[1] for call in fake.calls]


def test_typo_in_a_condition_is_caught_before_the_call(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    r = invoke("search", "res.partner", "-w", "mobil=+32")
    assert r.exit_code == 2
    error = json.loads(r.stderr)["error"]
    assert error["code"] == "unknown_field"
    assert "Did you mean 'mobile'?" in error["message"]
    assert "search_read" not in methods(fake_odoo)


def test_typo_in_a_requested_field_is_caught(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    r = invoke("search", "res.partner", "--fields", "name,emial")
    assert r.exit_code == 2
    assert json.loads(r.stderr)["error"]["code"] == "unknown_field"
    assert "search_read" not in methods(fake_odoo)


def test_typo_across_a_relation_names_the_related_model(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    r = invoke("search", "res.partner", "-w", "country_id.cod=BE")
    assert r.exit_code == 2
    error = json.loads(r.stderr)["error"]
    assert error["message"].startswith("res.country has no field 'cod'")


def test_valid_query_still_runs(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    fake_odoo.on("res.partner", "search_read", [{"id": 1, "name": "Acme"}])
    r = invoke("search", "res.partner", "-w", "name~acme", "--fields", "name")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == [{"id": 1, "name": "Acme"}]


def test_no_validate_skips_the_schema_entirely(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    fake_odoo.on("res.partner", "search_read", [])
    r = invoke("search", "res.partner", "-w", "mobil=+32", "--no-validate")
    assert r.exit_code == 0, r.stderr
    assert methods(fake_odoo) == ["search_read"]


def test_no_validate_can_come_from_the_environment(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    fake_odoo.on("res.partner", "search_read", [])
    r = invoke("search", "res.partner", "-w", "mobil=+32", env={**ENV, "ODOO_NO_VALIDATE": "1"})
    assert r.exit_code == 0, r.stderr
    assert methods(fake_odoo) == ["search_read"]


def test_unstored_field_warns_but_runs(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    fake_odoo.on("res.partner", "search_read", [])
    r = invoke("search", "res.partner", "-w", "credit>0")
    assert r.exit_code == 0, r.stderr
    warning = json.loads(r.stderr.strip().splitlines()[0])
    assert warning["warning"] == "field_not_stored" and warning["field"] == "credit"
    assert "search_read" in methods(fake_odoo)


def test_count_validates_its_domain(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    r = invoke("count", "res.partner", "-w", "mobil=x")
    assert r.exit_code == 2
    assert "search_count" not in methods(fake_odoo)


def test_create_rejects_an_unknown_value_key_before_writing(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    r = invoke("create", "res.partner", "-v", "nam=X", env=RW)
    assert r.exit_code == 2
    assert json.loads(r.stderr)["error"]["code"] == "unknown_field"
    assert "create" not in methods(fake_odoo)


def test_write_guard_fires_before_any_rpc(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    r = invoke("write", "res.partner", "1", "-v", "nam=X", env=ENV)
    assert r.exit_code == 4
    assert json.loads(r.stderr)["error"]["code"] == "writes_disabled"
    assert fake_odoo.calls == []


def test_unknown_schema_degrades_to_no_validation(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [])
    r = invoke("search", "res.partner", "-w", "whatever=1")
    assert r.exit_code == 0, r.stderr
    assert "search_read" in methods(fake_odoo)


def test_cache_path_points_at_the_connection_file(fake_odoo: FakeOdoo) -> None:
    r = invoke("cache", "path")
    assert r.exit_code == 0 and r.stdout.strip().endswith(".json")


def test_cache_list_then_clear(fake_odoo: FakeOdoo) -> None:
    serve_schema(fake_odoo)
    fake_odoo.on("res.partner", "search_read", [])
    assert invoke("search", "res.partner", "--fields", "name").exit_code == 0
    listed = invoke("cache", "list", "--format", "json")
    assert [row["model"] for row in json.loads(listed.stdout)] == ["res.partner"]
    cleared = invoke("cache", "clear", "--format", "json")
    assert json.loads(cleared.stdout)["cleared"] is True
    assert json.loads(invoke("cache", "list", "--format", "json").stdout) == []
