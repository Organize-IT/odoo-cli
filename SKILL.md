---
name: odoo-cli
description: Use when a task needs to read or change data in an Odoo ERP (partners, invoices, orders, stock, any model) through the `odoo` command line tool from the odoo-agent-cli package (import name odoocli). Covers connection setup, domain syntax, guarded writes, output contract and version-drift pitfalls.
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
`odoo profile path --check` says whether the stored key is really owner-only on this
platform; on Windows it is not, so prefer `--api-key-env` there.
`ODOO_API_KEY` accepts an Odoo API key (preferred) or the user's password.
Check a connection with `odoo info`. Self-signed on-prem server: `--insecure`
(or `odoo profile add ... --no-verify-ssl`).

## Context: archived records, company, language

Odoo hides archived records (`active = false`) from every search unless the context says
otherwise, and multi-company data depends on the company in context. These global flags
work on every command:

```
--include-archived        context active_test=false: search also returns archived records
--company 3               context allowed_company_ids=[3]
--lang fr_BE              labels and selection values in that language (must be installed
                          in Odoo: 18+ answers "Invalid language code" otherwise)
--context '{"tz": "Europe/Brussels"}'   any other key, merged with the flags above
```

## Business names instead of technical ones

Read commands accept an alias in place of a model name, and a preset name in place of a
condition. Both expand to an ordinary domain before anything is sent, so the result has
exactly the same shape.

```
odoo alias                    every alias, its model and its filter (no connection needed)
odoo alias invoices --presets the presets that apply to that model
```

```
odoo search invoices -w overdue      same as
odoo search account.move -w move_type=out_invoice -w payment_state=not_paid \
                         -w invoice_date_due<TODAY
```

Aliases include `partners`, `customers`, `suppliers`, `invoices`, `bills`, `credit-notes`,
`orders`, `quotes`, `opportunities`, `products`, `pickings`, `users`, `employees`, `tasks`.
Presets include `overdue`, `unpaid`, `paid`, `draft`, `posted`, `cancelled`, `confirmed`,
`this-month`, `this-year`, `ready`, `done`, and `archived` / `active` on any model.

Write commands refuse an alias that carries a filter (exit 2, `alias_not_writable`): use the
technical name and set the discriminator field yourself, so a vendor bill cannot be filed as
a customer invoice by accident.

## Field names are checked before the call

A misspelled field costs no round trip. The CLI reads the model schema once with
`fields_get`, caches it for 24 hours, and checks every name used in `-w`, `--fields`,
`--order`, `-v` and `--by`:

```
$ odoo search partners -w mobil=+32
{"error": {"code": "unknown_field", "message": "res.partner has no field 'mobil'.
 Did you mean 'mobile'? (also: phone)"}}      exit 2, nothing was sent
```

Dotted paths are followed across relations, and the error names the model where the path
actually broke. Using a computed non-stored field in `-w` or `--order` produces a
`field_not_stored` warning on stderr and the call still goes out.

Validation only ever rejects a name it has positively read from the server: if the schema
cannot be read, it stays quiet. Turn it off with `--no-validate` or `ODOO_NO_VALIDATE=1`.
Refresh it after a module install or an Odoo upgrade with `odoo cache clear`.

## Output contract

- Piped or captured: raw Odoo JSON, exactly what `search_read`, `read` or `fields_get` return.
  Many2one fields are `[id, "display name"]`, empty values are `false`, never `null`.
- On a terminal: a table. Force a format with `--format json|jsonl|table|csv`.
  Use `--format jsonl` for large result sets.
- Errors: one JSON object on stderr, `{"error": {"code": ..., "message": ..., "odoo": {...}}}`.
- Warnings and write logs: one JSON object per line on stderr.
- Exit codes: `0` ok, `1` Odoo raised, `2` bad usage, `3` connection or authentication,
  `4` refused by a guard (writes disabled, missing `--yes`, sensitive model), `5` the query
  was repaired to make it run, so the rows answer a wider question than the one you asked.
- Values of fields named like `password`, `api_key`, `secret` are replaced by `[redacted]`
  unless `--no-redact`.

## Read commands

```
odoo info [--modules]                       server version, uid, optional installed modules
odoo models [--like sale]                   list models (technical name, label)
odoo fields MODEL [--type many2one] [--stored] [--search text] [--all-attributes]
odoo search MODEL [-w COND]... [--domain JSON] [--fields a,b] [--limit N] [--offset N]
                  [--order "x desc"] [--all] [--ids-only] [--lenient-fields]
odoo count MODEL [-w COND]... [--domain JSON]
odoo read MODEL ID [ID...] [--fields a,b]
odoo group MODEL --by FIELD[,FIELD] [--sum a,b] [--avg a,b] [-w COND]... [--limit N]
odoo alias [NAME] [--presets]               aliases and presets, offline
odoo cache path|list|clear                  the schema cache
```

`MODEL` accepts an alias on every read command. `odoo group` runs `read_group`, so you
get counts and totals per group without pulling the records:
`odoo group invoices -w overdue --by partner_id --sum amount_residual`.
Grouping keys accept a date granularity: `--by invoice_date:month`.

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

- `--dry-run` prints the exact payload and exits 0 without writing anything. It does read
  the model schema to check your field names, so a typo is caught there too. Use it first.
- `unlink` and any `call` to a non read-only method need `--yes` (or `ODOO_ASSUME_YES=1`).
- `call` on read-only methods (`name_search`, `read_group`, `default_get`, ...) needs
  neither `allow_writes` nor `--yes`.
- Every executed write logs one line on stderr:
  `{"write": {"model": ..., "method": ..., "ids": [...], "fields": [...]}}`.

One2many and many2many fields take Odoo commands, written as JSON in `-v` or `--values`:

```
-v 'order_line=[[0,0,{"product_id":7,"product_uom_qty":2}]]'   create a line
-v 'tag_ids=[[4,12]]'                                           link id 12
-v 'tag_ids=[[6,0,[12,13]]]'                                    replace with ids 12 and 13
-v 'tag_ids=[[3,12]]'                                           unlink id 12 (keep record)
-v 'order_line=[[2,55]]'                                        delete line 55
```

## Working method that avoids most failures

1. Unknown model? Try `odoo alias` first, then `odoo models --like word`. Then
   `odoo fields MODEL`, which shows `type`, `required`, `store`, `relation` and `selection`
   values.
2. Only filter or order on fields with `store: true`. Computed non-stored fields
   (`qty_available`, `amount_to_invoice`, ...) can be read but not searched; Odoo answers
   "Cannot convert ... to SQL". Read them and filter client-side.
3. `odoo count` before a wide `odoo search`. Default `--limit` is 80. `--all` paginates
   everything; prefer `--format jsonl` with it. `--ids-only` when you only need ids.
4. Ask only for the fields you need with `--fields`. `search` without `--fields` returns
   every field, which is slow and noisy.
5. Many2one values come back as `[id, name]`. Filter on them with the id
   (`-w partner_id=42`) or through a related field (`-w partner_id.name~acme`).
6. Dates are strings, `YYYY-MM-DD` or `YYYY-MM-DD HH:MM:SS` in UTC.
7. Field names drift between Odoo 17, 18 and 19 (for example `account.account.company_id`
   became `company_ids`). If a field is rejected, `odoo fields` is the truth.
   `--lenient-fields` on `search` removes rejected fields and retries. It prints the rows and
   then exits 5, because they answer a wider question than the one you asked. Use it to
   explore; if you keep it in a script, check the exit code.
8. Never guess a model name: `odoo alias`, then `odoo models --like invoice`. A dotless
   name close to a known alias is reported as a typo instead of being sent.
9. Sensitive models (`ir.config_parameter`, `ir.mail_server`, `res.users.apikeys`, `ir.cron`,
   `ir.actions.server`, ...) are refused unless `--include-sensitive`.
10. A record you know exists but cannot find is usually archived (`--include-archived`) or in
    another company (`--company`). `odoo read` exits 1 with `missing_record` in that case.
11. Something odd on the wire? `--debug` logs every RPC call (method, duration, retries) as
    JSON lines on stderr. Network errors and HTTP 5xx are retried for reads only; a write that
    timed out is reported, never replayed.

## Recipes

```
odoo search customers -w country_id.code=BE --fields name,email,vat --limit 20
odoo count invoices -w overdue
odoo group invoices -w overdue --by partner_id --sum amount_residual --order "amount_residual desc" --limit 10
odoo group invoices --by invoice_date:month --sum amount_total
odoo search res.partner -w is_company=true -w country_id.code=BE --fields name,email,vat --limit 20
odoo search sale.order -w state=sale -w date_order>=2026-01-01 --fields name,partner_id,amount_total --order "amount_total desc"
odoo count account.move -w move_type=out_invoice -w payment_state=not_paid -w invoice_date_due<2026-09-01
odoo search product.product --fields name,qty_available --all --format jsonl | jq -c 'select(.qty_available < 0)'
odoo call res.partner name_search --args '["acme"]' --kwargs '{"limit": 5}'
odoo call account.move read_group --kwargs '{"domain": [["move_type","=","out_invoice"]], "fields": ["amount_total:sum"], "groupby": ["partner_id"]}'
odoo create crm.lead -v name="Website inquiry" -v partner_id=42 --dry-run
odoo call sale.order action_confirm --ids 12 --yes
odoo call sale.order action_cancel --ids 12 --yes --context '{"disable_cancel_warning": true}'
odoo search res.partner -w name~acme --include-archived --ids-only
```
