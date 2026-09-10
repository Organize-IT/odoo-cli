## What and why

<!-- One paragraph. What changes for someone using the CLI, and what problem it solves. -->

## Checks

- [ ] `uv run ruff check && uv run ruff format --check`
- [ ] `uv run mypy`
- [ ] `uv run pytest` passes, coverage at or above 93%
- [ ] A test fails without this change
- [ ] README / `AGENT_GUIDE.md` updated if anything user-visible moved
- [ ] `CHANGELOG.md` entry added
- [ ] Live assertion added if this depends on Odoo's own surface (model, field,
      ORM method, parsed error message)

## Contract impact

<!-- Does this change an exit code, the stdout/stderr split, a guard default,
     retry safety, or the shape of returned data? If yes, say so explicitly. -->

None.
