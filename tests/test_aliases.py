from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from typer.testing import CliRunner

from odoocli import aliases
from odoocli.cli.app import app, read_target, write_target
from odoocli.domain import build_domain
from odoocli.errors import OdooUsageError
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

MOVE_FIELDS: dict[str, Any] = {
    "id": {"type": "integer", "store": True},
    "name": {"type": "char", "store": True},
    "move_type": {"type": "selection", "store": True},
    "payment_state": {"type": "selection", "store": True},
    "invoice_date_due": {"type": "date", "store": True},
    "amount_residual": {"type": "monetary", "store": True},
}


def invoke(*args: str, env: dict[str, str] | None = None) -> Any:
    return runner.invoke(app, list(args), env=env or ENV)


# ----- table -----


def test_alias_maps_to_a_model() -> None:
    assert aliases.resolve_model("invoices") == "account.move"
    assert aliases.resolve_model("res.partner") == "res.partner"


def test_alias_lookup_is_case_insensitive() -> None:
    assert aliases.resolve_model("Invoices") == "account.move"


def test_every_alias_names_a_dotted_model() -> None:
    assert all("." in alias.model for alias in aliases.ALIASES.values())


def test_every_preset_targets_known_models() -> None:
    models = {alias.model for alias in aliases.ALIASES.values()}
    for preset in aliases.PRESETS.values():
        assert set(preset.models) <= models


# ----- presets -----


def test_preset_expands_to_clauses() -> None:
    assert aliases.expand("account.move", "unpaid") == [["payment_state", "=", "not_paid"]]


def test_preset_resolves_dynamic_dates() -> None:
    expanded = aliases.expand("account.move", "overdue", date(2026, 3, 15))
    assert expanded == [
        ["payment_state", "=", "not_paid"],
        ["invoice_date_due", "<", "2026-03-15"],
    ]


def test_month_start_preset() -> None:
    assert aliases.expand("account.move", "this-month", date(2026, 3, 15)) == [
        ["invoice_date", ">=", "2026-03-01"]
    ]


def test_preset_is_ignored_on_an_unrelated_model() -> None:
    assert aliases.expand("res.partner", "unpaid") is None


def test_global_preset_applies_anywhere() -> None:
    assert aliases.expand("res.partner", "archived") == [["active", "=", False]]


# ----- domain building -----


def test_build_domain_combines_base_preset_and_condition() -> None:
    domain = build_domain(
        None,
        ["unpaid", "amount_residual>100"],
        model="account.move",
        base=[["move_type", "=", "out_invoice"]],
        today=date(2026, 3, 15),
    )
    assert domain == [
        ["move_type", "=", "out_invoice"],
        ["payment_state", "=", "not_paid"],
        ["amount_residual", ">", 100],
    ]


def test_build_domain_without_a_model_keeps_the_old_behaviour() -> None:
    assert build_domain(None, ["name=X"]) == [["name", "=", "X"]]


def test_bare_word_that_is_not_a_preset_lists_the_presets() -> None:
    with pytest.raises(OdooUsageError) as excinfo:
        build_domain(None, ["overdu"], model="account.move")
    assert "neither a condition nor a preset" in excinfo.value.message
    assert "overdue" in excinfo.value.message


def test_malformed_condition_keeps_its_own_error() -> None:
    with pytest.raises(OdooUsageError) as excinfo:
        build_domain(None, ["name!!X"], model="account.move")
    assert "Cannot parse condition" in excinfo.value.message


# ----- targets -----


def test_read_target_returns_model_and_clauses() -> None:
    assert read_target("invoices") == ("account.move", [["move_type", "=", "out_invoice"]])
    assert read_target("res.partner") == ("res.partner", [])


def test_write_target_refuses_a_filtered_alias() -> None:
    with pytest.raises(OdooUsageError) as excinfo:
        write_target("invoices")
    assert excinfo.value.code == "alias_not_writable"
    assert "account.move" in excinfo.value.message


def test_write_target_accepts_a_plain_alias() -> None:
    assert write_target("partners") == "res.partner"


def test_unknown_dotless_name_suggests_an_alias() -> None:
    with pytest.raises(OdooUsageError) as excinfo:
        read_target("invoces")
    assert excinfo.value.code == "unknown_model"
    assert "invoices" in excinfo.value.message


def test_unknown_dotted_name_is_left_to_the_server() -> None:
    assert read_target("not.a.model") == ("not.a.model", [])


# ----- CLI -----


def test_search_through_an_alias_filters_the_model(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("account.move", "fields_get", MOVE_FIELDS)
    fake_odoo.on("account.move", "search_read", [{"id": 1}])
    r = invoke("search", "invoices", "-w", "unpaid", "--fields", "name")
    assert r.exit_code == 0, r.stderr
    call = next(c for c in fake_odoo.calls if c[1] == "search_read")
    assert call[0] == "account.move"
    assert call[2][0] == [
        ["move_type", "=", "out_invoice"],
        ["payment_state", "=", "not_paid"],
    ]


def test_count_through_an_alias(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("account.move", "fields_get", MOVE_FIELDS)
    fake_odoo.on("account.move", "search_count", 3)
    r = invoke("count", "bills")
    assert r.exit_code == 0 and r.stdout.strip() == "3"
    call = next(c for c in fake_odoo.calls if c[1] == "search_count")
    assert call[2][0] == [["move_type", "=", "in_invoice"]]


def test_create_through_a_filtered_alias_is_refused(fake_odoo: FakeOdoo) -> None:
    r = invoke("create", "invoices", "-v", "name=X", env=RW)
    assert r.exit_code == 2
    assert json.loads(r.stderr)["error"]["code"] == "alias_not_writable"
    assert fake_odoo.calls == []


def test_alias_command_lists_offline() -> None:
    r = invoke("alias", "invoices", "--format", "json")
    rows = json.loads(r.stdout)
    assert r.exit_code == 0
    assert rows[0]["alias"] == "invoices" and rows[0]["model"] == "account.move"


def test_alias_presets_are_scoped_to_the_model() -> None:
    r = invoke("alias", "invoices", "--presets", "--format", "json")
    names = {row["preset"] for row in json.loads(r.stdout)}
    assert "overdue" in names and "confirmed" not in names
