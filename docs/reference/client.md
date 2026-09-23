# Python client

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

async with AsyncOdooClient(url, db, key_owner, key) as odoo:
    try:
        new_id = await odoo.create("res.partner", {"name": "Acme"})
    except OdooAccessError as e:
        print(e.code, e.message, e.data)
```

Both clients accept `context={...}` (merged into every call; a per-call
`context=` keyword wins), `verify_ssl=False`, `timeout=` and `max_retries=`.
Logs go to the `odoocli.rpc` logger.

Query helpers live in `odoocli.domain`, guards in `odoocli.security`, the
schema cache in `odoocli.schema`, aliases and presets in `odoocli.aliases`, and
the repair loop in `odoocli.lenient`. `lenient_search_read` drops a rejected
field from `fields` and `order` on its own; a rejected field in the domain
raises `OdooFieldMissingError` unless `strip_domain=True` is passed, because
removing a filter widens the query (see ADR 0008).

::: odoocli.client.AsyncOdooClient

::: odoocli.sync.OdooClient
