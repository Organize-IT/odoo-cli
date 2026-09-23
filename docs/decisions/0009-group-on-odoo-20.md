# 9. `odoo group` on Odoo 20 passes formatted_read_group through

**Status:** accepted — applies [ADR 0001](0001-a-cli-that-returns-odoo-json.md) to a changed server API

## Context

`odoo group` calls `read_group(domain, fields, groupby, lazy=False)`, the method the web
client used up to Odoo 18. Odoo 19 added `formatted_read_group` and kept `read_group` working.
Odoo 20 gave the public name `read_group` to the ORM's internal API: it takes
`(domain, groupby, aggregates, having, offset, limit, order)`, returns tuples of records, and
answers our call with `TypeError: read_group() got an unexpected keyword argument 'lazy'`.

`formatted_read_group` is the JSON form on 20. Its answer is not shaped like `read_group`'s:
a total is keyed `amount_total:sum` instead of `amount_total`, `__count` has to be requested
as an aggregate, the group's filter is `__extra_domain` instead of `__domain`, and `order`
must name a groupby or an aggregate spec (`amount_total:sum desc`), not a field.

## Decision

- `odoo group` still calls `read_group` first. On 15 to 19 nothing changes.
- When the server rejects `lazy` with a `TypeError`, and only then, it calls
  `formatted_read_group(domain, groupby, ["__count", *aggregates])` with the same limit and
  offset, and passes the answer through untouched.
- `--order` terms naming a field that is also totalled are rewritten to the aggregate spec
  before the call. That translates the request, not the data.
- `formatted_read_group` joins `READ_SAFE_METHODS`.

## Consequences

- The same command prints differently keyed rows on 20 than on 19. A script reading
  `amount_total` from `odoo group` output has to read `amount_total:sum` on 20. The README
  and the agent guide say so.
- Odoo 20 pays one failed round trip per `odoo group` before the real call.
- The fallback depends on the wording of a Python `TypeError`. If it changes, the command
  exits 1 with Odoo's error rather than doing something else.

## Alternatives rejected

- **Rename the keys back** (`amount_total:sum` to `amount_total`). It would keep scripts
  working across versions, but it reshapes Odoo's data, which the raw data rule forbids, and
  it would have to guess what `__extra_domain` means to fake `__domain`.
- **Use `formatted_read_group` wherever it exists** (19+). One code path, but it changes the
  output on 19 for no reason the user can see.
- **Pick the method from `server_version`.** Cheaper on 20, but `saas~` builds between majors
  carry API changes early, and the version number would be a guess about the API rather than
  the API's own answer.

## What would change our mind

If Odoo 21 removes `read_group`'s old signature from 19 as well, or users ask for one output
shape across versions, `group` would move to `formatted_read_group` everywhere and the change
would ship as a breaking release with the key names documented once.
