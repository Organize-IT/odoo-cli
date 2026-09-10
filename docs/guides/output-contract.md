# Output contract

This is the part a script depends on. It does not change without a major
version.

| Situation | stdout | stderr | exit |
|---|---|---|---|
| piped or captured | raw Odoo JSON (`--format json` by default) | | 0 |
| terminal | table (`--format table`); `jsonl` and `csv` available | | 0 |
| Odoo raised | | `{"error": {"code", "message", "odoo": {...}}}` | 1 |
| bad arguments, unknown field | | `{"error": ...}` | 2 |
| connection, auth, no profile | | `{"error": ...}` | 3 |
| refused by a guard | | `{"error": ...}` | 4 |
| write executed | result | `{"write": {"model", "method", "ids", "fields"}}` | 0 |

Three consequences worth stating outright:

- **stdout carries data and nothing else.** No banners, no progress, no
  warnings. `odoo count invoices` prints an integer and a newline.
- **Every diagnostic is one JSON object per line on stderr.** Warnings, write
  logs and errors are all parseable without splitting on prose.
- **Exit codes never change meaning.** Branch on them:

```bash
if ! ids=$(odoo search invoices -w overdue --ids-only); then
  case $? in
    2) echo "my query was wrong" ;;
    3) echo "cannot reach Odoo" ;;
    4) echo "a guard refused it" ;;
  esac
fi
```

## Data is never humanised

Many2one fields stay `[id, "name"]`. Empty values stay `false`, not `null` and
not `""`. Dates stay strings in Odoo's format. Nothing is renamed, coerced or
flattened.

The table renderer abbreviates for humans — a many2one shows as
`Acme (#42)` — but `--format json` never does. If you are parsing the output,
pipe it or pass `--format json`.

## Redaction

Values of fields whose name contains `password`, `api_key`, `secret`,
`private_key`, `totp_secret` and similar are replaced by `[redacted]`. This is
the one exception to the rule above, and `--no-redact` lifts it.

## Formats

| Format | Use |
|---|---|
| `json` | default when piped; the source of truth |
| `jsonl` | one record per line — the right choice with `--all` |
| `table` | default on a terminal |
| `csv` | spreadsheets; nested values are JSON-encoded in the cell |
