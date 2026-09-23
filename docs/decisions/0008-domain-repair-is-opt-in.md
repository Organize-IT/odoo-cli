# 8. The library does not remove a filter unless asked

**Status:** accepted — narrows the library side of [ADR 0007](0007-a-repaired-query-is-not-a-success.md)

## Context

ADR 0007 made a repaired query widen rather than narrow, and made the CLI exit 5 after one.
The exit code is what tells a caller the rows answer a wider question. The library function
behind the flag, `lenient_search_read`, had no equivalent: it reported each removal through an
optional `on_warning` callback and returned the rows as if nothing had happened.

A caller that did not pass the callback, or logged it and moved on, got a wrong answer that
looked right. On Odoo 15 `account.account` has no `account_type`. A search for
`account_type = asset_cash` lost that leaf, was replayed with an empty domain, and returned
every account in the chart; a cash total built on it summed receivables, payables and equity
without any error being raised.

Removing a field from `fields` or `order` is a different kind of repair. It changes the shape
of the rows or their order, never which records come back, and the caller sees the missing key.

## Decision

`lenient_search_read` takes `strip_domain: bool = False`.

- A rejected field in `fields` or `order` is removed and the query replayed, as before.
- A rejected field that appears in the domain raises `OdooFieldMissingError` (`.model`,
  `.field`, `.where = "domain"`, code `field_missing`) before any replay, whether Odoo said
  the field is invalid or that it is not stored.
- With `strip_domain=True` the domain is repaired as in ADR 0007: it only widens, and the
  removal is reported through `on_warning`.

The CLI's `--lenient-fields` passes `strip_domain=True`. Its behaviour does not change: the
command already turns every removal into exit 5, which is the signal the library lacked.

The error exits 2 if it ever reaches the CLI, the code for an unknown field.

## Consequences

- A library caller asking a question the server cannot answer gets an exception naming the
  field, and decides: pick a version-aware field, filter in Python, or opt into the wider
  query knowingly.
- This is a breaking change for library callers that relied on the silent widening. They add
  `strip_domain=True` to get it back; the version moves to 0.6.0.
- The domain check is exact on path segments. The previous substring test would now raise on
  a missing `type` whenever the domain mentioned `move_type`.

## What would change our mind

If callers turned out to pass `strip_domain=True` almost everywhere, and handle the widening
themselves, the default would be the wrong way round and would flip back, keeping the error
as the opt-in. If the domain repair turned out to be wanted only by the CLI, the parameter
would go and the CLI would do its own stripping.
