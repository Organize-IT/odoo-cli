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
odoo models --like invoice                 # find the right technical name
odoo fields account.move --stored          # what you can filter and order on
odoo count account.move -w move_type=out_invoice -w payment_state=not_paid
odoo search account.move -w move_type=out_invoice -w invoice_date_due<2026-09-01 \
     --fields name,partner_id,amount_residual --order "invoice_date_due" --limit 20
```

Prefer named connections? They live in a `0600` TOML file:

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
(`--api-key`) or points to an env var (`--api-key-env`). `odoo profile path` shows the file.

## Output contract

| Situation | stdout | stderr | exit |
|---|---|---|---|
| piped / captured | raw Odoo JSON (`--format json` by default) | | 0 |
| terminal | table (`--format table`), `jsonl` and `csv` available | | 0 |
| Odoo raised | | `{"error": {"code", "message", "odoo": {...}}}` | 1 |
| bad arguments | | `{"error": ...}` | 2 |
| connection, auth, no profile | | `{"error": ...}` | 3 |
| refused by a guard | | `{"error": ...}` | 4 |
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

## Writes

Off by default. Enable per connection with `allow_writes = true` on the profile
(`odoo profile add ... --allow-writes`) or `ODOO_ALLOW_WRITES=1`.

```bash
odoo create crm.lead -v name="Website inquiry" -v partner_id=42 --dry-run   # shows payload, exit 0
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
- `odoo search ... --lenient-fields` removes fields Odoo rejects and retries, with a warning on
  stderr. Exploration only.

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
uv run pytest                        # unit tests, mocked JSON-RPC
uv run ruff check && uv run mypy

ODOO_VERSION=17.0 scripts/start-odoo.sh                     # throwaway Odoo in Docker
ODOO_URL=http://localhost:8069 ODOO_DB=test ODOO_LOGIN=admin ODOO_API_KEY=admin \
ODOO_ALLOW_WRITES=1 uv run pytest -m integration -o addopts=""
docker compose -f docker/odoo-compose.yml down -v
```

CI runs the unit suite on every PR and the integration matrix (Odoo 17.0, 18.0, 19.0) on
`main`, tags and manual dispatch. Releases are published to PyPI on `v*` tags through
trusted publishing.

## License

MIT. Odoo is a trademark of Odoo S.A.; this project is independent.
