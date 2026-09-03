from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from odoocli.cli.app import app
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo

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
    return runner.invoke(app, list(args), env=env or RW)


def test_create_refused_without_allow_writes(fake_odoo: FakeOdoo) -> None:
    r = invoke("create", "res.partner", "-v", "name=X", env=ENV)
    assert r.exit_code == 4 and json.loads(r.stderr)["error"]["code"] == "writes_disabled"
    assert fake_odoo.calls == []


def test_create_dry_run_prints_payload(fake_odoo: FakeOdoo) -> None:
    r = invoke(
        "create",
        "res.partner",
        "-v",
        "name=X",
        "-v",
        "is_company=true",
        "--values",
        '{"ref": "A"}',
        "--dry-run",
        env=ENV,
    )
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == {
        "dry_run": True,
        "model": "res.partner",
        "method": "create",
        "args": [{"ref": "A", "name": "X", "is_company": True}],
        "kwargs": {},
    }
    assert fake_odoo.calls == []


def test_create_executes_and_logs(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "create", 42)
    r = invoke("create", "res.partner", "-v", "name=X")
    assert r.exit_code == 0 and r.stdout.strip() == "42"
    assert json.loads(r.stderr)["write"] == {
        "model": "res.partner",
        "method": "create",
        "ids": [42],
        "fields": ["name"],
    }


def test_create_requires_values(fake_odoo: FakeOdoo) -> None:
    assert invoke("create", "res.partner").exit_code == 2


def test_write(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "write", True)
    r = invoke("write", "res.partner", "1,2", "-v", "active=false")
    assert r.exit_code == 0 and r.stdout.strip() == "true"
    assert fake_odoo.calls[-1][2] == [[1, 2], {"active": False}]
    assert json.loads(r.stderr)["write"]["ids"] == [1, 2]


def test_write_requires_values(fake_odoo: FakeOdoo) -> None:
    assert invoke("write", "res.partner", "1").exit_code == 2


def test_unlink_requires_yes(fake_odoo: FakeOdoo) -> None:
    r = invoke("unlink", "res.partner", "1")
    assert r.exit_code == 4
    assert json.loads(r.stderr)["error"]["code"] == "confirmation_required"
    fake_odoo.on("res.partner", "unlink", True)
    assert invoke("unlink", "res.partner", "1", "--yes").exit_code == 0
    assert invoke("unlink", "res.partner", "1", env={**RW, "ODOO_ASSUME_YES": "1"}).exit_code == 0


def test_unlink_dry_run_needs_no_guard(fake_odoo: FakeOdoo) -> None:
    r = invoke("unlink", "res.partner", "1", "2", "--dry-run", env=ENV)
    assert r.exit_code == 0 and json.loads(r.stdout)["args"] == [[1, 2]]


def test_call_read_safe_needs_nothing(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "name_search", [[1, "Acme"]])
    r = invoke(
        "call",
        "res.partner",
        "name_search",
        "--args",
        '["acme"]',
        "--kwargs",
        '{"limit": 5}',
        env=ENV,
    )
    assert r.exit_code == 0 and json.loads(r.stdout) == [[1, "Acme"]]
    assert fake_odoo.calls[-1][2:] == (["acme"], {"limit": 5})
    assert r.stderr == ""


def test_call_action_needs_writes_and_yes(fake_odoo: FakeOdoo) -> None:
    assert invoke("call", "sale.order", "action_confirm", "--ids", "5", env=ENV).exit_code == 4
    assert invoke("call", "sale.order", "action_confirm", "--ids", "5").exit_code == 4
    fake_odoo.on("sale.order", "action_confirm", True)
    r = invoke("call", "sale.order", "action_confirm", "--ids", "5", "--yes")
    assert r.exit_code == 0
    assert fake_odoo.calls[-1][2] == [[5]]
    assert json.loads(r.stderr)["write"] == {
        "model": "sale.order",
        "method": "action_confirm",
        "ids": [5],
        "fields": [],
    }


def test_call_dry_run(fake_odoo: FakeOdoo) -> None:
    r = invoke("call", "sale.order", "action_confirm", "--ids", "5", "--dry-run", env=ENV)
    assert r.exit_code == 0
    assert json.loads(r.stdout)["args"] == [[5]]


def test_call_bad_json_exit_2(fake_odoo: FakeOdoo) -> None:
    assert invoke("call", "res.partner", "name_search", "--args", "{oops").exit_code == 2
    assert invoke("call", "res.partner", "name_search", "--args", '{"a": 1}').exit_code == 2


def test_sensitive_model_blocked_on_write(fake_odoo: FakeOdoo) -> None:
    r = invoke("create", "ir.cron", "-v", "name=x")
    assert r.exit_code == 4 and json.loads(r.stderr)["error"]["code"] == "sensitive_model"
