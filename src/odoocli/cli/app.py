"""Typer application: global options, session, run/emit helpers, exit code mapping."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import typer
from typer.core import TyperGroup

from odoocli._version import __version__
from odoocli.cli.output import FORMATS, detect_format, render
from odoocli.client import AsyncOdooClient
from odoocli.config import ENV_ASSUME_YES, Profile, config_path, env_flag, resolve_profile
from odoocli.errors import OdooError, OdooRefusedError
from odoocli.security import is_sensitive_model, redact

T = TypeVar("T")

# Root options that may appear anywhere on the command line. Agents naturally
# write ``odoo search res.partner --format jsonl``; click only accepts group
# options before the subcommand, so we hoist them.
_GLOBAL_WITH_VALUE = {"--profile", "-p", "--format", "-f", "--timeout"}
_GLOBAL_FLAGS = {"--no-redact", "--include-sensitive", "--verbose", "--version"}


def hoist_global_options(args: list[str]) -> list[str]:
    """Move root options found after the subcommand to the front, keeping order."""
    hoisted: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            rest.extend(args[i:])
            break
        name, eq, _value = tok.partition("=")
        if tok in _GLOBAL_FLAGS:
            hoisted.append(tok)
        elif tok in _GLOBAL_WITH_VALUE and i + 1 < len(args):
            hoisted.extend(args[i : i + 2])
            i += 1
        elif eq and name in _GLOBAL_WITH_VALUE:
            hoisted.append(tok)
        else:
            rest.append(tok)
        i += 1
    return hoisted + rest


class _RootGroup(TyperGroup):
    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        return super().parse_args(ctx, hoist_global_options(args))


app = typer.Typer(
    name="odoo",
    cls=_RootGroup,
    help=(
        "Odoo JSON-RPC CLI for AI agents and scripts.\n\n"
        "stdout carries only data: raw Odoo JSON when piped, a table on a terminal. "
        "Errors, warnings and write logs are single JSON lines on stderr. "
        "Exit codes: 0 ok, 1 Odoo error, 2 usage, 3 connection/auth, 4 refused by a guard.\n\n"
        "New here? Run: odoo agent-guide"
    ),
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode=None,
    context_settings={"help_option_names": ["-h", "--help"]},
)


@dataclass
class Session:
    profile_name: str | None
    fmt: str | None
    redact: bool
    include_sensitive: bool
    timeout: float
    verbose: bool
    assume_yes: bool
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    config: Path = field(default_factory=lambda: config_path(os.environ))

    def profile(self) -> Profile:
        return resolve_profile(self.profile_name, self.env, self.config)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"odoo (odoocli) {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None,
        "--profile",
        "-p",
        help="Profile name (see 'odoo profile'). Beats ODOO_PROFILE and ODOO_* env.",
    ),
    fmt: str | None = typer.Option(
        None,
        "--format",
        "-f",
        help="json | jsonl | table | csv. Default: table on a TTY, json otherwise.",
    ),
    no_redact: bool = typer.Option(
        False, "--no-redact", help="Do not mask password/api_key/secret field values."
    ),
    include_sensitive: bool = typer.Option(
        False,
        "--include-sensitive",
        help="Allow sensitive models (ir.config_parameter, ir.mail_server, ir.cron, ...).",
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="Seconds per RPC call."),
    verbose: bool = typer.Option(
        False, "--verbose", help="Include the Odoo debug payload in errors."
    ),
    _version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Print version."
    ),
) -> None:
    if fmt is not None and fmt not in FORMATS:
        raise typer.BadParameter(f"--format must be one of {', '.join(FORMATS)}")
    ctx.obj = Session(
        profile_name=profile,
        fmt=fmt,
        redact=not no_redact,
        include_sensitive=include_sensitive,
        timeout=timeout,
        verbose=verbose,
        assume_yes=env_flag(os.environ, ENV_ASSUME_YES),
    )


def session(ctx: typer.Context) -> Session:
    obj = ctx.obj
    assert isinstance(obj, Session)
    return obj


def warn(payload: dict[str, Any]) -> None:
    """One JSON line on stderr (warnings, write logs)."""
    sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stderr.flush()


def fail(err: OdooError, verbose: bool) -> None:
    body = err.to_dict()
    if verbose and err.data:
        body["debug"] = err.data.get("debug")
    warn({"error": body})
    raise typer.Exit(err.exit_code)


def check_model(sess: Session, profile: Profile, model: str) -> None:
    if is_sensitive_model(model) and not (sess.include_sensitive or profile.allow_sensitive):
        raise OdooRefusedError(
            f"Model {model!r} is sensitive (secrets or code execution). "
            "Pass --include-sensitive or set allow_sensitive = true on the profile.",
            code="sensitive_model",
        )


def require_writes(profile: Profile) -> None:
    if not profile.allow_writes:
        raise OdooRefusedError(
            f"Writes are disabled for {profile.source}. Set allow_writes = true on the profile "
            "or ODOO_ALLOW_WRITES=1 in the environment.",
            code="writes_disabled",
        )


def require_yes(sess: Session, yes: bool, what: str) -> None:
    if not (yes or sess.assume_yes):
        raise OdooRefusedError(
            f"{what} needs explicit confirmation: pass --yes (or ODOO_ASSUME_YES=1).",
            code="confirmation_required",
        )


def run(ctx: typer.Context, fn: Callable[[AsyncOdooClient, Profile], Awaitable[T]]) -> T:
    """Resolve the profile, open a client, run ``fn``, map errors to exit codes.

    Argument parsing that can raise ``OdooUsageError`` belongs inside ``fn`` so
    it is mapped to exit code 2 like every other ``OdooError``.
    """
    sess = session(ctx)

    async def _go() -> T:
        profile = sess.profile()
        async with AsyncOdooClient(
            profile.url, profile.database, profile.login, profile.api_key, timeout=sess.timeout
        ) as client:
            return await fn(client, profile)

    try:
        return asyncio.run(_go())
    except OdooError as e:
        fail(e, sess.verbose)
        raise AssertionError("unreachable") from e


def emit(ctx: typer.Context, data: Any, *, table_rows: list[dict[str, Any]] | None = None) -> None:
    sess = session(ctx)
    if sess.redact:
        data = redact(data)
        table_rows = redact(table_rows) if table_rows is not None else None
    fmt = detect_format(sess.fmt, sys.stdout.isatty())
    text = render(data, fmt, table_rows=table_rows)
    if text:
        typer.echo(text)


def main() -> None:
    app()


# Command modules register themselves on ``app``; imported last to avoid cycles.
from odoocli.cli import guide_cmd, profile_cmds, read_cmds, write_cmds  # noqa: E402,F401
