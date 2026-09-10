# Commands

Global options are accepted anywhere on the command line, before or after the
subcommand.

| Option | Effect |
|---|---|
| `--profile/-p NAME` | named connection |
| `--format/-f FMT` | `json`, `jsonl`, `table`, `csv` |
| `--timeout S` | seconds per RPC call |
| `--include-archived` | context `active_test=false` |
| `--company ID`, `--lang CODE`, `--context JSON` | merged into every call |
| `--insecure` | skip TLS verification |
| `--no-redact`, `--include-sensitive` | lift an output or model guard |
| `--no-validate` | skip [field validation](../guides/validation.md) |
| `--debug` | one JSON line per RPC on stderr |
| `--verbose` | include Odoo's traceback in error output |

## Reading

| Command | Purpose |
|---|---|
| `odoo info [--modules]` | server version, uid, connection source |
| `odoo models [--like TEXT]` | technical model names |
| `odoo fields MODEL [--stored] [--type T] [--search TEXT]` | field types, storage, relations |
| `odoo search MODEL [-w …] [--fields …] [--order …] [--limit N] [--all] [--ids-only]` | `search_read` |
| `odoo count MODEL [-w …]` | `search_count`, prints an integer |
| `odoo read MODEL IDS [--fields …]` | records by id |
| `odoo group MODEL --by F [--sum F] [--avg F] [-w …]` | `read_group` |

`MODEL` accepts an [alias](../guides/aliases.md) on every read command.

## Writing

| Command | Guards |
|---|---|
| `odoo create MODEL -v k=v [--values JSON] [--dry-run]` | writes |
| `odoo write MODEL IDS -v k=v [--dry-run]` | writes |
| `odoo unlink MODEL IDS --yes` | writes, confirmation |
| `odoo call MODEL METHOD [--ids …] [--args JSON] [--kwargs JSON] [--yes]` | writes and confirmation unless read-safe |

## Housekeeping

| Command | Purpose |
|---|---|
| `odoo profile add\|list\|test\|remove\|path` | named connections |
| `odoo alias [NAME] [--presets]` | aliases and presets, offline |
| `odoo cache path\|list\|clear` | the schema cache |
| `odoo agent-guide` | the packaged guide for AI agents |
