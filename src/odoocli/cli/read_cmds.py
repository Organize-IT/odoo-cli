"""Read-only commands: info, models, fields, search, count, read."""

from __future__ import annotations

from typing import Any

import typer

from odoocli.cli.app import app, check_model, emit, run, session, warn
from odoocli.cli.values import parse_ids, split_fields
from odoocli.client import AsyncOdooClient
from odoocli.config import Profile
from odoocli.domain import build_domain
from odoocli.lenient import lenient_search_read

DEFAULT_LIMIT = 80
PAGE_SIZE = 200
FIELD_ATTRIBUTES = ["string", "type", "required", "readonly", "store", "relation", "selection"]

WhereOpt = typer.Option(
    [], "--where", "-w", help="Condition 'field op value'. Repeatable, AND-ed together."
)
DomainOpt = typer.Option(None, "--domain", "-d", help="Odoo domain as JSON, AND-ed with -w.")
FieldsOpt = typer.Option(None, "--fields", help="Comma-separated field names.")


@app.command()
def info(
    ctx: typer.Context,
    modules: bool = typer.Option(False, "--modules", help="Also list installed module names."),
) -> None:
    """Server version, authenticated uid and connection source. Use it to test a connection."""

    async def go(client: AsyncOdooClient, profile: Profile) -> dict[str, Any]:
        version = await client.version()
        uid = await client.authenticate()
        out: dict[str, Any] = {
            "url": profile.url,
            "database": profile.database,
            "login": profile.login,
            "uid": uid,
            "source": profile.source,
            "allow_writes": profile.allow_writes,
            "server_version": version.get("server_version"),
            "server_version_info": version.get("server_version_info"),
        }
        if modules:
            rows = await client.search_read(
                "ir.module.module", [["state", "=", "installed"]], ["name"], limit=2000
            )
            out["modules"] = sorted(r["name"] for r in rows if r.get("name"))
        return out

    emit(ctx, run(ctx, go))


@app.command()
def models(
    ctx: typer.Context,
    like: str | None = typer.Option(None, "--like", help="Substring of the technical name."),
    where: list[str] = WhereOpt,
) -> None:
    """List models (technical name, label, transient)."""

    async def go(client: AsyncOdooClient, _profile: Profile) -> list[dict[str, Any]]:
        domain = build_domain(None, where)
        if like:
            domain.append(["model", "ilike", like])
        return await client.search_read(
            "ir.model", domain, ["model", "name", "transient"], order="model"
        )

    emit(ctx, run(ctx, go))


@app.command()
def fields(
    ctx: typer.Context,
    model: str = typer.Argument(..., help="Technical model name, e.g. res.partner"),
    type_: str | None = typer.Option(None, "--type", help="Keep only this field type."),
    stored: bool = typer.Option(
        False, "--stored", help="Keep only stored fields (searchable and orderable)."
    ),
    search: str | None = typer.Option(None, "--search", help="Substring of the name or label."),
    all_attributes: bool = typer.Option(
        False, "--all-attributes", help="Return every attribute Odoo has, not the curated set."
    ),
) -> None:
    """Introspect a model: field types, required, store, relation, selection values."""
    sess = session(ctx)

    async def go(client: AsyncOdooClient, profile: Profile) -> dict[str, dict[str, Any]]:
        check_model(sess, profile, model)
        return await client.fields_get(model, None if all_attributes else FIELD_ATTRIBUTES)

    data = run(ctx, go)
    needle = search.lower() if search else None
    out = {
        name: info
        for name, info in data.items()
        if (type_ is None or info.get("type") == type_)
        and (not stored or bool(info.get("store")))
        and (
            needle is None
            or needle in name.lower()
            or needle in str(info.get("string", "")).lower()
        )
    }
    rows = [
        {
            "field": name,
            "type": info.get("type"),
            "label": info.get("string"),
            "required": info.get("required", False),
            "store": info.get("store", False),
            "relation": info.get("relation", ""),
        }
        for name, info in out.items()
    ]
    emit(ctx, out, table_rows=rows)


@app.command()
def search(
    ctx: typer.Context,
    model: str = typer.Argument(..., help="Technical model name"),
    where: list[str] = WhereOpt,
    domain: str | None = DomainOpt,
    fields_: str | None = FieldsOpt,
    limit: int | None = typer.Option(
        None, "--limit", "-l", help=f"Max records (default {DEFAULT_LIMIT})."
    ),
    offset: int = typer.Option(0, "--offset"),
    order: str | None = typer.Option(None, "--order", help='e.g. "date_order desc, id"'),
    all_: bool = typer.Option(
        False, "--all", help="Fetch every match, paginated. Prefer --format jsonl."
    ),
    lenient: bool = typer.Option(
        False, "--lenient-fields", help="Drop fields Odoo rejects and retry (warns on stderr)."
    ),
) -> None:
    """search_read on a model. Output is the raw Odoo result."""
    sess = session(ctx)

    async def fetch(
        client: AsyncOdooClient, dom: list[Any], flds: list[str] | None, lim: int | None, off: int
    ) -> list[dict[str, Any]]:
        if lenient:
            return await lenient_search_read(
                client, model, dom, flds, lim, off, order, on_warning=warn
            )
        return await client.search_read(model, dom, flds, lim, off, order)

    async def go(client: AsyncOdooClient, profile: Profile) -> list[dict[str, Any]]:
        check_model(sess, profile, model)
        dom = build_domain(domain, where)
        flds = split_fields(fields_)
        if not all_:
            return await fetch(client, dom, flds, DEFAULT_LIMIT if limit is None else limit, offset)
        rows: list[dict[str, Any]] = []
        off = offset
        while True:
            page = await fetch(client, dom, flds, PAGE_SIZE, off)
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows
            off += PAGE_SIZE

    emit(ctx, run(ctx, go))


@app.command()
def count(
    ctx: typer.Context,
    model: str = typer.Argument(...),
    where: list[str] = WhereOpt,
    domain: str | None = DomainOpt,
) -> None:
    """search_count on a model. Prints a bare integer."""
    sess = session(ctx)

    async def go(client: AsyncOdooClient, profile: Profile) -> int:
        check_model(sess, profile, model)
        return await client.search_count(model, build_domain(domain, where))

    emit(ctx, run(ctx, go))


@app.command()
def read(
    ctx: typer.Context,
    model: str = typer.Argument(...),
    ids: list[str] = typer.Argument(..., help="Record ids, space or comma separated."),
    fields_: str | None = FieldsOpt,
) -> None:
    """Read records by id."""
    sess = session(ctx)

    async def go(client: AsyncOdooClient, profile: Profile) -> list[dict[str, Any]]:
        check_model(sess, profile, model)
        return await client.read(model, parse_ids(ids), split_fields(fields_))

    emit(ctx, run(ctx, go))
