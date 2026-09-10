# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [0.4.0] - 2026-09-10

### Added

- Field validation before the call. `fields_get` is read once per model, cached under
  `~/.cache/odoo-cli` for 24 hours, and every field name used in `-w`, `--fields`,
  `--order`, `-v` and `--by` is checked locally. An unknown name exits 2 with the closest
  matches and nothing is sent; dotted paths are followed across relations and the error
  names the model where the path broke. A computed non-stored field used in `-w` or
  `--order` produces a `field_not_stored` warning on stderr. Disable with `--no-validate`
  or `ODOO_NO_VALIDATE=1`; manage the cache with `odoo cache path|list|clear` and
  `ODOO_CACHE_DIR` / `ODOO_SCHEMA_TTL`.
- Model aliases on read commands: `odoo search invoices` is `account.move` filtered on
  `move_type = out_invoice`. Presets usable wherever `-w` is accepted: `-w overdue`,
  `-w unpaid`, `-w confirmed`, `-w archived`. `odoo alias [NAME] [--presets]` lists both
  without a connection. Write commands refuse an alias that carries a filter
  (`alias_not_writable`, exit 2).
- `odoo group MODEL --by FIELD [--sum FIELDS] [--avg FIELDS]`: `read_group` with aliases,
  presets and validation, so counts and totals per group no longer need `odoo call`.
  Grouping keys accept a date granularity (`--by invoice_date:month`).
- MkDocs site (getting started, six guides, mkdocstrings reference), built `--strict` in CI.
- `AGENTS.md`: the authoritative specification of layering, contracts and definition of
  done. `CONTRIBUTING.md` and a pull request template.

### Fixed

- Global option hoisting no longer steals a subcommand's value: `--order --lang` keeps
  `--lang` as the value of `--order`. The mover now asks the invoked command which of its
  options consume the next token.
- Write guards run before any RPC, so a refused write leaves the server untouched.

### Changed

- `--dry-run` writes nothing, as before, but now reads the model schema to validate the
  payload. It no longer claims to call nothing at all.
- CI: actions pinned to commit digests, `contents: read` by default,
  `persist-credentials: false`, coverage gated at 93%, dependabot and pre-commit added.

## [0.3.0] - 2026-09-04

### Added

- `odoocli.domain.dehumanize_operand` is public: turns `"Name (#42)"` back into `42`
  (recursing into lists). `_dehumanize` stays as a compatibility alias until 1.0.

## [0.2.0] - 2026-09-03

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
