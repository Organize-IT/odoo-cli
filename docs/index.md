# odoo-agent-cli

Odoo JSON-RPC command line tool and Python client, built for AI agents and
scripts.

```bash
odoo search invoices -w overdue --fields name,partner_id,amount_residual
```

stdout is data only, stderr is diagnostics, exit codes mean something, and
nothing writes to your ERP unless you switched writes on for that connection.

Extracted from the connector that powers [UpBoard.ai](https://upboard.ai). Not
affiliated with Odoo S.A.

## Why it exists

An agent driving Odoo over raw JSON-RPC spends most of its turns on things that
are not the task: finding the technical model name, discovering that a field is
computed and cannot be filtered on, parsing a server traceback to learn it
misspelled `mobile`. This tool removes those turns.

- **[Aliases](guides/aliases.md)** — `invoices` is `account.move` filtered on
  `move_type = out_invoice`, and `-w overdue` is a filter you no longer have to
  remember.
- **[Field validation](guides/validation.md)** — a misspelled field is caught
  locally, with the closest matches, before anything is sent.
- **[An output contract](guides/output-contract.md)** — one place to look for
  data, one place to look for errors, and exit codes you can branch on.
- **[Guards](guides/writes.md)** — writes off by default, confirmation for
  destructive calls, secrets redacted, sensitive models refused.

## Compatibility

Python 3.11+. Odoo 17, 18 and 19 are integration-tested in CI on every push to
`main`; anything exposing `/jsonrpc` with API keys (14+) should work.

## Where to go next

Install it and run [the first commands](getting-started/install.md), or read
`AGENTS.md` in the repository if you intend to change the tool rather than use
it.
