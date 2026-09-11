"""Write commands, all behind allow_writes; unlink and non read-safe call also need --yes."""

from __future__ import annotations

from typing import Any

import typer

from odoocli.cli.app import (
    app,
    check_fields,
    check_model,
    emit,
    require_writes,
    require_yes,
    run,
    session,
    warn,
    write_target,
)
from odoocli.cli.values import parse_ids, parse_json_arg, parse_kv
from odoocli.client import AsyncOdooClient
from odoocli.config import Profile
from odoocli.errors import OdooUsageError
from odoocli.security import is_read_safe_method

ValuesOpt = typer.Option(
    [], "--value", "-v", help="field=value. Repeatable. Overrides keys from --values."
)
JsonValuesOpt = typer.Option(None, "--values", help="Values as a JSON object.")
DryRunOpt = typer.Option(
    False, "--dry-run", help="Print the payload, write nothing, exit 0. Values are still checked."
)
YesOpt = typer.Option(False, "--yes", "-y", help="Confirm a destructive or arbitrary call.")

# Sentinel returned by a dry run so the command prints nothing more.
_DRY = object()


def _merge_values(pairs: list[str], json_values: str | None) -> dict[str, Any]:
    base = parse_json_arg(json_values, "values") or {}
    if not isinstance(base, dict):
        raise OdooUsageError("--values must be a JSON object")
    base.update(parse_kv(pairs))
    if not base:
        raise OdooUsageError("No values given. Use -v field=value or --values '{...}'.")
    return base


def _dry_run(
    ctx: typer.Context, model: str, method: str, args: list[Any], kwargs: dict[str, Any]
) -> object:
    emit(ctx, {"dry_run": True, "model": model, "method": method, "args": args, "kwargs": kwargs})
    return _DRY


def _log_write(model: str, method: str, ids: list[int], fields: list[str]) -> None:
    warn({"write": {"model": model, "method": method, "ids": ids, "fields": fields}})


def _emit_unless_dry(ctx: typer.Context, result: Any) -> None:
    if result is not _DRY:
        emit(ctx, result)


@app.command()
def create(
    ctx: typer.Context,
    model: str = typer.Argument(...),
    values: list[str] = ValuesOpt,
    json_values: str | None = JsonValuesOpt,
    dry_run: bool = DryRunOpt,
) -> None:
    """Create one record. Prints the new id."""
    sess = session(ctx)

    async def go(client: AsyncOdooClient, profile: Profile) -> Any:
        target = write_target(sess.registry(), model)
        check_model(sess, profile, target)
        vals = _merge_values(values, json_values)
        if not dry_run:
            require_writes(profile)
        await check_fields(sess, client, profile, target, values=sorted(vals))
        if dry_run:
            return _dry_run(ctx, target, "create", [vals], {})
        new_id = await client.create(target, vals)
        ids = [new_id] if isinstance(new_id, int) else list(new_id)
        _log_write(target, "create", ids, sorted(vals))
        return new_id

    _emit_unless_dry(ctx, run(ctx, go))


@app.command()
def write(
    ctx: typer.Context,
    model: str = typer.Argument(...),
    ids: list[str] = typer.Argument(..., help="Record ids, space or comma separated."),
    values: list[str] = ValuesOpt,
    json_values: str | None = JsonValuesOpt,
    dry_run: bool = DryRunOpt,
) -> None:
    """Update records. Prints true."""
    sess = session(ctx)

    async def go(client: AsyncOdooClient, profile: Profile) -> Any:
        target = write_target(sess.registry(), model)
        check_model(sess, profile, target)
        id_list = parse_ids(ids)
        vals = _merge_values(values, json_values)
        if not dry_run:
            require_writes(profile)
        await check_fields(sess, client, profile, target, values=sorted(vals))
        if dry_run:
            return _dry_run(ctx, target, "write", [id_list, vals], {})
        ok = await client.write(target, id_list, vals)
        _log_write(target, "write", id_list, sorted(vals))
        return ok

    _emit_unless_dry(ctx, run(ctx, go))


@app.command()
def unlink(
    ctx: typer.Context,
    model: str = typer.Argument(...),
    ids: list[str] = typer.Argument(..., help="Record ids, space or comma separated."),
    yes: bool = YesOpt,
    dry_run: bool = DryRunOpt,
) -> None:
    """Delete records. Needs allow_writes and --yes."""
    sess = session(ctx)

    async def go(client: AsyncOdooClient, profile: Profile) -> Any:
        target = write_target(sess.registry(), model)
        check_model(sess, profile, target)
        id_list = parse_ids(ids)
        if dry_run:
            return _dry_run(ctx, target, "unlink", [id_list], {})
        require_writes(profile)
        require_yes(sess, yes, f"Deleting {len(id_list)} {target} record(s)")
        ok = await client.unlink(target, id_list)
        _log_write(target, "unlink", id_list, [])
        return ok

    _emit_unless_dry(ctx, run(ctx, go))


@app.command()
def call(
    ctx: typer.Context,
    model: str = typer.Argument(...),
    method: str = typer.Argument(
        ..., help="Any model method, e.g. action_confirm, name_search, read_group"
    ),
    ids: str | None = typer.Option(
        None, "--ids", help="Record ids (comma separated), prepended as the first positional arg."
    ),
    args: str | None = typer.Option(None, "--args", help="Positional args as a JSON list."),
    kwargs: str | None = typer.Option(None, "--kwargs", help="Keyword args as a JSON object."),
    yes: bool = YesOpt,
    dry_run: bool = DryRunOpt,
) -> None:
    """Call a model method through execute_kw. Read-only methods need no guard."""
    sess = session(ctx)

    async def go(client: AsyncOdooClient, profile: Profile) -> Any:
        target = write_target(sess.registry(), model)
        check_model(sess, profile, target)
        pos = parse_json_arg(args, "args") or []
        if not isinstance(pos, list):
            raise OdooUsageError("--args must be a JSON list")
        kw = parse_json_arg(kwargs, "kwargs") or {}
        if not isinstance(kw, dict):
            raise OdooUsageError("--kwargs must be a JSON object")
        id_list = parse_ids([ids]) if ids else []
        if id_list:
            pos = [id_list, *pos]
        if dry_run:
            return _dry_run(ctx, target, method, pos, kw)
        mutating = not is_read_safe_method(method)
        if mutating:
            require_writes(profile)
            require_yes(sess, yes, f"Calling {target}.{method}")
        result = await client.execute(target, method, *pos, **kw)
        if mutating:
            _log_write(target, method, id_list, [])
        return result

    _emit_unless_dry(ctx, run(ctx, go))
