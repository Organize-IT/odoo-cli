# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [0.2.0] - unreleased

### Added

- Odoo context on every call: `--context JSON`, `--include-archived` (`active_test=false`),
  `--company ID` (`allowed_company_ids`), `--lang CODE`. Library: `context=` on the clients,
  merged with a per-call `context=` keyword.
- Retry of network errors, timeouts and HTTP 5xx, limited to calls that cannot change data
  (`common.*`, read-safe ORM methods). HTTP 429 stays retried for every call.
- `--insecure` flag, `verify_ssl` on profiles (`odoo profile add --no-verify-ssl`) and
  `ODOO_VERIFY_SSL` for self-signed on-prem servers.
- `--debug`: one JSON line per RPC on stderr (method, id, duration, retries) through the
  `odoocli` logger hierarchy; the library logs on `odoocli.rpc`.
- `odoo search --ids-only` (ORM `search`) and `AsyncOdooClient.search()` / `OdooClient.search()`.
- `odoo read` exits 1 with `missing_record` when some ids are missing or not visible.
- `py.typed` marker; `Profile.api_key` is excluded from `repr`.
- Guide: x2many commands (`[0,0,{...}]`, `[4,id]`, `[6,0,[ids]]`), context and archived records.

### Changed

- Distribution renamed to `odoo-agent-cli` (PyPI rejects `odoocli` as too similar to the
  abandoned `odoo-cli`). Import name `odoocli` and binary `odoo` are unchanged.
- `max_retries_429` renamed to `max_retries` on the clients (unreleased API).

## [0.1.0] - 2026-09-03

Initial version: async and sync JSON-RPC clients, `odoo` CLI with profiles, guarded writes,
raw JSON output, `-w` domain DSL, opt-in field auto-repair, agent guide and `SKILL.md`,
mocked unit tests and live integration against Odoo 17, 18 and 19.
