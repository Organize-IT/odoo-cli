# Field validation

A misspelled field name used to cost a round trip and come back as a server
exception. Now it costs nothing and comes back with the answer:

```console
$ odoo search partners -w mobil=+32
{"error": {"code": "unknown_field", "message": "res.partner has no field 'mobil'. Did you mean 'mobile'? (also: phone)"}}
$ echo $?
2
```

Nothing was sent to Odoo.

## What is checked

Every field name a command is about to use: the ones in `-w` conditions, in
`--fields`, in `--order`, in `-v` values on `create` and `write`, and the
grouping and aggregate fields of `odoo group`.

Dotted paths are followed across relations, and the error names the model where
the path actually broke:

```console
$ odoo search partners -w country_id.cod=BE
{"error": {"code": "unknown_field", "message": "res.country has no field 'cod' (in 'country_id.cod'). Did you mean 'code'?"}}
```

## Computed fields

A field that is computed and not stored cannot be filtered or sorted on — Odoo
rejects it with a message that takes a while to interpret. Using one in `-w` or
`--order` produces a warning on stderr and the call still goes out:

```json
{"warning": "field_not_stored", "field": "credit", "used_in": "domain",
 "message": "res.partner.credit is computed and not stored: Odoo cannot filter or sort on it."}
```

`odoo fields MODEL --stored` lists what you *can* filter and order on.

## It never invents a refusal

Validation only rejects a name it has positively read from the server. If the
schema cannot be read — the API user cannot see the model, the server is older
than expected, the network hiccups — it stays quiet and the real call produces
the real error. A wrong refusal would be worse than a missing check, because
the caller cannot argue with it.

Turn it off entirely with `--no-validate` or `ODOO_NO_VALIDATE=1`.

## The cache

Field definitions are read once per model with `fields_get` and cached under
`~/.cache/odoo-cli`, keyed by URL and database. Entries expire after 24 hours.

```bash
odoo cache path     # the file for the current connection
odoo cache list     # models held, and their age
odoo cache clear    # after installing a module or upgrading Odoo
```

| Variable | Effect |
|---|---|
| `ODOO_CACHE_DIR` | where the file lives |
| `ODOO_SCHEMA_TTL` | lifetime in seconds; `0` disables the disk cache |

Clear it after an upgrade or a module install, or accept up to a day of drift.
