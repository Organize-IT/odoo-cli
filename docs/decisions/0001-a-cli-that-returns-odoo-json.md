# 1. A CLI that returns Odoo's own JSON

**Status:** accepted

## Context

Odoo exposes thousands of models across versions and installed modules. Wrapping them in typed
methods is endless work that ages with every release and produces something only a Python
programme can use. Most of what this tool is asked to do — find overdue invoices, export a
model, confirm an order — is a shell task, often driven by an agent that has a shell and not a
REPL.

## Decision

Ship a command-line tool whose output is what Odoo returned. Many2one fields stay
`[id, "name"]`, empty values stay `false`, dates stay strings. Nothing is renamed, coerced or
reshaped. Expose the client as a library, but build no typed model layer.

## Consequences

- Every model works on day one, including the ones a tenant's custom modules add.
- Callers get dictionaries. The vendor's field names, including their inconsistencies, are the
  vocabulary; an IDE cannot complete them.
- A typo is caught by the schema check (ADR 0005), not by an editor.
- Version drift shows up as data rather than as a broken import.

## What would change our mind

If a handful of models carried most of the traffic and their payloads kept biting us, wrapping
those few — on top of the generic layer, never instead of it — would be worth the cost.
