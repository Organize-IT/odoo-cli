# 5. Field validation may reject only what it has read

**Status:** accepted

## Context

A misspelled field used to cost a round trip and come back as a server exception an agent had
to parse. Reading `fields_get` once per model and checking names locally removes that. But a
check that is wrong is worse than no check: the caller cannot argue with a refusal, and a tool
that rejects a valid field is a tool people disable.

## Decision

Validation rejects only a name it has positively read from the server. When the schema cannot
be read — no access to the model, an old server, a network hiccup, a path traversing something
it does not understand — it stays silent and lets the real call produce the real error.
`--no-validate` disables it entirely.

The cache is keyed by URL and database and expires after 24 hours. It is **not** invalidated by
probing the server version, because that probe would cost a round trip on every command and
defeat the cache it protects. `odoo cache clear` is the explicit answer after an upgrade or a
module install.

## Consequences

- The check can never produce a false refusal, only a missed one.
- Up to a day of drift is possible after an upgrade, which the README says plainly.
- Unstored fields used in a filter or an order produce a warning rather than a refusal, because
  `fields_get` does not reliably say whether a custom `search=` makes them usable.

## What would change our mind

If Odoo exposed a cheap schema fingerprint, keying the cache on it would remove the TTL
entirely.
