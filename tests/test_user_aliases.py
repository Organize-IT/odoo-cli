"""Aliases and presets a tenant defines for itself, in the profile file."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from odoocli import aliases
from odoocli.cli.app import app
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo

runner = CliRunner()

CONFIG = """
[profiles.acme]
url = "{url}"
database = "{db}"
login = "{login}"
api_key = "{key}"

[aliases.subscriptions]
model = "sale.subscription"
domain = [["stage_category", "=", "progress"]]
help = "Running subscriptions"

[aliases.contracts]
model = "account.analytic.account"

[aliases.invoices]
model = "account.move"
domain = [["move_type", "=", "out_invoice"], ["company_id", "=", 3]]
help = "Customer invoices of the Belgian entity"

[presets.mine]
domain = [["user_id", "=", 7]]
models = ["crm.lead", "sale.order"]
help = "Assigned to me"
"""


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(CONFIG.format(url=BASE_URL, db=DB, login=LOGIN, key=KEY))
    return path


def invoke(config: Path, *args: str) -> Any:
    return runner.invoke(
        app, ["-p", "acme", *args], env={"ODOO_CONFIG": str(config), "ODOO_PROFILE": "acme"}
    )


# ----- loading -----


def test_user_aliases_are_added(config: Path) -> None:
    registry = aliases.from_config(config)
    assert registry.resolve_model("subscriptions") == "sale.subscription"
    assert registry.resolve("contracts") is not None
    assert registry.resolve_model("cards") == "cards", "unknown names are still passed through"


def test_builtin_aliases_survive(config: Path) -> None:
    registry = aliases.from_config(config)
    assert registry.resolve_model("orders") == "sale.order"


def test_a_user_entry_replaces_the_builtin_of_the_same_name(config: Path) -> None:
    """The tenant knows its own vocabulary better than the shipped table does."""
    registry = aliases.from_config(config)
    alias = registry.resolve("invoices")
    assert alias is not None
    assert alias.clauses() == [["move_type", "=", "out_invoice"], ["company_id", "=", 3]]


def test_user_presets_are_scoped_like_builtin_ones(config: Path) -> None:
    registry = aliases.from_config(config)
    assert registry.expand("crm.lead", "mine") == [["user_id", "=", 7]]
    assert registry.expand("res.partner", "mine") is None


def test_dynamic_dates_work_in_a_user_preset(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[presets.recent]\ndomain = [["create_date", ">=", "@month-start"]]\n')
    assert aliases.from_config(path).expand("any.model", "recent", date(2026, 3, 15)) == [
        ["create_date", ">=", "2026-03-01"]
    ]


def test_a_missing_file_leaves_the_builtin_tables_alone(tmp_path: Path) -> None:
    assert aliases.from_config(tmp_path / "nope.toml") is aliases.BUILTIN


# ----- refusing what cannot be trusted -----


@pytest.mark.parametrize(
    "body",
    [
        '[aliases.bad]\nmodel = "notdotted"\n',
        "[aliases.bad]\nmodel = 42\n",
        '[aliases.bad]\nmodel = "a.b"\ndomain = "not a list"\n',
        '[aliases.bad]\nmodel = "a.b"\ndomain = [["only", "two"]]\n',
        '[presets.bad]\ndomain = [[1, "=", 2]]\n',
    ],
)
def test_a_malformed_entry_is_refused_rather_than_skipped(tmp_path: Path, body: str) -> None:
    """A filter the caller believes is applied and is not is the failure to avoid."""
    path = tmp_path / "c.toml"
    path.write_text(body)
    with pytest.raises(ValueError):
        aliases.from_config(path)


def test_a_malformed_table_fails_the_command_with_exit_2(tmp_path: Path) -> None:
    path = tmp_path / "c.toml"
    path.write_text('[aliases.bad]\nmodel = "notdotted"\n')
    result = runner.invoke(app, ["alias"], env={"ODOO_CONFIG": str(path)})
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "invalid_alias_table"


# ----- through the CLI -----


def test_search_uses_a_user_alias(fake_odoo: FakeOdoo, config: Path) -> None:
    fake_odoo.on("sale.subscription", "search_read", [{"id": 1}])
    result = invoke(config, "search", "subscriptions", "--no-validate")
    assert result.exit_code == 0, result.stderr
    call = next(c for c in fake_odoo.calls if c[1] == "search_read")
    assert call[0] == "sale.subscription"
    assert call[2][0] == [["stage_category", "=", "progress"]]


def test_search_uses_a_user_preset(fake_odoo: FakeOdoo, config: Path) -> None:
    fake_odoo.on("crm.lead", "search_read", [])
    result = invoke(config, "search", "leads", "-w", "mine", "--no-validate")
    assert result.exit_code == 0, result.stderr
    call = next(c for c in fake_odoo.calls if c[1] == "search_read")
    assert ["user_id", "=", 7] in call[2][0]


def test_a_user_alias_with_a_filter_is_refused_by_writes(fake_odoo: FakeOdoo, config: Path) -> None:
    result = invoke(config, "create", "subscriptions", "-v", "name=X")
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "alias_not_writable"


def test_a_user_alias_without_a_filter_is_accepted_by_writes(
    fake_odoo: FakeOdoo, config: Path
) -> None:
    fake_odoo.on("account.analytic.account", "fields_get", {"name": {"type": "char"}})
    result = invoke(config, "create", "contracts", "-v", "name=X", "--dry-run")
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)["model"] == "account.analytic.account"


def test_alias_listing_marks_where_each_entry_came_from(config: Path) -> None:
    rows = json.loads(invoke(config, "alias", "--format", "json").stdout)
    by_name = {row["alias"]: row for row in rows}
    assert by_name["subscriptions"]["source"] == "config"
    assert by_name["invoices"]["source"] == "config", "a replaced builtin counts as config"
    assert by_name["orders"]["source"] == "builtin"
