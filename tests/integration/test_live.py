"""End-to-end tests against a live Odoo. Run with:

    ODOO_URL=... ODOO_DB=... ODOO_LOGIN=... ODOO_API_KEY=... [ODOO_ALLOW_WRITES=1] \
        uv run pytest -m integration -o addopts=""
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import date
from typing import Any

import pytest

from odoocli import AsyncOdooClient, OdooClient, aliases
from odoocli.errors import OdooFieldMissingError
from odoocli.lenient import lenient_search_read

pytestmark = pytest.mark.integration


def cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "odoocli", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_version_and_auth(live: OdooClient) -> None:
    v = live.version()
    # The oldest version the integration matrix runs (see .github/workflows/ci.yml).
    assert int(str(v["server_version"]).split(".")[0]) >= 15
    assert live.authenticate() > 0


def test_fields_search_count_read(live: OdooClient) -> None:
    fields = live.fields_get("res.partner", ["type", "store"])
    assert fields["name"]["type"] == "char" and fields["name"]["store"] is True
    rows = live.search_read(
        "res.partner", [["id", ">", 0]], ["name", "company_id"], limit=2, order="id"
    )
    assert rows
    assert live.search_count("res.partner", []) >= len(rows)
    assert live.read("res.partner", [rows[0]["id"]], ["name"])[0]["name"] == rows[0]["name"]


def test_cli_end_to_end() -> None:
    out = cli("info")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["uid"] > 0
    out = cli(
        "search",
        "res.partner",
        "-w",
        "id>0",
        "--fields",
        "name",
        "--limit",
        "1",
        "--format",
        "jsonl",
    )
    assert out.returncode == 0, out.stderr
    assert "name" in json.loads(out.stdout.splitlines()[0])
    out = cli("count", "ir.config_parameter")
    assert out.returncode == 4
    out = cli("fields", "res.partner", "--type", "many2one", "--stored")
    assert out.returncode == 0 and "company_id" in json.loads(out.stdout)
    out = cli("models", "--like", "res.partner")
    assert out.returncode == 0 and any(m["model"] == "res.partner" for m in json.loads(out.stdout))


@pytest.mark.skipif(
    os.environ.get("ODOO_ALLOW_WRITES", "").lower() not in ("1", "true", "yes"),
    reason="writes disabled",
)
def test_cli_write_cycle() -> None:
    created = cli(
        "create", "res.partner", "-v", "name=odoocli integration", "-v", "is_company=true"
    )
    assert created.returncode == 0, created.stderr
    new_id = int(created.stdout.strip())
    assert json.loads(created.stderr)["write"]["ids"] == [new_id]
    assert cli("write", "res.partner", str(new_id), "-v", "ref=ODOOCLI").returncode == 0
    got = json.loads(cli("read", "res.partner", str(new_id), "--fields", "ref").stdout)
    assert got[0]["ref"] == "ODOOCLI"
    ns = cli("call", "res.partner", "name_search", "--args", '["odoocli integration"]')
    assert ns.returncode == 0 and any(r[0] == new_id for r in json.loads(ns.stdout))
    # Archived records disappear from search unless --include-archived is given.
    assert cli("write", "res.partner", str(new_id), "-v", "active=false").returncode == 0
    ids = cli("search", "res.partner", "-w", f"id={new_id}", "--ids-only")
    assert json.loads(ids.stdout) == []
    ids = cli("search", "res.partner", "-w", f"id={new_id}", "--ids-only", "--include-archived")
    assert json.loads(ids.stdout) == [new_id]
    # Context flows through (en_US is always installed; Odoo 18+ rejects unknown codes).
    lang = cli("fields", "res.partner", "--search", "name", "--lang", "en_US", "--debug")
    assert lang.returncode == 0 and '"log"' in lang.stderr
    assert cli("unlink", "res.partner", str(new_id)).returncode == 4
    assert cli("unlink", "res.partner", str(new_id), "--yes").returncode == 0
    assert cli("count", "res.partner", "-w", f"id={new_id}").stdout.strip() == "0"
    assert cli("read", "res.partner", str(new_id)).returncode == 1


def test_live_schema_validation_rejects_a_typo() -> None:
    """The schema really is readable on this server, and a typo never reaches it."""
    out = cli("search", "res.partner", "-w", "nam=x")
    assert out.returncode == 2, out.stdout
    error = json.loads(out.stderr)["error"]
    assert error["code"] == "unknown_field"
    assert "name" in error["message"]


def test_live_schema_validation_accepts_a_relation_path() -> None:
    out = cli("search", "res.partner", "-w", "country_id.code=BE", "--fields", "name", "-l", "1")
    assert out.returncode == 0, out.stderr


def test_live_alias_and_preset() -> None:
    """account.move really answers to the alias filter and the preset fields."""
    out = cli("count", "invoices", "-w", "unpaid")
    assert out.returncode == 0, out.stderr
    assert int(out.stdout.strip()) >= 0


def test_live_read_group() -> None:
    """read_group exists and answers on every supported Odoo version."""
    out = cli("group", "res.partner", "--by", "is_company", "--format", "json")
    assert out.returncode == 0, out.stderr
    groups = json.loads(out.stdout)
    assert groups and all("__count" in g for g in groups)
    # Totals and ordering by a total: Odoo 20 answers through formatted_read_group, which
    # only orders by an aggregate spec ("color:sum desc"), not by the bare field name.
    out = cli(
        "group", "res.partner", "--by", "is_company", "--sum", "color", "--order", "color desc"
    )
    assert out.returncode == 0, out.stderr
    assert all("__count" in g for g in json.loads(out.stdout))


def test_live_every_builtin_filter_runs(live: OdooClient) -> None:
    """Every field a built-in alias or preset filters on exists on this version.

    An alias whose clause names a field the server lacks would be refused (or, repaired,
    silently widened) on that version. Models whose module is not installed are skipped.
    """
    installed = {row["model"] for row in live.search_read("ir.model", [], ["model"])}
    for name, alias in aliases.ALIASES.items():
        if alias.domain and alias.model in installed:
            assert live.search_count(alias.model, alias.clauses()) >= 0, name
    for name, preset in aliases.PRESETS.items():
        for model in preset.models or ("res.partner",):
            if model in installed:
                assert live.search_count(model, preset.clauses(date.today())) >= 0, name


def _lenient(
    model: str, domain: list[Any], fields: list[str], *, strip_domain: bool = False
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    warnings: list[dict[str, Any]] = []

    async def go() -> list[dict[str, Any]]:
        async with AsyncOdooClient(
            os.environ["ODOO_URL"],
            os.environ["ODOO_DB"],
            os.environ["ODOO_LOGIN"],
            os.environ["ODOO_API_KEY"],
        ) as c:
            return await lenient_search_read(
                c,
                model,
                domain,
                fields,
                1,
                0,
                None,
                strip_domain=strip_domain,
                on_warning=warnings.append,
            )

    return asyncio.run(go()), warnings


def test_live_lenient_reads_this_versions_error_messages(live: OdooClient) -> None:
    """The messages ``lenient`` parses are the ones this Odoo version actually sends."""
    # A missing field in the domain is refused, not dropped, and names the queried model.
    with pytest.raises(OdooFieldMissingError) as exc:
        _lenient("res.partner", [["odoocli_missing", "=", 1]], ["id"])
    assert (exc.value.model, exc.value.field) == ("res.partner", "odoocli_missing")
    # Missing at the end of a path: the error names the related model.
    with pytest.raises(OdooFieldMissingError) as exc:
        _lenient("res.partner", [["country_id.odoocli_missing", "=", 1]], ["id"])
    assert (exc.value.model, exc.value.field) == ("res.country", "odoocli_missing")
    # Opted in, the dotted leaf is removed and the query runs.
    rows, warnings = _lenient(
        "res.partner", [["country_id.odoocli_missing", "=", 1]], ["id"], strip_domain=True
    )
    assert rows and warnings and warnings[0]["from"] == ["domain"]
    # res.partner has no ``login``; res.users does. The rejection is about ``fields`` only,
    # and the path through user_ids stays in the domain. The filter must match a record, or
    # Odoo never reaches the read that rejects the field.
    rows, warnings = _lenient("res.partner", [["user_ids.login", "=", "admin"]], ["id", "login"])
    assert rows and "login" not in rows[0]
    assert warnings == [{"warning": "invalid_field_removed", "field": "login", "from": ["fields"]}]
