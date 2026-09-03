# odoocli design (v0.1)

Decisions taken during the grilling session of 2026-09-03 with the founder.
This file is the contract the implementation plan argues from.

## What it is

`odoocli` is a Python package with two surfaces:

- a library: `odoocli.AsyncOdooClient` (httpx, async) and `odoocli.OdooClient`
  (thin sync wrapper), speaking Odoo JSON-RPC (`/jsonrpc`, services `common`
  and `object`, `execute_kw`);
- a binary: `odoo`, built for AI agents and scripts first, humans second.

It is extracted from UpBoard's `OdooConnector` / `OdooClient` but has no
dependency on UpBoard: no tenant, no database, no Redis, no quota, no cache.

## Decisions

| # | Decision |
|---|---|
| 1 | Audience: agents (Claude Code and similar) and scripts. Externalised, reusable across projects. |
| 2 | Separate repo. UpBoard keeps its own connector for now; a later lot makes UpBoard depend on this package. |
| 3 | Public, MIT. Repo `Organize-IT/odoo-cli`, PyPI `odoocli`, binary `odoo`. Not affiliated with Odoo S.A. |
| 4 | Connection resolution: `--profile` > `ODOO_PROFILE` > env `ODOO_URL/ODOO_DB/ODOO_LOGIN/ODOO_API_KEY` > profile `default`. No source resolved: refuse with exit code 3 and a message listing the three means. Never prompt. |
| 5 | Writes (`create`, `write`, `unlink`, `call` with a non read-safe method) exist only when the profile or env sets `allow_writes`. `unlink` and non read-safe `call` also need `--yes` (or `ODOO_ASSUME_YES=1`). `--dry-run` prints the payload and exits 0. Every executed write logs one JSON line on stderr. |
| 6 | Output: raw Odoo data, no envelope, never humanised. stdout is JSON when not a TTY, table when a TTY. `--format json\|jsonl\|table\|csv` forces. Errors: one JSON object on stderr. Exit codes: 0 ok, 1 Odoo error, 2 usage, 3 connection/auth, 4 refused (writes disabled, missing `--yes`, sensitive model). Sensitive field values redacted by default, `--no-redact` disables. |
| 7 | Domains: JSON (`--domain`) plus a mini DSL (`-w field=value`, repeated, AND-ed). Domain normalisation and de-humanisation of `Name (#id)` operands are ported. Field auto-repair is opt-in (`--lenient-fields`) and warns on stderr. Non-stored computed fields: error passed through, `odoo fields` exposes `store`. |
| 8 | Python 3.11+, `typer` + `rich` + `httpx`. Async core, sync wrapper on a private loop thread. Typed exceptions classified from the JSON-RPC error payload. `uv` for dev, `hatchling` build, PyPI trusted publishing on `v*` tags. |
| 9 | Agent onboarding: exhaustive `--help`, `SKILL.md` at repo root (Agent Skills format), `odoo agent-guide` prints the same guide from the packaged `AGENT_GUIDE.md`. A test asserts both copies are identical. English everywhere. |
| 10 | Tests: mocked JSON-RPC (`respx`) on every PR; integration against real `odoo:17.0`, `odoo:18.0`, `odoo:19.0` on `main`, tags and manual dispatch; integration runnable locally with `pytest -m integration` and `ODOO_*` env. |
| 11 | v0.1 scope below. Sensitive models blocked unless `--include-sensitive` or profile `allow_sensitive`. `ir.config_parameter` is treated as a sensitive model rather than redacted by value heuristics. |

## v0.1 scope

Library: `AsyncOdooClient(url, database, login, api_key, timeout=30, max_retries_429=3)`
with `version()`, `authenticate()`, `execute(model, method, *args, **kwargs)`,
`search_read`, `search_count`, `read`, `create`, `write`, `unlink`, `fields_get`,
`close()`, async context manager. `OdooClient` sync mirror.

CLI commands: `profile add|list|test|remove`, `info`, `models`, `fields`,
`search`, `count`, `read`, `create`, `write`, `unlink`, `call`, `agent-guide`.

Global options: `--profile/-p`, `--format/-f`, `--no-redact`, `--include-sensitive`,
`--timeout`, `--verbose/-v`, `--version`.

Out of scope for v0.1: cache, rate limiter, quotas, telemetry, session/password
login flows beyond the RPC `authenticate` slot, XML-RPC, bulk export beyond
`jsonl`, any tenant concept.

## Copy rules

No em-dash anywhere in user-facing strings, README or guide. English only.
