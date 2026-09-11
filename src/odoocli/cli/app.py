"""Typer application: global options, session, run/emit helpers, exit code mapping."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from collections.abc import Awaitable, Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

import typer
from typer.core import TyperGroup

from odoocli import aliases
from odoocli._version import __version__
from odoocli.cli.output import FORMATS, detect_format, render
from odoocli.client import AsyncOdooClient
from odoocli.config import ENV_ASSUME_YES, Profile, config_path, env_flag, resolve_profile
from odoocli.errors import OdooError, OdooRefusedError, OdooUsageError
from odoocli.schema import ENV_NO_VALIDATE, SchemaStore
from odoocli.schema import check as schema_check
from odoocli.security import is_sensitive_model, redact

T = TypeVar("T")

# Root options that may appear anywhere on the command line. Agents naturally
# write ``odoo search res.partner --format jsonl``; click only accepts group
# options before the subcommand, so we hoist them.
_GLOBAL_WITH_VALUE = {
    "--profile",
    "-p",
    "--format",
    "-f",
    "--timeout",
    "--context",
    "--company",
    "--lang",
}
_GLOBAL_FLAGS = {
    "--no-redact",
    "--include-sensitive",
    "--include-archived",
    "--insecure",
    "--no-validate",
    "--verbose",
    "--debug",
    "--version",
}


def hoist_global_options(args: list[str], value_options: frozenset[str] = frozenset()) -> list[str]:
    """Move root options found after the subcommand to the front, keeping order.

    ``value_options`` lists the options of the subcommand being invoked that
    consume the next token. Their values are copied through untouched, so
    ``--order --lang`` keeps ``--lang`` as the value of ``--order`` instead of
    stealing it for the root parser.
    """
    hoisted: list[str] = []
    rest: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--":
            rest.extend(args[i:])
            break
        name, eq, _value = tok.partition("=")
        is_global = tok in _GLOBAL_FLAGS or tok in _GLOBAL_WITH_VALUE
        if tok in value_options and not is_global and not eq:
            rest.extend(args[i : i + 2])
            i += 2
            continue
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
    def invoke(self, ctx: Any) -> object:
        """Map every OdooError to its exit code, not only those raised inside ``run()``.

        Offline commands (``alias``, ``cache``) never open a client, so without this they
        would escape as a traceback and exit 1 whatever the error said.
        """
        try:
            return super().invoke(ctx)
        except OdooError as e:
            session_obj = ctx.obj if isinstance(ctx.obj, Session) else None
            fail(e, bool(session_obj is not None and session_obj.verbose))
            raise  # unreachable: fail() raises typer.Exit

    def parse_args(self, ctx: Any, args: list[str]) -> list[str]:
        return super().parse_args(ctx, hoist_global_options(args, self._value_options(ctx, args)))

    def _value_options(self, ctx: Any, args: list[str]) -> frozenset[str]:
        """Option names of the invoked subcommand that take a value.

        Walks the command tree with the words of the command line; anything it
        cannot resolve yields an empty set, which is exactly the old behaviour.
        """
        names: set[str] = set()
        group: Any = self
        for tok in args:
            if tok.startswith("-"):
                continue
            try:
                command = group.get_command(ctx, tok)
            except Exception:  # noqa: BLE001 - resolution is best effort
                return frozenset()
            if command is None:
                return frozenset(names)
            for param in command.params:
                if getattr(param, "is_flag", False) or getattr(param, "nargs", 1) == 0:
                    continue
                names.update(param.opts or [])
                names.update(param.secondary_opts or [])
            if hasattr(command, "get_command"):  # a group: descend one level
                group = command
                continue
            break
        return frozenset(names)


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
    context: dict[str, Any] = field(default_factory=dict)
    verify_ssl: bool = True
    debug: bool = False
    validate: bool = True
    env: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    config: Path = field(default_factory=lambda: config_path(os.environ))
    _store: SchemaStore | None = field(default=None, repr=False, compare=False)
    _registry: aliases.Registry | None = field(default=None, repr=False, compare=False)

    def profile(self) -> Profile:
        return resolve_profile(self.profile_name, self.env, self.config)

    def registry(self) -> aliases.Registry:
        """Alias and preset tables, built-ins merged with anything the config file adds."""
        if self._registry is None:
            try:
                self._registry = aliases.from_config(self.config)
            except ValueError as e:
                raise OdooUsageError(f"{self.config}: {e}", code="invalid_alias_table") from e
        return self._registry

    def store(self, profile: Profile) -> SchemaStore:
        """Schema cache for this connection, created once per command."""
        if self._store is None:
            self._store = SchemaStore(
                profile.url, profile.database, env=self.env, enabled=self.validate
            )
        return self._store


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"odoo {__version__} (odoo-agent-cli)")
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
    context: str | None = typer.Option(
        None,
        "--context",
        help='Odoo context as JSON, e.g. \'{"lang": "fr_BE"}\'. Merged into every call.',
    ),
    include_archived: bool = typer.Option(
        False, "--include-archived", help="Also match archived records (context active_test=false)."
    ),
    company: int | None = typer.Option(
        None, "--company", help="Company id to operate in (context allowed_company_ids)."
    ),
    lang: str | None = typer.Option(None, "--lang", help="Language code for labels, e.g. fr_BE."),
    insecure: bool = typer.Option(
        False, "--insecure", help="Skip TLS certificate verification (self-signed on-prem)."
    ),
    no_validate: bool = typer.Option(
        False,
        "--no-validate",
        help="Do not check field names against the model schema before calling.",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Log every RPC call (method, id, duration, retries) as JSON on stderr.",
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
        context=build_context(context, include_archived, company, lang),
        verify_ssl=not insecure,
        debug=debug,
        validate=not (no_validate or env_flag(os.environ, ENV_NO_VALIDATE)),
    )


def build_context(
    context_json: str | None, include_archived: bool, company: int | None, lang: str | None
) -> dict[str, Any]:
    """Compose the Odoo context from the convenience flags; explicit JSON keys come first."""
    ctx: dict[str, Any] = {}
    if context_json:
        try:
            parsed = json.loads(context_json)
        except ValueError as e:
            raise typer.BadParameter(f"--context must be a JSON object: {e}") from e
        if not isinstance(parsed, dict):
            raise typer.BadParameter("--context must be a JSON object")
        ctx.update(parsed)
    if lang:
        ctx["lang"] = lang
    if company is not None:
        ctx["allowed_company_ids"] = [company]
    if include_archived:
        ctx["active_test"] = False
    return ctx


class _JsonLineFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "log": {
                    "level": record.levelname,
                    "logger": record.name,
                    "message": record.getMessage(),
                }
            },
            ensure_ascii=False,
        )


@contextlib.contextmanager
def debug_logging(enabled: bool) -> Iterator[None]:
    """Attach a JSON-lines stderr handler to the ``odoocli`` logger for one command."""
    if not enabled:
        yield
        return
    root = logging.getLogger("odoocli")
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonLineFormatter())
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
        handler.flush()


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


def _unknown_name(registry: aliases.Registry, name: str) -> OdooUsageError | None:
    """A name with no dot that is close to an alias is almost certainly a typo."""
    close = registry.suggest(name)
    if "." in name or not close:
        return None
    return OdooUsageError(
        f"{name!r} is neither an Odoo model nor an alias. Did you mean {close[0]!r}? "
        "Run 'odoo alias' for the list.",
        code="unknown_model",
        data={"suggestions": close},
    )


def read_target(registry: aliases.Registry, name: str) -> tuple[str, list[list[Any]]]:
    """Resolve a model name or alias for a read command, with its base clauses."""
    alias = registry.resolve(name)
    if alias is not None:
        return alias.model, alias.clauses()
    problem = _unknown_name(registry, name)
    if problem is not None:
        raise problem
    return name, []


def write_target(registry: aliases.Registry, name: str) -> str:
    """Resolve a model name for a write command. Filtered aliases are refused."""
    alias = registry.resolve(name)
    if alias is None:
        problem = _unknown_name(registry, name)
        if problem is not None:
            raise problem
        return name
    if alias.domain:
        clauses = ", ".join(f"{f} {o} {v}" for f, o, v in alias.domain)
        raise OdooUsageError(
            f"Alias {name!r} means {alias.model} filtered on {clauses}. Writing through it "
            f"would hide that filter, so use the technical name {alias.model!r} and set the "
            "field yourself.",
            code="alias_not_writable",
        )
    return alias.model


def check_model(sess: Session, profile: Profile, model: str) -> None:
    if is_sensitive_model(model) and not (sess.include_sensitive or profile.allow_sensitive):
        raise OdooRefusedError(
            f"Model {model!r} is sensitive (secrets or code execution). "
            "Pass --include-sensitive or set allow_sensitive = true on the profile.",
            code="sensitive_model",
        )


async def check_fields(
    sess: Session,
    client: AsyncOdooClient,
    profile: Profile,
    model: str,
    *,
    fields: list[str] | None = None,
    domain: list[Any] | None = None,
    order: str | None = None,
    values: list[str] | None = None,
) -> None:
    """Reject unknown field names before the real call; warn on unstored ones.

    Silently does nothing when the schema is unavailable or ``--no-validate``
    was passed: a wrong refusal costs more than a missing check.
    """
    if not sess.validate:
        return
    store = sess.store(profile)
    report = await schema_check(
        store, client, model, fields=fields, domain=domain, order=order, values=values
    )
    store.flush()
    report.raise_if_unknown()
    for path, context in report.not_stored:
        warn(
            {
                "warning": "field_not_stored",
                "field": path,
                "used_in": context,
                "message": (
                    f"{model}.{path} is computed and not stored: Odoo cannot filter or sort on it."
                ),
            }
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
            profile.url,
            profile.database,
            profile.login,
            profile.api_key,
            timeout=sess.timeout,
            verify_ssl=sess.verify_ssl and profile.verify_ssl,
            context=sess.context,
        ) as client:
            return await fn(client, profile)

    try:
        with debug_logging(sess.debug):
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
from odoocli.cli import (  # noqa: E402,F401
    alias_cmd,
    cache_cmds,
    guide_cmd,
    profile_cmds,
    read_cmds,
    write_cmds,
)
