# 7. A repaired query prints its rows and exits 5

**Status:** accepted — supersedes the original behaviour of `--lenient-fields`

## Context

Odoo field names drift between versions and modules, so exploring an unfamiliar tenant used to
cost a round trip per typo. `--lenient-fields` removes whatever the server rejects and retries.
It warned on stderr and exited 0.

That made it the one place in this tool where the output could be wrong while everything looked
fine. A script that checked its exit code was told the query succeeded, holding records that no
longer matched a filter it had asked for.

Worse, the removal itself could narrow the result. Stripping a leaf out of
`["|", a, b]` left `b`, dropping every record that matched only `a`; under `!`, weakening the
operand strengthened the whole expression.

## Decision

Two rules.

**A repair may only widen.** A removed leaf becomes "matches everything" and the domain is
simplified properly: an always-true operand absorbs a disjunction rather than collapsing it,
and a negation mentioning the field is dropped whole. Every record the original domain matched
still matches afterwards.

**A repair is not a success.** The rows are printed, because they are real and useful, and then
the command exits 5 listing the fields it had to remove.

## Consequences

- Interactive exploration is unchanged: the rows appear, the warning explains, the shell shows
  a non-zero status that nobody has to act on.
- A script that checks exit codes cannot be fooled; one that ignores them was already lost.
- 5 is a new exit code. None of the existing four fit: nothing failed, nothing was refused, and
  the arguments were not wrong.
- Returning extra rows is visible in the output. Losing rows is not, which is the whole reason
  the widening direction matters.

## What would change our mind

If the widening turned out to surprise people more than the narrowing did, the flag would
return an empty result and exit 5 rather than a wider one. It would not go back to exiting 0.
