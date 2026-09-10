from __future__ import annotations

import json
from typing import Any

from typer.testing import CliRunner

from odoocli.cli.app import app
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo
from tests.test_aliases import MOVE_FIELDS

ENV = {
    "ODOO_URL": BASE_URL,
    "ODOO_DB": DB,
    "ODOO_LOGIN": LOGIN,
    "ODOO_API_KEY": KEY,
    "ODOO_CONFIG": "/nonexistent/c.toml",
}
runner = CliRunner()

GROUPS = [
    {"partner_id": [4, "Acme"], "amount_residual": 1200.0, "__count": 3},
    {"partner_id": [9, "Globex"], "amount_residual": 300.0, "__count": 1},
]


def invoke(*args: str) -> Any:
    return runner.invoke(app, list(args), env=ENV)


def serve(fake: FakeOdoo) -> None:
    fields = {**MOVE_FIELDS, "partner_id": {"type": "many2one", "relation": "res.partner"}}
    fake.on("account.move", "fields_get", fields)
    fake.on("account.move", "read_group", GROUPS)


def read_group_call(fake: FakeOdoo) -> tuple[str, str, list[Any], dict[str, Any]]:
    return next(c for c in fake.calls if c[1] == "read_group")


def test_group_totals_a_field(fake_odoo: FakeOdoo) -> None:
    serve(fake_odoo)
    r = invoke("group", "invoices", "--by", "partner_id", "--sum", "amount_residual")
    assert r.exit_code == 0, r.stderr
    assert json.loads(r.stdout) == GROUPS
    _model, _method, args, kwargs = read_group_call(fake_odoo)
    assert args[0] == [["move_type", "=", "out_invoice"]]
    assert args[1] == ["partner_id", "amount_residual:sum"]
    assert args[2] == ["partner_id"]
    assert kwargs["lazy"] is False


def test_group_accepts_presets_and_limits(fake_odoo: FakeOdoo) -> None:
    serve(fake_odoo)
    r = invoke(
        "group",
        "invoices",
        "-w",
        "unpaid",
        "--by",
        "partner_id",
        "--limit",
        "5",
        "--order",
        "amount_residual desc",
    )
    assert r.exit_code == 0, r.stderr
    _model, _method, args, kwargs = read_group_call(fake_odoo)
    assert ["payment_state", "=", "not_paid"] in args[0]
    assert kwargs["limit"] == 5 and kwargs["orderby"] == "amount_residual desc"


def test_group_supports_a_date_granularity(fake_odoo: FakeOdoo) -> None:
    serve(fake_odoo)
    r = invoke("group", "invoices", "--by", "invoice_date_due:month")
    assert r.exit_code == 0, r.stderr
    assert read_group_call(fake_odoo)[2][2] == ["invoice_date_due:month"]


def test_group_validates_the_aggregate_field(fake_odoo: FakeOdoo) -> None:
    serve(fake_odoo)
    r = invoke("group", "invoices", "--by", "partner_id", "--sum", "amount_residal")
    assert r.exit_code == 2
    assert json.loads(r.stderr)["error"]["code"] == "unknown_field"
    assert not [c for c in fake_odoo.calls if c[1] == "read_group"]


def test_group_averages(fake_odoo: FakeOdoo) -> None:
    serve(fake_odoo)
    r = invoke("group", "invoices", "--by", "partner_id", "--avg", "amount_residual")
    assert r.exit_code == 0, r.stderr
    assert read_group_call(fake_odoo)[2][1] == ["partner_id", "amount_residual:avg"]


def test_group_needs_a_groupby(fake_odoo: FakeOdoo) -> None:
    r = invoke("group", "invoices", "--by", " ")
    assert r.exit_code == 2
    assert "--by needs at least one field" in json.loads(r.stderr)["error"]["message"]
