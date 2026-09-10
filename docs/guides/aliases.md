# Aliases and presets

Knowing that "unpaid customer invoices" means `account.move` filtered on
`move_type = out_invoice` and `payment_state = not_paid` is Odoo knowledge, not
information the caller has. Aliases and presets put that knowledge in the tool.

Both are pure sugar. They expand to an ordinary domain before anything is sent,
they never change the shape of the result, and the technical model name always
keeps working.

```bash
odoo alias                      # every alias, its model and its filter
odoo alias invoices --presets   # the presets that apply to that model
```

Neither command needs a connection.

## Aliases

```bash
odoo search invoices --fields name,amount_residual
# same as
odoo search account.move -w move_type=out_invoice --fields name,amount_residual
```

A few of the mappings:

| Alias | Model | Filter |
|---|---|---|
| `partners`, `contacts` | `res.partner` | |
| `customers` | `res.partner` | `customer_rank > 0` |
| `suppliers`, `vendors` | `res.partner` | `supplier_rank > 0` |
| `invoices` | `account.move` | `move_type = out_invoice` |
| `bills` | `account.move` | `move_type = in_invoice` |
| `credit-notes` | `account.move` | `move_type = out_refund` |
| `orders`, `sales` | `sale.order` | |
| `quotes` | `sale.order` | `state in draft, sent` |
| `opportunities` | `crm.lead` | `type = opportunity` |
| `products` | `product.template` | |
| `pickings`, `transfers` | `stock.picking` | |

`odoo alias` prints the full list.

## Presets

A preset is a named condition, usable wherever `-w` is accepted:

```bash
odoo count invoices -w overdue
odoo search orders -w confirmed --fields name,amount_total
odoo search partners -w archived
```

| Preset | Applies to | Means |
|---|---|---|
| `overdue` | `account.move` | unpaid and past its due date |
| `unpaid`, `paid` | `account.move` | on `payment_state` |
| `draft`, `posted`, `cancelled` | `account.move`, `sale.order`, `purchase.order` | on `state` |
| `this-month`, `this-year` | `account.move` | on `invoice_date` |
| `confirmed` | `sale.order` | `state = sale` |
| `ready`, `done` | `stock.picking` | on `state` |
| `archived`, `active` | any model | on `active` |

Presets that mention a date are resolved against today when the command runs.

## Writes refuse filtered aliases

```console
$ odoo create invoices -v name=X
{"error": {"code": "alias_not_writable", "message": "Alias 'invoices' means account.move filtered on move_type = out_invoice. Writing through it would hide that filter, so use the technical name 'account.move' and set the field yourself."}}
$ echo $?
2
```

Creating a record through a name that silently sets a discriminator field is
how a vendor bill ends up filed as a customer invoice. Aliases without a filter
— `partners`, `products` — are accepted by write commands.

## Adding one

Aliases and presets live in `src/odoocli/aliases.py`. The bar for adding one is
in `AGENTS.md`: it has to be a name an agent would plausibly use, and its
clauses have to be true on a stock Odoo 17 through 19. If a field it filters on
moved between versions, it does not go in.
