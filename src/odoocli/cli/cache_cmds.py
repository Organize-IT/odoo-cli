"""odoo cache path | list | clear — the on-disk model schema used for validation."""

from __future__ import annotations

import json
import os
import time
from typing import Any

import typer

from odoocli.cli.app import app, emit, session
from odoocli.schema import CACHE_VERSION, cache_file

cache_app = typer.Typer(
    help=(
        "Inspect the schema cache. Field names are checked against it before a call; "
        "entries expire after ODOO_SCHEMA_TTL seconds (default 24h)."
    ),
    no_args_is_help=True,
    rich_markup_mode=None,
)
app.add_typer(cache_app, name="cache")


def _path(ctx: typer.Context) -> Any:
    sess = session(ctx)
    profile = sess.profile()
    return cache_file(sess.env, profile.url, profile.database)


@cache_app.command("path")
def cache_path(ctx: typer.Context) -> None:
    """Print the cache file for the current connection."""
    typer.echo(str(_path(ctx)))


@cache_app.command("list")
def cache_list(ctx: typer.Context) -> None:
    """Models held in the cache, with their age in seconds."""
    path = _path(ctx)
    rows: list[dict[str, Any]] = []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if raw.get("version") == CACHE_VERSION:
        now = time.time()
        for model, entry in sorted(raw.get("models", {}).items()):
            if not isinstance(entry, dict):
                continue
            rows.append(
                {
                    "model": model,
                    "fields": len(entry.get("fields") or {}),
                    "age_seconds": int(now - float(entry.get("fetched_at", now))),
                }
            )
    emit(ctx, rows)


@cache_app.command("clear")
def cache_clear(ctx: typer.Context) -> None:
    """Delete the cache file for the current connection."""
    path = _path(ctx)
    removed = False
    try:
        os.remove(path)
        removed = True
    except FileNotFoundError:
        pass
    emit(ctx, {"cleared": removed, "path": str(path)})
