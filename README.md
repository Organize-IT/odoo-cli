# odoo-agent-cli

Odoo JSON-RPC command line tool and Python client, built for AI agents and scripts.

`odoo search res.partner -w is_company=true --fields name,email` prints exactly what Odoo
returns. stdout is data only, stderr is diagnostics, exit codes mean something, and nothing
writes to your ERP unless you switched writes on for that connection.

Extracted from the connector that powers [UpBoard.ai](https://upboard.ai). Not affiliated with
Odoo S.A.

## Install

```bash
uv tool install odoo-agent-cli   # or: pipx install odoo-agent-cli
odoo --version
```

Requires Python 3.11+. Works with Odoo 17, 18 and 19 (integration-tested in CI), and should
work with any version exposing `/jsonrpc` with API keys (14+).

## 60 seconds

```bash
export ODOO_URL=https://mycompany.odoo.com ODOO_DB=mycompany \
       ODOO_LOGIN=bot@mycompany.com ODOO_API_KEY=...   # API key or password

odoo info                                  # version, uid, connection source
odoo alias                                 # business names for models, and presets
odoo models --like invoice                 # or find the technical name yourself
odoo fields account.move --stored          # what you can filter and order on
odoo count invoices -w overdue
odoo search invoices -w overdue \
     --fields name,partner_id,amount_residual --order "invoice_date_due" --limit 20
odoo group invoices -w unpaid --by partner_id --sum amount_residual
```

`invoices` is `account.move` filtered on `move_type = out_invoice`, and `overdue` is
`payment_state = not_paid` past its due date. Both expand to an ordinary domain before
anything is sent, and the technical names keep working. Full documentation:
[Organize-IT.github.io/odoo-cli](https://github.com/Organize-IT/odoo-cli/tree/main/docs).

Prefer named connections? They live in a TOML file written owner-only where the platform
can enforce that — `odoo profile path --check` says whether it can:

```bash
odoo profile add acme --url https://acme.odoo.com --db acme --login bot@acme.com \
     --api-key-env ACME_ODOO_KEY --test
odoo -p acme search res.partner -w name~acme
```

## Connection resolution

First match wins, and the CLI never prompts:

1. `--profile NAME` or `ODOO_PROFILE=NAME`
2. `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY`
3. a profile named `default`

Nothing found: exit code 3 with a message listing those three ways. A profile stores the key
(`--api-key`) or points to an env var (`--api-key-env`). `odoo profile path` shows the file,
`--check` reports what its permissions are actually worth: mode 600 means owner-only on
POSIX and nothing at all on Windows, where `chmod` only toggles a read-only attribute. On
such a platform, prefer `--api-key-env` and keep the key in your secret manager.

## Output contract

| Situation | stdout | stderr | exit |
|---|---|---|---|
| piped / captured | raw Odoo JSON (`--format json` by default) | | 0 |
| terminal | table (`--format table`), `jsonl` and `csv` available | | 0 |
| Odoo raised | | `{"error": {"code", "message", "odoo": {...}}}` | 1 |
| bad arguments | | `{"error": ...}` | 2 |
| connection, auth, no profile | | `{"error": ...}` | 3 |
| refused by a guard | | `{"error": ...}` | 4 |
| query repaired to run | rows | `{"error": ...}` | 5 |
| write executed | result | `{"write": {"model", "method", "ids", "fields"}}` | 0 |

Data is never humanised: many2one fields stay `[id, "name"]`, empty values stay `false`.
Values of fields named like `password`, `api_key`, `secret` are `[redacted]` unless
`--no-redact`. Global options are accepted anywhere on the command line:

| Option | Effect |
|---|---|
| `--profile/-p NAME`, `--format/-f FMT`, `--timeout S` | connection, output, per-call timeout |
| `--include-archived` | context `active_test=false`: searches also return archived records |
| `--company ID`, `--lang CODE`, `--context JSON` | Odoo context merged into every call |
| `--insecure` | skip TLS verification (self-signed on-prem) |
| `--no-redact`, `--include-sensitive` | lift the two output/model guards |
| `--no-validate` | skip the field-name check against the model schema |
| `--debug` | one JSON line per RPC on stderr (method, id, duration, retries) |
| `--verbose` | include Odoo's server traceback in error output |

## Conditions

`-w` is repeatable and AND-ed; `--domain` takes a raw Odoo domain (use it for OR).

| `-w` | Odoo leaf |
|---|---|
| `is_company=true` | `["is_company", "=", true]` |
| `amount_total>=1000` | `["amount_total", ">=", 1000]` |
| `name~acme` / `name!~acme` | `["name", "ilike", "acme"]` / `not ilike` |
| `state in draft,sent` | `["state", "in", ["draft", "sent"]]` |
| `email=null` | `["email", "=", false]` |
| `partner_id.country_id.code=BE` | `["partner_id.country_id.code", "=", "BE"]` |
| `tag_ids in [1,2]` | `["tag_ids", "in", [1, 2]]` |
| `parent_id child_of 5` | `["parent_id", "child_of", 5]` |

Values: `true/false/null`, integers, floats, JSON lists or objects, quoted strings, else text.

A bare word is looked up as a preset for the model: `-w overdue`, `-w unpaid`, `-w draft`,
`-w confirmed`, `-w archived`. `odoo alias MODEL --presets` lists the ones that apply. A bare
word that is not a preset exits 2 listing the ones that are.

## Your own names

The shipped table covers what most tenants call things. A profile file adds the rest, and a
user entry replaces a built-in of the same name — your tenant knows its vocabulary better than
this tool does:

```toml
[aliases.subscriptions]
model = "sale.subscription"
domain = [["stage_category", "=", "progress"]]
help = "Running subscriptions"

[aliases.invoices]                     # replaces the built-in
model = "account.move"
domain = [["move_type", "=", "out_invoice"], ["company_id", "=", 3]]

[presets.mine]
domain = [["user_id", "=", 7]]
models = ["crm.lead", "sale.order"]
```

`odoo alias` marks each entry `builtin` or `config`. A malformed table fails the command with
exit 2 instead of being skipped: a filter you believe is applied and is not is exactly what
this mechanism exists to avoid. Dynamic dates work too — `@today`, `@month-start`, `@year-start`.

## Names and typos

Read commands accept an alias in place of a technical model name (`invoices`, `customers`,
`quotes`, `pickings`, ...); `odoo alias` prints the table and needs no connection. Write
commands refuse an alias that carries a filter, so a vendor bill cannot be filed as a
customer invoice by accident.

Field names are checked against the model schema before the call, which costs nothing after
the first lookup:

```console
$ odoo search partners -w mobil=+32
{"error": {"code": "unknown_field", "message": "res.partner has no field 'mobil'. Did you mean 'mobile'? (also: phone)"}}
$ echo $?
2
```

`fields_get` is read once per model and cached under `~/.cache/odoo-cli` for 24 hours
(`odoo cache path|list|clear`, `ODOO_CACHE_DIR`, `ODOO_SCHEMA_TTL`). Dotted paths are
followed across relations. A computed non-stored field used in `-w` or `--order` warns on
stderr rather than failing. Validation only rejects a name it has positively read from the
server: when the schema is unreadable it stays quiet, so it can never refuse wrongly.
`--no-validate` or `ODOO_NO_VALIDATE=1` turns it off.

## Aggregates

```bash
odoo group invoices -w overdue --by partner_id --sum amount_residual \
     --order "amount_residual desc" --limit 10
odoo group invoices --by invoice_date:month --sum amount_total
```

`read_group` under the hood: counts and totals per group without pulling the records.

## Writes

Off by default. Enable per connection with `allow_writes = true` on the profile
(`odoo profile add ... --allow-writes`) or `ODOO_ALLOW_WRITES=1`.

```bash
odoo create crm.lead -v name="Website inquiry" -v partner_id=42 --dry-run   # payload only, exit 0
odoo create crm.lead -v name="Website inquiry" -v partner_id=42             # prints the new id
odoo write res.partner 42,43 -v active=false
odoo unlink res.partner 99 --yes                                            # --yes required
odoo call sale.order action_confirm --ids 12 --yes                          # any method
odoo call res.partner name_search --args '["acme"]' --kwargs '{"limit": 5}' # read-only: no guard
```

`unlink` and any `call` to a non read-only method need `--yes` or `ODOO_ASSUME_YES=1`.
Sensitive models (`ir.config_parameter`, `ir.mail_server`, `res.users.apikeys`, `ir.cron`, ...)
are refused unless `--include-sensitive`.

## For AI agents

- `odoo agent-guide` prints the working method, pitfalls (non-stored fields, version drift,
  many2one shapes) and recipes.
- The same text ships as an [Agent Skill](https://github.com/Organize-IT/odoo-cli/blob/main/SKILL.md):
  `npx skills add Organize-IT/odoo-cli`.
- `odoo search ... --lenient-fields` removes fields Odoo rejects and retries. It prints the
  rows, then exits **5**: they answer a wider question than the one you asked. Exploration
  stays comfortable; a script that checks its exit codes cannot be fooled by it.

## Library

The distribution is `odoo-agent-cli`; the import name is `odoocli`.

```python
from odoocli import OdooClient

with OdooClient("https://acme.odoo.com", "acme", "bot@acme.com", "api-key") as odoo:
    overdue = odoo.search_read(
        "account.move",
        [["move_type", "=", "out_invoice"], ["payment_state", "=", "not_paid"]],
        ["name", "partner_id", "amount_residual"],
        limit=50,
        order="invoice_date_due",
    )
```

```python
from odoocli import AsyncOdooClient, OdooAccessError

async with AsyncOdooClient(url, db, login, key) as odoo:
    try:
        new_id = await odoo.create("res.partner", {"name": "Acme"})
    except OdooAccessError as e:
        print(e.code, e.message, e.data)
```

Exceptions: `OdooError` (base, `.code`, `.message`, `.data`), `OdooConnectionError`,
`OdooAuthError`, `OdooAccessError`, `OdooValidationError`, `OdooMissingError`.

Both clients accept `context={...}` (merged into every call; a per-call `context=` keyword
wins), `verify_ssl=False` and `max_retries`. HTTP 429 is always retried with backoff and
`Retry-After`; network errors, timeouts and HTTP 5xx are retried only for calls that cannot
change data, so a `create` that timed out is never replayed. Logs go to the `odoocli.rpc`
logger. Domain helpers live in `odoocli.domain`, guards in `odoocli.security`, the opt-in
repair loop in `odoocli.lenient`.

## Development

```bash
uv sync --group dev
uvx pre-commit install               # ruff, mypy and hygiene hooks on commit
uv run pytest                        # unit tests, mocked JSON-RPC
uv run ruff check && uv run mypy
uv run pytest --cov --cov-report=term-missing   # gated at 93% in CI
uv run --group docs mkdocs serve     # the documentation site

ODOO_VERSION=17.0 scripts/start-odoo.sh                     # throwaway Odoo in Docker
ODOO_URL=http://localhost:8069 ODOO_DB=test ODOO_LOGIN=admin ODOO_API_KEY=admin \
ODOO_ALLOW_WRITES=1 uv run pytest -m integration -o addopts=""
docker compose -f docker/odoo-compose.yml down -v
```

CI runs the unit suite on Python 3.11-3.13 and builds the docs on every PR; the integration
matrix (Odoo 17.0, 18.0, 19.0) runs on `main`, tags and manual dispatch. Releases are
published to PyPI on `v*` tags through trusted publishing, with every action pinned to a
commit digest.

`AGENTS.md` is the specification: layering, the contracts that may not change silently, and
the definition of done. [docs/decisions/](docs/decisions/) records the decisions with a real
trade-off behind them. Read both before changing anything.

## License

MIT. Odoo is a trademark of Odoo S.A.; this project is independent.
