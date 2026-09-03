from pathlib import Path

from typer.testing import CliRunner

from odoocli.cli.app import app
from odoocli.cli.guide_cmd import guide_text

ROOT = Path(__file__).resolve().parents[1]


def test_skill_md_matches_packaged_guide() -> None:
    skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: odoo-cli\n")
    body = skill.split("---", 2)[2].strip()
    assert body == guide_text().strip()


def test_guide_has_no_em_dash() -> None:
    assert "—" not in guide_text()


def test_agent_guide_command_prints_guide() -> None:
    result = CliRunner().invoke(app, ["agent-guide"])
    assert result.exit_code == 0
    assert result.stdout.strip() == guide_text().strip()


def test_version_flag() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0 and "odoocli" in result.stdout
