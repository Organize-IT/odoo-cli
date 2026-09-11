# 2. stdout is data, and exit codes are an API

**Status:** accepted

## Context

The tool is driven non-interactively by something that cannot ask a follow-up question. A
banner on stdout, a warning mixed into the records, or an exit code that means "something
happened" are all the same bug from the caller's point of view: they turn a machine-readable
answer into prose to be parsed.

## Decision

stdout carries data and nothing else. Every diagnostic — warnings, write logs, errors — is one
JSON object per line on stderr. Exit codes are part of the interface and never change meaning:
0 ok, 1 Odoo raised, 2 bad arguments, 3 connection or authentication, 4 refused by a guard,
5 the query was repaired (ADR 0007).

## Consequences

- `odoo search ... > file` produces a file containing only records.
- A caller can branch on `$?` without reading a message.
- Adding a code is a contract change: it needs an ADR saying why none of the existing ones fit.
- Every command must map its failures onto that table, which is why the mapping lives at the
  Typer group level rather than inside the helper that opens a client.

## What would change our mind

Nothing. This is the property that makes the tool usable by a program at all.
