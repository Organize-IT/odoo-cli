# For AI agents

```bash
odoo agent-guide       # the packaged guide: conventions, pitfalls, recipes
npx skills add Organize-IT/odoo-cli
```

The same text ships as an [Agent Skill](https://github.com/Organize-IT/odoo-cli/blob/main/SKILL.md).

## Why this tool suits an agent

- **One place to look for data, one for errors.** stdout is data; stderr is one
  JSON object per line. No prose to parse.
- **Exit codes that mean something.** 2 is your mistake, 3 is the connection, 4
  is a guard. See the [output contract](output-contract.md).
- **Mistakes are caught locally.** A misspelled field costs no round trip and
  comes back with the closest matches.
- **Business names.** `odoo search invoices -w overdue` instead of recalling
  that `payment_state` exists on `account.move`.
- **No prompts, ever.** Nothing blocks waiting for input.

## Working method

1. `odoo info` — confirm the connection and the server version.
2. `odoo alias` — check whether the object you want already has a name.
   Otherwise `odoo models --like <word>` for the technical one.
3. `odoo fields MODEL --stored` — what you can filter and order on. Odoo's
   field names differ between versions and between installed modules; do not
   assume.
4. `odoo count ...` before `odoo search ...`, so you know what you are about to
   pull.
5. Read with `--fields`. Never fetch every field of every record.

## Pitfalls

- **Non-stored fields** cannot be filtered or sorted on. You get a
  `field_not_stored` warning on stderr; believe it.
- **Many2one fields come back as `[id, "name"]`.** Compare on the id.
- **Empty is `false`**, not `null` and not `""`. `-w email=null` is the way to
  test it.
- **Version drift is real.** A field that exists on Odoo 17 may not exist on
  19. `odoo fields` is the truth; the cache behind it holds for 24 hours, and
  `odoo cache clear` refreshes it.
- **`--all` can be very large.** Pair it with `--format jsonl` and a `--fields`
  list.
- **`--lenient-fields` is for exploration only.** It drops fields Odoo rejects
  and retries, warning on stderr. Never leave it in a script: a query that
  silently loses a filter returns the wrong rows, not an error.

## Recipes

```bash
# What is overdue, per customer
odoo group invoices -w overdue --by partner_id --sum amount_residual \
     --order "amount_residual desc" --limit 10

# The overdue invoices themselves
odoo search invoices -w overdue \
     --fields name,partner_id,invoice_date_due,amount_residual \
     --order invoice_date_due --limit 50

# Does this contact already exist
odoo count partners -w 'email=jane@example.com'

# Everything, streamed
odoo search partners --all --format jsonl --fields id,name,email > partners.jsonl

# Confirm a quotation
odoo call sale.order action_confirm --ids 12 --yes
```
