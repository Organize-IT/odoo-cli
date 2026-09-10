# Conditions

`-w` is repeatable and every condition is AND-ed. `--domain` takes a raw Odoo
domain and is AND-ed with the rest — use it when you need `OR`.

| `-w` | Odoo leaf |
|---|---|
| `is_company=true` | `["is_company", "=", true]` |
| `amount_total>=1000` | `["amount_total", ">=", 1000]` |
| `name~acme` | `["name", "ilike", "acme"]` |
| `name!~acme` | `["name", "not ilike", "acme"]` |
| `state in draft,sent` | `["state", "in", ["draft", "sent"]]` |
| `state not in draft,sent` | `["state", "not in", ["draft", "sent"]]` |
| `email=null` | `["email", "=", false]` |
| `partner_id.country_id.code=BE` | `["partner_id.country_id.code", "=", "BE"]` |
| `tag_ids in [1,2]` | `["tag_ids", "in", [1, 2]]` |
| `parent_id child_of 5` | `["parent_id", "child_of", 5]` |

## Values

Parsed in this order: a quoted string keeps its content verbatim;
`true`/`yes` become `true`; `false`/`no`/`null`/`none` become `false` (Odoo's
empty value); text starting with `[` or `{` is parsed as JSON; then integer,
then float; anything else stays text.

Quote when you mean text that looks like something else:

```bash
odoo search partners -w 'ref="42"'      # the string "42", not the number
```

## OR

```bash
odoo search partners --domain '["|", ["email", "!=", false], ["phone", "!=", false]]'
odoo search partners --domain '["|", ["city","=","Brussels"], ["city","=","Antwerp"]]' \
     -w is_company=true                 # AND-ed with the -w condition
```

## Presets

A bare word is looked up as a [preset](aliases.md#presets) for the model:

```bash
odoo search invoices -w overdue -w 'amount_residual>1000'
```

A bare word that is not a preset produces exit 2 listing the presets that do
apply, rather than a parse error.

## Ordering and paging

```bash
odoo search invoices --order "invoice_date_due, id" --limit 50 --offset 100
odoo search invoices --all --format jsonl > all.jsonl   # pages until exhausted
odoo search invoices --ids-only                          # ORM search, ids only
```

`--order` only accepts stored fields; so does `-w`. `odoo fields MODEL --stored`
lists them, and [validation](validation.md) warns when you use one that is not.
