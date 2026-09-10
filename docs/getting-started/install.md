# Install

```bash
uv tool install odoo-agent-cli   # or: pipx install odoo-agent-cli
odoo --version
```

The distribution is `odoo-agent-cli`; the command is `odoo` and the import name
is `odoocli`.

## The first minute

```bash
export ODOO_URL=https://mycompany.odoo.com ODOO_DB=mycompany \
       ODOO_LOGIN=bot@mycompany.com ODOO_API_KEY=...   # API key or password

odoo info                                  # version, uid, connection source
odoo alias                                 # the names you can use for models
odoo models --like invoice                 # find a technical name instead
odoo fields account.move --stored          # what you can filter and order on
odoo count invoices -w overdue
odoo search invoices -w overdue --fields name,partner_id,amount_residual \
     --order "invoice_date_due" --limit 20
odoo group invoices -w unpaid --by partner_id --sum amount_residual
```

## Creating an API key

In Odoo: *Preferences → Account Security → New API Key*. Copy it once; Odoo
does not show it again. A password works too but is discouraged — an API key
can be revoked without locking the user out.

## Requirements for the API user

Reading needs nothing special. Writing needs the relevant application groups.
`odoo info` tells you which user you authenticated as; `odoo fields MODEL`
fails with exit 1 and an `access_error` if that user cannot see the model at
all.
