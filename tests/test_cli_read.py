from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from odoocli.cli.app import app
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo, RpcFailure

ENV = {
    "ODOO_URL": BASE_URL,
    "ODOO_DB": DB,
    "ODOO_LOGIN": LOGIN,
    "ODOO_API_KEY": KEY,
    "ODOO_CONFIG": "/nonexistent/c.toml",
}
runner = CliRunner()


def invoke(*args: str, env: dict[str, str] | None = None) -> Any:
    return runner.invoke(app, list(args), env={**ENV, **(env or {})})


def test_info(fake_odoo: FakeOdoo) -> None:
    r = invoke("info")
    assert r.exit_code == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["server_version"] == "17.0" and data["uid"] == 7 and data["database"] == DB
    assert KEY not in r.stdout


def test_info_with_modules(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("ir.module.module", "search_read", [{"name": "sale"}, {"name": "account"}])
    r = invoke("info", "--modules")
    assert json.loads(r.stdout)["modules"] == ["account", "sale"]


def test_no_connection_exit_3(fake_odoo: FakeOdoo) -> None:
    r = runner.invoke(app, ["info"], env={"ODOO_CONFIG": "/nonexistent/c.toml"})
    assert r.exit_code == 3
    assert json.loads(r.stderr)["error"]["code"] == "no_connection"


def test_auth_failure_exit_3(fake_odoo: FakeOdoo) -> None:
    r = invoke("count", "res.partner", env={"ODOO_API_KEY": "bad"})
    assert r.exit_code == 3
    assert json.loads(r.stderr)["error"]["code"] == "auth_failed"


def test_search_builds_domain_and_kwargs(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [{"id": 1, "name": "Acme", "user_id": [3, "Bob"]}])
    r = invoke(
        "search",
        "res.partner",
        "-w",
        "is_company=true",
        "-w",
        "name~acme",
        "--fields",
        "name,user_id",
        "--limit",
        "5",
        "--order",
        "name desc",
    )
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == [{"id": 1, "name": "Acme", "user_id": [3, "Bob"]}]
    _, _, args, kwargs = fake_odoo.calls[-1]
    assert args == [[["is_company", "=", True], ["name", "ilike", "acme"]]]
    assert kwargs == {"fields": ["name", "user_id"], "limit": 5, "order": "name desc"}


def test_search_default_limit_80(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [])
    invoke("search", "res.partner")
    assert fake_odoo.calls[-1][3]["limit"] == 80


def test_search_all_paginates(fake_odoo: FakeOdoo) -> None:
    pages = {0: [{"id": i} for i in range(200)], 200: [{"id": 200}]}
    fake_odoo.on("res.partner", "search_read", lambda _a, k: pages.get(k.get("offset", 0), []))
    r = invoke("search", "res.partner", "--all", "--format", "jsonl")
    assert len(r.stdout.splitlines()) == 201
    assert [c[3].get("offset", 0) for c in fake_odoo.calls] == [0, 200]


def test_search_redacts_by_default(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.users", "search_read", [{"id": 1, "password": "x"}])
    assert json.loads(invoke("search", "res.users").stdout)[0]["password"] == "[redacted]"
    assert json.loads(invoke("--no-redact", "search", "res.users").stdout)[0]["password"] == "x"


def test_sensitive_model_refused_exit_4(fake_odoo: FakeOdoo) -> None:
    r = invoke("search", "ir.config_parameter")
    assert r.exit_code == 4 and json.loads(r.stderr)["error"]["code"] == "sensitive_model"
    assert fake_odoo.calls == []
    fake_odoo.on("ir.config_parameter", "search_read", [{"id": 1, "key": "k", "value": "v"}])
    assert invoke("--include-sensitive", "search", "ir.config_parameter").exit_code == 0
    env = {"ODOO_ALLOW_SENSITIVE": "1"}
    assert invoke("search", "ir.config_parameter", env=env).exit_code == 0


def test_search_odoo_error_exit_1(fake_odoo: FakeOdoo) -> None:
    def fail(_a: list[Any], _k: dict[str, Any]) -> Any:
        raise RpcFailure("builtins.ValueError", "Invalid field 'nope'")

    fake_odoo.on("res.partner", "search_read", fail)
    r = invoke("search", "res.partner", "--fields", "nope")
    assert r.exit_code == 1
    err = json.loads(r.stderr)["error"]
    assert err["message"] == "Invalid field 'nope'" and "debug" not in err
    r = invoke("search", "res.partner", "--fields", "nope", "--verbose")
    assert json.loads(r.stderr)["error"]["debug"] == "Traceback"


def test_search_lenient_warns_on_stderr(fake_odoo: FakeOdoo) -> None:
    def handler(_a: list[Any], k: dict[str, Any]) -> Any:
        if "nope" in k.get("fields", []):
            raise RpcFailure("builtins.ValueError", "Invalid field 'nope'")
        return [{"id": 1}]

    fake_odoo.on("res.partner", "search_read", handler)
    r = invoke("search", "res.partner", "--fields", "name,nope", "--lenient-fields")
    assert r.exit_code == 0
    assert json.loads(r.stderr)["warning"] == "invalid_field_removed"


def test_bad_where_exit_2(fake_odoo: FakeOdoo) -> None:
    r = invoke("search", "res.partner", "-w", "garbage")
    assert r.exit_code == 2 and json.loads(r.stderr)["error"]["code"] == "usage_error"


def test_bad_format_exit_2(fake_odoo: FakeOdoo) -> None:
    assert invoke("--format", "xml", "info").exit_code == 2


def test_count(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_count", 12)
    r = invoke("count", "res.partner", "-w", "is_company=true")
    assert r.stdout.strip() == "12"
    assert fake_odoo.calls[-1][2] == [[["is_company", "=", True]]]


def test_count_table_format_prints_scalar(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_count", 12)
    assert invoke("--format", "table", "count", "res.partner").stdout.strip() == "12"


def test_read(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "read", [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}])
    r = invoke("read", "res.partner", "1,2", "--fields", "name")
    assert json.loads(r.stdout)[1]["name"] == "B"
    assert fake_odoo.calls[-1][2] == [[1, 2]] and fake_odoo.calls[-1][3] == {"fields": ["name"]}


def test_read_bad_id_exit_2(fake_odoo: FakeOdoo) -> None:
    assert invoke("read", "res.partner", "abc").exit_code == 2


def test_models_like(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on(
        "ir.model",
        "search_read",
        [{"model": "sale.order", "name": "Sales Order", "transient": False}],
    )
    r = invoke("models", "--like", "sale")
    assert json.loads(r.stdout)[0]["model"] == "sale.order"
    assert fake_odoo.calls[-1][2] == [[["model", "ilike", "sale"]]]


def test_fields_filters(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on(
        "res.partner",
        "fields_get",
        {
            "name": {"type": "char", "string": "Name", "store": True, "required": True},
            "user_id": {
                "type": "many2one",
                "string": "Salesperson",
                "store": True,
                "relation": "res.users",
            },
            "total": {"type": "float", "string": "Total", "store": False},
        },
    )
    assert set(json.loads(invoke("fields", "res.partner").stdout)) == {"name", "user_id", "total"}
    assert set(json.loads(invoke("fields", "res.partner", "--type", "many2one").stdout)) == {
        "user_id"
    }
    assert set(json.loads(invoke("fields", "res.partner", "--stored").stdout)) == {
        "name",
        "user_id",
    }
    assert set(json.loads(invoke("fields", "res.partner", "--search", "sales").stdout)) == {
        "user_id"
    }
    assert "attributes" in fake_odoo.calls[0][3]
    invoke("fields", "res.partner", "--all-attributes")
    assert "attributes" not in fake_odoo.calls[-1][3]


def test_fields_table_output(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "fields_get", {"name": {"type": "char", "string": "Name"}})
    out = invoke("--format", "table", "fields", "res.partner").stdout
    assert "field" in out and "char" in out


def test_global_options_accepted_after_subcommand(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.users", "search_read", [{"id": 1, "password": "x"}])
    r = invoke("search", "res.users", "--no-redact", "--format=jsonl", "--timeout", "5")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {"id": 1, "password": "x"}


def test_hoist_stops_at_double_dash() -> None:
    from odoocli.cli.app import hoist_global_options

    assert hoist_global_options(["search", "x", "-f", "csv", "--", "-f", "raw"]) == [
        "-f",
        "csv",
        "search",
        "x",
        "--",
        "-f",
        "raw",
    ]


def test_context_flags_reach_odoo(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [])
    r = invoke(
        "search",
        "res.partner",
        "--include-archived",
        "--company",
        "3",
        "--lang",
        "fr_BE",
        "--context",
        '{"tz": "Europe/Brussels", "lang": "en_US"}',
    )
    assert r.exit_code == 0, r.stderr
    assert fake_odoo.calls[-1][3]["context"] == {
        "tz": "Europe/Brussels",
        "lang": "fr_BE",
        "allowed_company_ids": [3],
        "active_test": False,
    }


def test_bad_context_exit_2(fake_odoo: FakeOdoo) -> None:
    assert invoke("count", "res.partner", "--context", "[1]").exit_code == 2


def test_search_ids_only(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search", [4, 9])
    r = invoke("search", "res.partner", "-w", "is_company=true", "--ids-only", "--limit", "5")
    assert json.loads(r.stdout) == [4, 9]
    assert fake_odoo.calls[-1][1] == "search" and fake_odoo.calls[-1][3]["limit"] == 5


def test_read_missing_id_exit_1(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "read", [{"id": 1, "name": "A"}])
    r = invoke("read", "res.partner", "1,999")
    assert r.exit_code == 1
    err = json.loads(r.stderr)["error"]
    assert err["code"] == "missing_record" and "999" in err["message"]


def test_debug_logs_rpc_as_json_lines(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_count", 2)
    r = invoke("count", "res.partner", "--debug")
    assert r.exit_code == 0 and r.stdout.strip() == "2"
    lines = [json.loads(line) for line in r.stderr.splitlines()]
    assert any("res.partner.search_count" in line["log"]["message"] for line in lines)
    assert all(line["log"]["logger"].startswith("odoocli") for line in lines)


def test_insecure_flag_disables_verify(fake_odoo: FakeOdoo, monkeypatch: Any) -> None:
    import odoocli.cli.app as app_module
    from odoocli.client import AsyncOdooClient as real

    seen: dict[str, Any] = {}

    class Spy(real):
        def __init__(self, *a: Any, **k: Any) -> None:
            seen.update(k)
            super().__init__(*a, **k)

    monkeypatch.setattr(app_module, "AsyncOdooClient", Spy)
    fake_odoo.on("res.partner", "search_count", 0)
    assert invoke("count", "res.partner", "--insecure").exit_code == 0
    assert seen["verify_ssl"] is False
