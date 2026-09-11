"""odoo alias: the model aliases and named conditions understood by read commands."""

from __future__ import annotations

from typing import Any

import typer

from odoocli.cli.app import app, emit, session


@app.command("alias")
def alias_cmd(
    ctx: typer.Context,
    name: str | None = typer.Argument(
        None, help="Filter the list, or the model/alias whose presets you want."
    ),
    presets: bool = typer.Option(
        False, "--presets", help="List named conditions instead of aliases."
    ),
) -> None:
    """Model aliases ('invoices' -> account.move) and presets ('-w overdue'). Offline."""
    registry = session(ctx).registry()
    if presets:
        model = registry.resolve_model(name) if name else None
        rows: list[dict[str, Any]] = [
            {
                "preset": preset_name,
                "models": ", ".join(preset.models) if preset.models else "any",
                "domain": " and ".join(f"{f} {o} {v}" for f, o, v in preset.domain),
                "help": preset.help,
            }
            for preset_name, preset in sorted(registry.presets_for(model).items())
        ]
        emit(ctx, rows)
        return
    listing = registry.rows()
    if name:
        needle = name.lower()
        listing = [r for r in listing if needle in r["alias"] or needle in r["model"]]
    emit(ctx, listing)
