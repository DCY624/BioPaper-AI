from typer.testing import CliRunner

from biopaper_ai.cli import app


def test_biopaper_console_command_shows_help() -> None:
    result = CliRunner().invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "BioPaper AI" in result.output
