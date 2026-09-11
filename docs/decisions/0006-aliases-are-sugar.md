# 6. Aliases and presets are sugar, and never reach a write

**Status:** accepted

## Context

Knowing that "unpaid customer invoices" means `account.move` filtered on `move_type` and
`payment_state` is Odoo knowledge the caller does not have. Naming it removes a research step
from every task. But a name that carries a hidden filter is dangerous in the other direction:
creating a record through `invoices` without `move_type` files a vendor bill as a customer
invoice.

## Decision

Aliases and presets expand to an ordinary domain before anything is sent. The result keeps
exactly the same shape, and the technical model name always works. Read commands accept them;
write commands resolve the model name only and refuse outright any alias carrying clauses.

A profile file may add its own tables, and an entry of the same name replaces the built-in. A
malformed user entry raises rather than being skipped.

## Consequences

- `odoo search invoices -w overdue` and the explicit domain produce identical output.
- A tenant's own vocabulary is a config change, not a pull request.
- The shipped table has to stay conservative: its clauses must be true on Odoo 17 through 19,
  verified by the live suite.

## What would change our mind

If alias definitions started encoding real logic rather than a filter, they would have outgrown
being sugar and would need to become something explicit and testable instead.
