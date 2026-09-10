# Writing

Writes are off by default. That is a property of the connection, not of the
command line: turn them on with `allow_writes = true` on the profile
(`odoo profile add ... --allow-writes`) or `ODOO_ALLOW_WRITES=1`.

```bash
odoo create crm.lead -v name="Website inquiry" -v partner_id=42 --dry-run
odoo create crm.lead -v name="Website inquiry" -v partner_id=42   # prints the new id
odoo write res.partner 42,43 -v active=false
odoo unlink res.partner 99 --yes
odoo call sale.order action_confirm --ids 12 --yes
odoo call res.partner name_search --args '["acme"]' --kwargs '{"limit": 5}'
```

## The guards

| Guard | Applies to | Lift with |
|---|---|---|
| Writes disabled | `create`, `write`, `unlink`, mutating `call` | `allow_writes` / `ODOO_ALLOW_WRITES=1` |
| Confirmation | `unlink`, `call` to a method outside the read-safe list | `--yes` / `ODOO_ASSUME_YES=1` |
| Sensitive model | `ir.config_parameter`, `ir.cron`, `ir.mail_server`, … | `--include-sensitive` / `allow_sensitive` |
| Filtered alias | `create`, `write`, `unlink`, `call` | use the technical model name |

A refused command exits 4 (or 2 for a filtered alias) **before making any
call**. The server is untouched.

## Dry runs

`--dry-run` prints the exact payload and exits 0 without writing anything:

```console
$ odoo create res.partner -v name=Acme -v is_company=true --dry-run
{"dry_run": true, "model": "res.partner", "method": "create",
 "args": [{"name": "Acme", "is_company": true}], "kwargs": {}}
```

It writes nothing, but it does read the model schema to check your field names,
so a typo is caught here too.

## Write logs

Every executed write puts one line on stderr, so a script that captured stdout
still has an audit trail:

```json
{"write": {"model": "res.partner", "method": "write", "ids": [42, 43], "fields": ["active"]}}
```

## Retries and duplicates

HTTP 429 is always retried. Network errors, timeouts and HTTP 5xx are retried
**only** for calls that cannot change data. A `create` that timed out is never
replayed, because it may well have been committed — you get the timeout, and
you decide.

## Arbitrary methods

`odoo call` reaches any model method through `execute_kw`. Methods in the
read-safe list (`search`, `read_group`, `name_search`, `fields_get`, …) need no
guard; everything else needs `allow_writes` and `--yes`.

```bash
odoo call account.move action_post --ids 501 --yes
odoo call product.product name_search --args '["desk"]' --kwargs '{"limit": 3}'
```
