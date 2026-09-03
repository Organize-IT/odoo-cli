"""odoo agent-guide: print the packaged guide written for AI agents."""

from __future__ import annotations

from importlib import resources

import typer

from odoocli.cli.app import app


def guide_text() -> str:
    return resources.files("odoocli").joinpath("AGENT_GUIDE.md").read_text(encoding="utf-8")


@app.command("agent-guide")
def agent_guide() -> None:
    """Print the usage guide written for AI agents (conventions, pitfalls, recipes)."""
    typer.echo(guide_text())
