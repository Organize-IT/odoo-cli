"""odoo profile add | list | test | remove | path"""

from __future__ import annotations

from typing import Any

import typer

from odoocli.cli.app import app, emit, fail, session
from odoocli.cli.read_cmds import info
from odoocli.config import load_profiles, remove_profile, save_profile
from odoocli.errors import OdooConnectionError

profile_app = typer.Typer(
    help="Manage named connections stored in the config file (mode 0600).",
    no_args_is_help=True,
    rich_markup_mode=None,
)
app.add_typer(profile_app, name="profile")


@profile_app.command("add")
def profile_add(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    url: str = typer.Option(..., "--url", help="https://your-odoo.example.com"),
    db: str = typer.Option(..., "--db", help="Database name"),
    login: str = typer.Option(..., "--login", help="User login (email)"),
    api_key: str | None = typer.Option(
        None, "--api-key", help="API key or password, stored in the file."
    ),
    api_key_env: str | None = typer.Option(
        None, "--api-key-env", help="Name of an env var holding the key (nothing stored)."
    ),
    allow_writes: bool = typer.Option(
        False, "--allow-writes", help="Enable create/write/unlink/call on this profile."
    ),
    allow_sensitive: bool = typer.Option(
        False, "--allow-sensitive", help="Allow sensitive models on this profile."
    ),
    no_verify_ssl: bool = typer.Option(
        False, "--no-verify-ssl", help="Skip TLS verification (self-signed on-prem)."
    ),
    test: bool = typer.Option(False, "--test", help="Run 'odoo info' with the new profile."),
) -> None:
    """Add or replace a profile."""
    if bool(api_key) == bool(api_key_env):
        raise typer.BadParameter("Give exactly one of --api-key or --api-key-env")
    sess = session(ctx)
    save_profile(
        sess.config,
        name,
        {
            "url": url.rstrip("/"),
            "database": db,
            "login": login,
            "api_key": api_key,
            "api_key_env": api_key_env,
            "allow_writes": allow_writes,
            "allow_sensitive": allow_sensitive,
            "verify_ssl": False if no_verify_ssl else None,
        },
    )
    if test:
        sess.profile_name = name
        info(ctx, modules=False)


@profile_app.command("list")
def profile_list(ctx: typer.Context) -> None:
    """List profiles. Keys are never printed."""
    sess = session(ctx)
    rows: list[dict[str, Any]] = []
    for name, data in load_profiles(sess.config).items():
        key = "***" if data.get("api_key") else f"${data.get('api_key_env', '')}"
        rows.append(
            {
                "name": name,
                "url": data.get("url"),
                "database": data.get("database"),
                "login": data.get("login"),
                "key": key,
                "allow_writes": bool(data.get("allow_writes", False)),
                "allow_sensitive": bool(data.get("allow_sensitive", False)),
                "verify_ssl": bool(data.get("verify_ssl", True)),
            }
        )
    emit(ctx, rows)


@profile_app.command("test")
def profile_test(ctx: typer.Context, name: str | None = typer.Argument(None)) -> None:
    """Authenticate with a profile (default: the one that would be used) and print server info."""
    sess = session(ctx)
    if name:
        sess.profile_name = name
    info(ctx, modules=False)


@profile_app.command("remove")
def profile_remove(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    """Delete a profile."""
    sess = session(ctx)
    if not remove_profile(sess.config, name):
        fail(
            OdooConnectionError(
                f"Profile {name!r} not found in {sess.config}", code="no_connection"
            ),
            False,
        )


@profile_app.command("path")
def profile_path(ctx: typer.Context) -> None:
    """Print the config file path."""
    typer.echo(str(session(ctx).config))
