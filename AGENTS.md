# odoo-agent-cli — specification

This file is the authority on how this project behaves and how it is changed.
When the README, a docstring or an implementation disagrees with it, this file
wins and the other is a bug. Read it before touching anything.

## Mission

One command-line tool, and the Python client under it, that lets an AI agent or
a shell script read and write an Odoo database over JSON-RPC without knowing
anything about JSON-RPC, and without ever damaging the database by accident.

The tool is used non-interactively, mostly by something that cannot ask a
follow-up question. Every design decision below follows from that.

## Non-goals

- An ORM, or a typed model layer over Odoo's business objects. The output is
  Odoo's own JSON. See "The raw data rule".
- Support for every Odoo model through hand-written code. Aliases are sugar
  over model names, not a domain layer.
- XML-RPC, database management (`db.create`, `db.drop`), or the web session
  API. `/jsonrpc` with an API key only.
- Anything interactive. The CLI never prompts, never reads stdin for
  confirmation, never opens a pager.

## Layers

Dependencies point downwards only. A module never imports from a layer above it.

```
cli/            app, read_cmds, write_cmds, alias_cmd, cache_cmds, profile_cmds, guide_cmd
                Typer commands, exit codes, stdout/stderr, rendering
─────────────────────────────────────────────────────────────────────────────
schema, lenient, aliases, domain, security, config
                query building, guards, validation, profiles
─────────────────────────────────────────────────────────────────────────────
sync            OdooClient: blocking mirror of the async client
client          AsyncOdooClient: /jsonrpc, retries, context merging
errors          the exception hierarchy everything else raises
```

Rules that follow:

- `client.py` never reads the environment, never prints, never formats for
  humans. It logs to the `odoocli.rpc` logger and raises `OdooError`.
- `config.py` is the only library module allowed to read environment variables.
- Everything that reaches stdout goes through `cli/output.py`.
- `errors.py` imports nothing from the package.

## Invariants

These are contracts. Changing one is a breaking change and needs a major
version, a CHANGELOG entry and a README update in the same commit.

### The output contract

| Situation | stdout | stderr | exit |
|---|---|---|---|
| success, piped | raw Odoo JSON | | 0 |
| success, terminal | table | | 0 |
| Odoo raised | | `{"error": {...}}` | 1 |
| bad arguments, unknown field | | `{"error": {...}}` | 2 |
| connection, auth, no profile | | `{"error": {...}}` | 3 |
| refused by a guard | | `{"error": {...}}` | 4 |
| query repaired to run (`--lenient-fields`) | rows | `{"error": {...}}` | 5 |

stdout carries data and nothing else — no banners, no progress, no warnings.
Every diagnostic is one JSON object per line on stderr. An exit code never
changes meaning; a new failure mode reuses the closest existing code.

### The raw data rule

Data returned by Odoo is passed through untouched. Many2one fields stay
`[id, "name"]`, empty values stay `false`, dates stay strings. The table
renderer may abbreviate for humans; `--format json` never does. No layer
invents, renames, coerces or reshapes a field.

The single exception is redaction: values of fields whose name matches
`SENSITIVE_FIELD_PATTERNS` are replaced by `[redacted]` unless `--no-redact`.

### Retries are idempotent or absent

HTTP 429 is always retried: Odoo rejected the request before running it.
Network errors, timeouts and HTTP 5xx are retried **only** for calls that
cannot change data — `common.*` and the methods in `READ_SAFE_METHODS`. A
`create` that timed out may well have been committed, and replaying it would
duplicate a record. Any new client method must pass the right `retryable` to
`_rpc`; any new read-only ORM method belongs in `READ_SAFE_METHODS`.

### Guards fire before any RPC

`require_writes`, `require_yes` and `check_model` run before the command makes
its first call, so a refused command leaves the server untouched. Ordering
inside a command body: resolve the target, check the model, parse arguments,
apply write guards, validate fields, then call.

Writes are off unless the connection says otherwise. `unlink` and any `call` to
a method outside `READ_SAFE_METHODS` need `--yes` on top.

### A repaired result is not a successful one

`--lenient-fields` exists because Odoo's field names drift between versions and exploring a
strange tenant otherwise means a round trip per typo. It removes what the server rejects and
retries — which means the rows it returns answer a *wider* question than the one asked.

It prints those rows, because they are real and useful, and then exits 5. Nothing else in
this tool returns data that does not match the request, and nothing else may: a query that
silently loses a filter is how a batch operates on the wrong records.

### Validation never invents a refusal

`schema.py` may only reject a field name it has positively read from the
server. If `fields_get` fails, the model is unknown, the path traverses
something it does not understand, or `--no-validate` was passed, it returns "no
opinion" and the call proceeds. A wrong refusal is worse than a missing check,
because the caller cannot argue with it.

### Aliases never hide a filter from a write

A read command may resolve `invoices` to `account.move` plus
`move_type = out_invoice`. A write command resolves the model name only, and
refuses outright any alias that carries clauses (`alias_not_writable`, exit 2).
Creating a record through a name that silently sets a discriminator field is
how you get a vendor bill filed as a customer invoice.

## Adding things

**A command.** Put reads in `cli/read_cmds.py`, writes in `cli/write_cmds.py`.
Follow the body ordering above. Parsing that can raise `OdooUsageError` goes
*inside* the `go()` coroutine so `run()` maps it to exit 2. Return data and let
`emit()` render it; never call `typer.echo` with data yourself.

**An alias.** Only for a model an agent would plausibly name in English, and
only with clauses that are true on a stock Odoo 17 through 19. If a field it
filters on moved between versions, do not add it. Add a live assertion to
`tests/integration/test_live.py`.

**A preset.** Same bar. Scope it with `models=` unless it genuinely applies to
anything. Dynamic dates use the `@today` / `@month-start` / `@year-start`
sentinels so tests can inject a date.

Both tables are merged with `[aliases]` and `[presets]` from the profile file at
the start of every command; a user entry of the same name replaces the built-in.
A malformed user entry raises rather than being skipped, because a filter the
caller believes is applied and is not is the failure the whole mechanism exists
to avoid. Built-in tables are reached through `aliases.BUILTIN`; everything that
resolves a name at runtime takes a `Registry` instead.

**A client method.** Add it to `AsyncOdooClient`, mirror it in `OdooClient`
with the same parameter list — `tests/test_cli_parsing.py` fails otherwise —
and decide its retry safety explicitly.

## Definition of done

A change is finished when all of these are true:

1. `uv run ruff check && uv run ruff format --check` is clean.
2. `uv run mypy` is clean. The codebase is `strict`; no new `Any` escaping into
   a public signature, no `# type: ignore` without a comment saying why.
3. `uv run pytest` passes and coverage stays at or above 93%.
4. New behaviour has a test that would fail without the change. Guard and
   refusal paths are tested for what they *do not* call, not only for the exit
   code.
5. The README documents anything a user can type, and `AGENT_GUIDE.md` anything
   an agent should know.
6. `CHANGELOG.md` has an entry under the unreleased heading.
7. Anything touching version-specific Odoo behaviour has a live assertion in
   `tests/integration/test_live.py`, which runs against 17, 18 and 19.

## Testing

Unit tests mock JSON-RPC with `respx` through the `fake_odoo` fixture and never
reach a network. They are the fast gate and cover argument parsing, guards,
rendering and error mapping.

They cannot tell you whether a field still exists in Odoo 19. That is what the
integration suite is for: it runs the real CLI as a subprocess against a real
Odoo in Docker, on 17.0, 18.0 and 19.0, on `main` and on tags. Anything that
depends on Odoo's own surface — a model name, a field, an ORM method, an error
message we parse — belongs there as well as in the unit suite.

`tests/conftest.py` redirects the schema cache to a temporary directory for
every test. Never let a test write to the user's real cache or config.

## Security posture

- Secrets never reach stdout: `redact()` runs on everything `emit()` prints.
- Secrets never reach logs: `--debug` logs method names, ids and durations, not
  arguments.
- The profile file is written atomically, owner-only, inside an owner-only directory. The
  temporary file is *created* with mode 600 rather than created and then chmod-ed, so a
  permissive umask never leaves the API key in a world-readable file. `chmod` carries that
  meaning on POSIX and none on Windows: `permissions_enforced()` says which, `odoo profile
  path --check` reports it, and no document may claim the stronger one unconditionally.
- `SENSITIVE_MODELS` are refused by default because reading them leaks secrets
  or writing them executes code.
- CI actions are pinned to commit digests and workflows default to
  `contents: read`. The publish workflow uses trusted publishing; no token is
  stored in the repository or in secrets.
