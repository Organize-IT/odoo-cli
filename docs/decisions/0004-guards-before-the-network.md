# 4. Writes are off until a connection says otherwise

**Status:** accepted

## Context

The realistic accident is not exotic: the right command against the wrong profile. An agent
exploring a production database should not be one `create` away from changing it, and a
confirmation prompt does not help a tool that is mostly used non-interactively.

## Decision

Writes require `allow_writes` on the connection. `unlink` and any `call` to a method outside
`READ_SAFE_METHODS` additionally require `--yes`. Models holding secrets or executing code are
refused unless `--include-sensitive`. `--dry-run` prints the payload and sends nothing. All of
it is evaluated before the first RPC, so a refused command leaves the server untouched.

## Consequences

- Writing to production takes a deliberate configuration step, which is friction on purpose.
- A refused write makes no call at all — including the schema read, which is why the guards run
  before validation.
- Values of fields named like a secret are masked on the way out whatever the guards say.

## What would change our mind

Nothing foreseeable. Per-command limits (refuse an `unlink` over N records without a second
flag) would be an addition, not a change.
