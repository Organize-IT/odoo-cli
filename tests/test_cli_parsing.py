"""Global option hoisting and sync/async client parity."""

from __future__ import annotations

import inspect
import json
from typing import Any

from typer.testing import CliRunner

from odoocli.cli.app import app, hoist_global_options
from odoocli.client import AsyncOdooClient
from odoocli.sync import OdooClient
from tests.conftest import BASE_URL, DB, KEY, LOGIN, FakeOdoo

ENV = {
    "ODOO_URL": BASE_URL,
    "ODOO_DB": DB,
    "ODOO_LOGIN": LOGIN,
    "ODOO_API_KEY": KEY,
    "ODOO_CONFIG": "/nonexistent/c.toml",
}
runner = CliRunner()


def invoke(*args: str) -> Any:
    return runner.invoke(app, list(args), env=ENV)


# ----- hoisting -----


def test_global_option_after_the_subcommand_is_hoisted() -> None:
    assert hoist_global_options(["search", "x", "--lang", "fr_BE"]) == [
        "--lang",
        "fr_BE",
        "search",
        "x",
    ]


def test_equals_form_is_hoisted() -> None:
    assert hoist_global_options(["search", "x", "--format=csv"]) == [
        "--format=csv",
        "search",
        "x",
    ]


def test_local_option_keeps_an_option_shaped_value() -> None:
    """--order takes a value; '--lang' after it belongs to --order, not to the root."""
    args = ["search", "res.partner", "--order", "--lang"]
    assert hoist_global_options(args, frozenset({"--order"})) == args


def test_a_hoisted_flag_still_moves_past_a_local_option() -> None:
    assert hoist_global_options(
        ["search", "x", "--order", "name", "--debug"], frozenset({"--order"})
    ) == ["--debug", "search", "x", "--order", "name"]


def test_local_flag_is_not_treated_as_taking_a_value() -> None:
    assert hoist_global_options(
        ["search", "x", "--ids-only", "--lang", "fr_BE"], frozenset({"--order"})
    ) == ["--lang", "fr_BE", "search", "x", "--ids-only"]


def test_global_name_wins_over_a_local_option_of_the_same_name() -> None:
    assert hoist_global_options(["search", "x", "--lang", "fr"], frozenset({"--lang"})) == [
        "--lang",
        "fr",
        "search",
        "x",
    ]


def test_hoisting_survives_a_subcommand_group() -> None:
    assert hoist_global_options(["profile", "list", "--format", "json"]) == [
        "--format",
        "json",
        "profile",
        "list",
    ]


def test_order_value_reaches_odoo_unharmed(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [])
    r = invoke("search", "res.partner", "--order", "name desc", "--format", "json")
    assert r.exit_code == 0, r.stderr
    call = next(c for c in fake_odoo.calls if c[1] == "search_read")
    assert call[3]["order"] == "name desc"


def test_unknown_subcommand_does_not_break_hoisting(fake_odoo: FakeOdoo) -> None:
    r = invoke("nope", "--format", "json")
    assert r.exit_code != 0  # click reports the unknown command, we did not crash


# ----- sync / async parity -----


def _public_coroutines(cls: type) -> set[str]:
    return {
        name
        for name, member in inspect.getmembers(cls, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }


def test_sync_client_mirrors_every_async_method() -> None:
    missing = _public_coroutines(AsyncOdooClient) - set(dir(OdooClient))
    assert missing == set(), f"OdooClient is missing {sorted(missing)}"


def test_mirrored_methods_keep_their_signature() -> None:
    for name in _public_coroutines(AsyncOdooClient):
        async_sig = inspect.signature(getattr(AsyncOdooClient, name))
        sync_sig = inspect.signature(getattr(OdooClient, name))
        assert list(async_sig.parameters) == list(sync_sig.parameters), name


def test_sync_client_runs_a_call(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [{"id": 1}])
    with OdooClient(BASE_URL, DB, LOGIN, KEY) as odoo:
        assert odoo.search_read("res.partner", [], ["id"]) == [{"id": 1}]
        assert odoo.uid == fake_odoo.uid


def test_closed_sync_client_refuses_further_calls(fake_odoo: FakeOdoo) -> None:
    odoo = OdooClient(BASE_URL, DB, LOGIN, KEY)
    odoo.close()
    try:
        odoo.version()
    except RuntimeError as e:
        assert "closed" in str(e)
    else:  # pragma: no cover - the guard must fire
        raise AssertionError("a closed client should refuse to run")


def test_sync_client_does_not_leak_its_loop_thread(fake_odoo: FakeOdoo) -> None:
    odoo = OdooClient(BASE_URL, DB, LOGIN, KEY)
    thread = odoo._thread
    odoo.close()
    assert not thread.is_alive()


def test_context_is_shared_with_the_async_client() -> None:
    odoo = OdooClient(BASE_URL, DB, LOGIN, KEY, context={"lang": "fr_BE"})
    try:
        odoo.context["allowed_company_ids"] = [2]
        assert odoo._async.context == {"lang": "fr_BE", "allowed_company_ids": [2]}
    finally:
        odoo.close()


def test_json_output_of_a_hoisted_command_is_still_data_only(fake_odoo: FakeOdoo) -> None:
    fake_odoo.on("res.partner", "search_read", [{"id": 1}])
    r = invoke("search", "res.partner", "--format", "json", "--fields", "id")
    assert json.loads(r.stdout) == [{"id": 1}]
