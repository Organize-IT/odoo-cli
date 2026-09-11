# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow SemVer.

## [0.5.0] - 2026-09-11

### Fixed

- `strip_field_from_domain` could narrow a query instead of widening it, so
  `--lenient-fields` silently dropped records the caller had asked for.
  `["|", ["mobile", "!=", false], ["phone", "!=", false]]` repaired of `mobile` became
  `[["phone", "!=", false]]`, losing every partner reachable by mobile and not by phone; under
  `!` the repaired domain matched a disjoint set. A removed leaf now means "matches everything"
  and the domain is simplified properly: an always-true operand absorbs a disjunction, and a
  negation mentioning the field is dropped whole. Found by the property tests added in this
  release. See [ADR 0007](docs/decisions/0007-a-repaired-query-is-not-a-success.md).
- The README and `AGENTS.md` promised the profile file is written `0600` inside a `0700`
  directory, unconditionally. On Windows `os.chmod` only toggles a read-only attribute, so the
  stored API key was as readable as any other file in the user's profile directory. The claim is
  now qualified, `odoo profile path --check` reports what the permissions are actually worth, and
  a platform that cannot enforce them says so and points at `--api-key-env`.
- The profile file's temporary copy is *created* with mode 600 instead of created and then
  chmod-ed: a permissive umask used to leave a window in which the API key sat in a
  world-readable file. A failed write no longer leaves the temporary behind.
- `OdooError` is mapped to its exit code at the Typer group level, not only inside `run()`.
  Offline commands (`alias`, `cache`) never open a client, so an error in one escaped as a
  traceback and exited 1 whatever it said.

### Changed

- **`--lenient-fields` now exits 5** after printing its rows, listing the fields it had to
  remove: they answer a wider question than the one that was asked. Interactive exploration is
  unchanged; a script that checks exit codes can no longer be told a repaired query succeeded.
  `5` is a new exit code — see the output contract in the README.

### Added

- `[aliases]` and `[presets]` in the profile file. A tenant defines its own names, and an entry
  of the same name replaces the built-in. A malformed entry fails the command with exit 2 rather
  than being skipped; `odoo alias` marks every row `builtin` or `config`. Dynamic dates
  (`@today`, `@month-start`, `@year-start`) work in user presets too.
- `odoo profile path --check`: the file's actual mode and whether this platform can enforce it.
- Property-based tests over the domain algebra, checked against a small domain evaluator: every
  record the original matched must still match after a repair, the result stays well formed,
  stripping is idempotent, and no leaf on the removed field survives.
- Seven ADRs under [docs/decisions/](docs/decisions/), each ending with what would change our
  mind.

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
