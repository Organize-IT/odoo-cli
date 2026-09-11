# 3. Retries never replay a write

**Status:** accepted

## Context

Odoo rate-limits, occasionally answers 5xx, and often sits behind a proxy. Retrying is
necessary. But a `create` that timed out may well have been committed, and replaying it makes a
second record.

## Decision

HTTP 429 is always retried: Odoo rejected the request before running it. Network errors,
timeouts and HTTP 5xx are retried only for calls that cannot change data — `common.*` and the
methods in `READ_SAFE_METHODS`. Everything else is reported, never repeated.

## Consequences

- A write that times out surfaces as an error the operator has to resolve, which is honest:
  only they can check whether it landed.
- Any new client method has to declare its retry safety explicitly.
- A read-only ORM method that is missing from `READ_SAFE_METHODS` is merely not retried, which
  is the safe direction to be wrong in.

## What would change our mind

An idempotency key on Odoo's side would let writes be retried safely. `/jsonrpc` offers none.
