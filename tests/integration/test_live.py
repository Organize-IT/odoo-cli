"""End-to-end tests against a live Odoo. Run with:

    ODOO_URL=... ODOO_DB=... ODOO_LOGIN=... ODOO_API_KEY=... [ODOO_ALLOW_WRITES=1] \
        uv run pytest -m integration -o addopts=""
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from odoocli import OdooClient

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
    assert int(str(v["server_version"]).split(".")[0]) >= 17
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
