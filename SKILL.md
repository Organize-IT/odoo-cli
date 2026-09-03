---
name: odoo-cli
description: Use when a task needs to read or change data in an Odoo ERP (partners, invoices, orders, stock, any model) through the `odoo` command line tool from the odoocli package. Covers connection setup, domain syntax, guarded writes, output contract and version-drift pitfalls.
---

# odoo CLI guide for AI agents

`odoo` talks to one Odoo database over JSON-RPC. It is built so that a program can drive it:
stdout is data only, stderr is diagnostics, exit codes mean something.

## Connection

Resolution order, first match wins:

1. `--profile NAME` or `ODOO_PROFILE=NAME`, defined with
   `odoo profile add NAME --url https://... --db DB --login USER --api-key KEY`
2. Environment: `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY`
3. A profile named `default`

Nothing resolved: exit code 3 and a message listing these three ways. The CLI never prompts.
`ODOO_API_KEY` accepts an Odoo API key (preferred) or the user's password.
Check a connection with `odoo info`.

## Output contract

- Piped or captured: raw Odoo JSON, exactly what `search_read`, `read` or `fields_get` return.
  Many2one fields are `[id, "display name"]`, empty values are `false`, never `null`.
- On a terminal: a table. Force a format with `--format json|jsonl|table|csv`.
  Use `--format jsonl` for large result sets.
- Errors: one JSON object on stderr, `{"error": {"code": ..., "message": ..., "odoo": {...}}}`.
- Warnings and write logs: one JSON object per line on stderr.
- Exit codes: `0` ok, `1` Odoo raised, `2` bad usage, `3` connection or authentication,
  `4` refused by a guard (writes disabled, missing `--yes`, sensitive model).
- Values of fields named like `password`, `api_key`, `secret` are replaced by `[redacted]`
  unless `--no-redact`.

## Read commands

```
odoo info [--modules]                       server version, uid, optional installed modules
odoo models [--like sale]                   list models (technical name, label)
odoo fields MODEL [--type many2one] [--stored] [--search text] [--all-attributes]
odoo search MODEL [-w COND]... [--domain JSON] [--fields a,b] [--limit N] [--offset N]
                  [--order "x desc"] [--all] [--lenient-fields]
odoo count MODEL [-w COND]... [--domain JSON]
odoo read MODEL ID [ID...] [--fields a,b]
```

Conditions (`-w`, repeatable, AND-ed together, combined with `--domain`):

```
-w is_company=true         -w amount_total>=1000      -w name~acme        (ilike)
-w name!~test              -w state in draft,sent     -w state not in done,cancel
-w email=null              -w partner_id.country_id.code=BE
-w tag_ids in [1,2]        -w parent_id child_of 5
```

For OR, use `--domain` with Odoo prefix notation: `--domain '["|",["a","=",1],["b","=",2]]'`.

## Write commands

Writes only exist when the profile has `allow_writes = true` or `ODOO_ALLOW_WRITES=1`.
Otherwise exit 4.

```
odoo create MODEL -v name=Acme -v is_company=true [--values JSON] [--dry-run]
odoo write MODEL IDS -v field=value... [--values JSON] [--dry-run]
odoo unlink MODEL IDS --yes [--dry-run]
odoo call MODEL METHOD [--ids 1,2] [--args JSON] [--kwargs JSON] [--yes] [--dry-run]
```

- `--dry-run` prints the exact payload and exits 0 without calling Odoo. Use it first.
- `unlink` and any `call` to a non read-only method need `--yes` (or `ODOO_ASSUME_YES=1`).
- `call` on read-only methods (`name_search`, `read_group`, `default_get`, ...) needs
  neither `allow_writes` nor `--yes`.
- Every executed write logs one line on stderr:
  `{"write": {"model": ..., "method": ..., "ids": [...], "fields": [...]}}`.

## Working method that avoids most failures

1. Unknown model? `odoo fields MODEL` first. It shows `type`, `required`, `store`, `relation`
   and `selection` values.
2. Only filter or order on fields with `store: true`. Computed non-stored fields
   (`qty_available`, `amount_to_invoice`, ...) can be read but not searched; Odoo answers
   "Cannot convert ... to SQL". Read them and filter client-side.
3. `odoo count` before a wide `odoo search`. Default `--limit` is 80. `--all` paginates
   everything; prefer `--format jsonl` with it.
4. Ask only for the fields you need with `--fields`. `search` without `--fields` returns
   every field, which is slow and noisy.
5. Many2one values come back as `[id, name]`. Filter on them with the id
   (`-w partner_id=42`) or through a related field (`-w partner_id.name~acme`).
6. Dates are strings, `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` in UTC.
7. Field names drift between Odoo 17, 18 and 19 (for example `account.account.company_id`
   became `company_ids`). If a field is rejected, `odoo fields` is the truth.
   `--lenient-fields` on `search` removes rejected fields and retries, with a warning on
   stderr; only use it for exploration, never in a script that relies on the result.
8. Never guess a model name: `odoo models --like invoice`.
9. Sensitive models (`ir.config_parameter`, `ir.mail_server`, `res.users.apikeys`, `ir.cron`,
   `ir.actions.server`, ...) are refused unless `--include-sensitive`.

## Recipes

```
odoo search res.partner -w is_company=true -w country_id.code=BE --fields name,email,vat --limit 20
odoo search sale.order -w state=sale -w date_order>=2026-01-01 --fields name,partner_id,amount_total --order "amount_total desc"
odoo count account.move -w move_type=out_invoice -w payment_state=not_paid -w invoice_date_due<2026-09-01
odoo search product.product --fields name,qty_available --all --format jsonl | jq -c 'select(.qty_available < 0)'
odoo call res.partner name_search --args '["acme"]' --kwargs '{"limit": 5}'
odoo call account.move read_group --kwargs '{"domain": [["move_type","=","out_invoice"]], "fields": ["amount_total:sum"], "groupby": ["partner_id"]}'
odoo create crm.lead -v name="Website inquiry" -v partner_id=42 --dry-run
odoo call sale.order action_confirm --ids 12 --yes
```
