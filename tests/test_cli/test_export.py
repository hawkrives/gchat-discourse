# ABOUTME: Tests for export CLI placeholders
# ABOUTME: Verifies export commands exist and return placeholder output

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from gchat_mirror.cli.main import cli


def test_discourse_start_placeholder(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--config-dir",
            str(tmp_path / "config"),
            "export",
            "discourse",
            "start",
        ],
    )

    assert result.exit_code == 0
    assert "Discourse exporter not yet implemented" in result.output


def test_discourse_status_placeholder(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "--data-dir",
            str(tmp_path / "data"),
            "--config-dir",
            str(tmp_path / "config"),
            "export",
            "discourse",
            "status",
        ],
    )

    assert result.exit_code == 0
    assert "Discourse exporter not yet implemented" in result.output
