# Connections

The CLI never prompts. It resolves a connection in this order and the first
match wins:

1. `--profile NAME` or `ODOO_PROFILE=NAME`
2. `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY`
3. a profile named `default`

Nothing found is exit code 3 with a message listing those three ways.

## Profiles

Profiles live in a TOML file written `0600` inside a `0700` directory.

```bash
odoo profile add acme --url https://acme.odoo.com --db acme \
     --login bot@acme.com --api-key-env ACME_ODOO_KEY --test
odoo profile list
odoo profile path
odoo -p acme search partners -w name~acme
```

`--api-key` stores the key in the file; `--api-key-env` stores only the name of
an environment variable to read it from, which is what you want on a shared
machine or in CI.

## Per-connection permissions

| Setting | Profile key | Environment | Effect |
|---|---|---|---|
| Writes | `allow_writes` | `ODOO_ALLOW_WRITES=1` | `create`, `write`, `unlink`, mutating `call` |
| Sensitive models | `allow_sensitive` | `ODOO_ALLOW_SENSITIVE=1` | `ir.config_parameter`, `ir.cron`, … |
| TLS | `verify_ssl` | `ODOO_VERIFY_SSL=0` | certificate verification |

Keep writes off on the profile that points at production and turn them on
explicitly, per command line, when you mean it.

## Context

Every call carries an Odoo context, composed from these flags:

| Option | Context key |
|---|---|
| `--lang fr_BE` | `lang` |
| `--company 3` | `allowed_company_ids` |
| `--include-archived` | `active_test = false` |
| `--context '{"...": ...}'` | merged first, so the flags above win |

## Environment variables

| Variable | Effect |
|---|---|
| `ODOO_URL`, `ODOO_DB`, `ODOO_LOGIN`, `ODOO_API_KEY` | connection |
| `ODOO_PROFILE` | named profile to use |
| `ODOO_CONFIG` | path to the profiles file |
| `ODOO_ALLOW_WRITES`, `ODOO_ALLOW_SENSITIVE`, `ODOO_ASSUME_YES` | lift a guard |
| `ODOO_VERIFY_SSL` | set to `0` to skip TLS verification |
| `ODOO_NO_VALIDATE` | skip [field validation](../guides/validation.md) |
| `ODOO_CACHE_DIR`, `ODOO_SCHEMA_TTL` | schema cache location and lifetime |
