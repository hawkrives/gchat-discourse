# ABOUTME: Tests for the primary CLI entry point
# ABOUTME: Ensures global CLI options and help output behave as expected

from __future__ import annotations

from click.testing import CliRunner

from gchat_mirror.cli.main import cli


def test_cli_help_includes_core_commands() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])

    assert result.exit_code == 0
    assert "GChat Mirror" in result.output
    assert "sync" in result.output
    assert "export" in result.output
    assert "clients" in result.output
